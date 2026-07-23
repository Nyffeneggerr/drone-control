"""MAVLink bridge: owns the UART2 link to the FC.

Runs its own thread (pymavlink's socket I/O is blocking). Exposes a
thread-safe "latest value" control surface — new control updates simply
overwrite the previous one, so a slow/backed-up link never plays back
stale stick data. Telemetry is pushed out through an asyncio-safe queue
so the WS server can pick it up without polling pymavlink directly.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from pymavlink import mavutil

HEARTBEAT_HZ = 1.0
MANUAL_CONTROL_HZ = 30.0
TELEMETRY_STREAM_HZ = 4  # requested rate for GPS_RAW_INT/SYS_STATUS/VFR_HUD; FC doesn't send these unsolicited
STALE_CONTROL_TIMEOUT_S = 0.5  # if browser stops sending, fall back to neutral/no-input rather than replay old sticks
FC_HEARTBEAT_TIMEOUT_S = 3.0  # no HEARTBEAT from FC within this window -> report link down to the UI
FORCE_DISARM_MAGIC = 21196  # ArduPilot's magic param2 value to force disarm past the landed-check
DISARM_ACK_TIMEOUT_S = 3.0  # if a plain disarm isn't acked (or is rejected) within this window, force it

# Mirrors BATT_LOW_VOLT/BATT_CRT_VOLT in firmware-config/drone.param (6S LiPo, confirmed
# 2026-07-23) -- keep these in sync with the live FC params if either changes.
BATT_LOW_VOLT = 21.0
BATT_CRT_VOLT = 19.8


@dataclass
class ControlState:
    x: int = 0  # roll, -1000..1000
    y: int = 0  # pitch, -1000..1000
    z: int = 0  # throttle, 0..1000
    r: int = 0  # yaw, -1000..1000
    updated_at: float = field(default_factory=time.time)


@dataclass
class Telemetry:
    armed: bool = False
    mode: str = "UNKNOWN"
    link_ok: bool = False
    battery_voltage: Optional[float] = None
    battery_remaining: Optional[int] = None
    gps_fix_type: int = 0
    satellites_visible: int = 0
    lat: Optional[float] = None
    lon: Optional[float] = None
    alt: Optional[float] = None
    fence_breached: bool = False
    battery_status: str = "unknown"  # "unknown" | "normal" | "low" | "critical"


class MavlinkBridge:
    def __init__(self, port: str, baud: int, on_telemetry: Callable[[Telemetry], None]):
        self._port = port
        self._baud = baud
        self._on_telemetry = on_telemetry

        self._conn: Optional[mavutil.mavfile] = None
        self._lock = threading.Lock()
        self._control = ControlState()
        self._telemetry = Telemetry()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._pending_arm: Optional[bool] = None  # True=arm, False=disarm, set by caller, consumed by loop thread
        self._pending_mode: Optional[str] = None
        self._last_fc_heartbeat_rx: Optional[float] = None
        self._disarm_ack_deadline: Optional[float] = None  # set while waiting to confirm a plain disarm landed

    # --- public API, called from the asyncio/WS side ---

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def set_control(self, x: int, y: int, z: int, r: int) -> None:
        with self._lock:
            self._control = ControlState(x=x, y=y, z=z, r=r)

    def request_arm(self) -> None:
        self._pending_arm = True

    def request_disarm(self) -> None:
        self._pending_arm = False

    def request_mode(self, mode: str) -> None:
        self._pending_mode = mode

    def get_telemetry(self) -> Telemetry:
        with self._lock:
            return self._telemetry

    # --- internal: runs on the bridge thread ---

    def _run(self) -> None:
        self._conn = mavutil.mavlink_connection(self._port, baud=self._baud)
        self._conn.wait_heartbeat()
        # FC only sends HEARTBEAT unsolicited; GPS_RAW_INT/SYS_STATUS/VFR_HUD need an explicit request
        self._conn.mav.request_data_stream_send(
            self._conn.target_system,
            self._conn.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL,
            TELEMETRY_STREAM_HZ,
            1,
        )

        last_hb = 0.0
        last_manual = 0.0
        self._last_fc_heartbeat_rx = time.time()

        while not self._stop.is_set():
            now = time.time()

            if now - last_hb >= 1.0 / HEARTBEAT_HZ:
                self._send_heartbeat()
                last_hb = now

            if now - self._last_fc_heartbeat_rx > FC_HEARTBEAT_TIMEOUT_S:
                with self._lock:
                    if self._telemetry.link_ok:
                        self._telemetry.link_ok = False
                        self._on_telemetry(self._telemetry)

            if self._pending_arm is not None:
                self._handle_arm_request(self._pending_arm)
                self._pending_arm = None

            if self._disarm_ack_deadline is not None and now > self._disarm_ack_deadline:
                self._force_disarm()
                self._disarm_ack_deadline = None

            if self._pending_mode is not None:
                self._handle_mode_request(self._pending_mode)
                self._pending_mode = None

            if now - last_manual >= 1.0 / MANUAL_CONTROL_HZ:
                self._send_manual_control(now)
                last_manual = now

            self._drain_incoming()
            time.sleep(0.005)

    def _send_heartbeat(self) -> None:
        self._conn.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0, 0, 0,
        )

    def _send_manual_control(self, now: float) -> None:
        with self._lock:
            control = self._control
        stale = (now - control.updated_at) > STALE_CONTROL_TIMEOUT_S
        x, y, z, r = (0, 0, 0, 0) if stale else (control.x, control.y, control.z, control.r)
        self._conn.mav.manual_control_send(self._conn.target_system, x, y, z, r, 0)

    def _handle_arm_request(self, arm: bool) -> None:
        self._conn.mav.command_long_send(
            self._conn.target_system,
            self._conn.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            1 if arm else 0,
            0, 0, 0, 0, 0, 0,
        )
        # a fresh arm supersedes any still-pending disarm-ack tracking, so a stale ack
        # (or the timeout fallback) can't force-disarm after the operator re-armed
        self._disarm_ack_deadline = time.time() + DISARM_ACK_TIMEOUT_S if not arm else None

    def _force_disarm(self) -> None:
        # ArduPilot refuses a plain disarm if it doesn't yet trust the vehicle is landed
        # (e.g. right after throttle was applied); param2=FORCE_DISARM_MAGIC overrides that.
        self._conn.mav.command_long_send(
            self._conn.target_system,
            self._conn.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            0, FORCE_DISARM_MAGIC, 0, 0, 0, 0, 0,
        )

    def _handle_mode_request(self, mode: str) -> None:
        mapping = self._conn.mode_mapping()
        if not mapping or mode not in mapping:
            return
        self._conn.mav.set_mode_send(
            self._conn.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mapping[mode],
        )

    def _drain_incoming(self) -> None:
        changed = False
        while True:
            msg = self._conn.recv_match(blocking=False)
            if msg is None:
                break
            changed = self._apply_message(msg) or changed
        if changed:
            self._on_telemetry(self.get_telemetry())

    def _apply_message(self, msg) -> bool:
        msg_type = msg.get_type()
        force_disarm_needed = False
        changed = True
        with self._lock:
            t = self._telemetry
            if msg_type == "HEARTBEAT":
                self._last_fc_heartbeat_rx = time.time()
                t.armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                mapping = self._conn.mode_mapping() if self._conn else None
                if mapping:
                    t.mode = next((name for name, num in mapping.items() if num == msg.custom_mode), t.mode)
                t.link_ok = True
            elif msg_type == "SYS_STATUS":
                t.battery_voltage = msg.voltage_battery / 1000.0
                t.battery_remaining = msg.battery_remaining
                if t.battery_voltage <= BATT_CRT_VOLT:
                    t.battery_status = "critical"
                elif t.battery_voltage <= BATT_LOW_VOLT:
                    t.battery_status = "low"
                else:
                    t.battery_status = "normal"
            elif msg_type == "GPS_RAW_INT":
                t.gps_fix_type = msg.fix_type
                t.satellites_visible = msg.satellites_visible
                t.lat = msg.lat / 1e7
                t.lon = msg.lon / 1e7
            elif msg_type == "VFR_HUD":
                t.alt = msg.alt
            elif msg_type == "FENCE_STATUS":
                # ArduPilot-specific message with a direct breach_status bool -- preferred over
                # decoding the generic SYS_STATUS geofence health bit or scraping STATUSTEXT,
                # neither of which distinguish "breached" from "fence disabled"/other unhealthy.
                t.fence_breached = bool(msg.breach_status)
            elif (
                msg_type == "COMMAND_ACK"
                and msg.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
                and self._disarm_ack_deadline is not None
            ):
                force_disarm_needed = msg.result != mavutil.mavlink.MAV_RESULT_ACCEPTED
                self._disarm_ack_deadline = None
                changed = False
            else:
                changed = False
        if force_disarm_needed:
            self._force_disarm()
        return changed
