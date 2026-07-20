#!/usr/bin/env python3
"""Phase 0 bench validation script.

Run on the Raspi with props OFF. Connects to the FC over UART2 (MAVLink2),
sends heartbeats, arms/disarms, sends test MANUAL_CONTROL values, and prints
telemetry. Use this to prove the link works and to run the mandatory
heartbeat-loss failsafe drill (Ctrl+C or unplug WiFi/kill this process and
confirm the FC enters RTL/Land on its own).

Usage:
    python3 bench_test.py [--port /dev/serial0] [--baud 57600]
"""
import argparse
import sys
import time

from pymavlink import mavutil

HEARTBEAT_HZ = 1
MANUAL_CONTROL_HZ = 30
GPS_FIX_TYPE_3D = 3


def connect(port: str, baud: int) -> mavutil.mavfile:
    print(f"Connecting to {port} @ {baud}...")
    conn = mavutil.mavlink_connection(port, baud=baud)
    conn.wait_heartbeat()
    print(
        f"Heartbeat received from system {conn.target_system}, "
        f"component {conn.target_component}"
    )
    return conn


def send_heartbeat(conn: mavutil.mavfile) -> None:
    conn.mav.heartbeat_send(
        mavutil.mavlink.MAV_TYPE_GCS,
        mavutil.mavlink.MAV_AUTOPILOT_INVALID,
        0,
        0,
        0,
    )


def get_gps_fix_type(conn: mavutil.mavfile, timeout: float = 2.0) -> int:
    msg = conn.recv_match(type="GPS_RAW_INT", blocking=True, timeout=timeout)
    return msg.fix_type if msg else 0


def arm(conn: mavutil.mavfile, force: bool = False) -> bool:
    fix_type = get_gps_fix_type(conn)
    if fix_type < GPS_FIX_TYPE_3D and not force:
        print(f"Refusing to arm: GPS fix_type={fix_type} (< 3D fix). Use --force to override.")
        return False

    conn.mav.command_long_send(
        conn.target_system,
        conn.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,
        1,  # arm
        0, 0, 0, 0, 0, 0,
    )
    ack = conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=3)
    ok = bool(ack and ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED)
    print(f"Arm {'accepted' if ok else 'REJECTED'} (ack={ack})")
    return ok


def disarm(conn: mavutil.mavfile) -> None:
    conn.mav.command_long_send(
        conn.target_system,
        conn.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,
        0,  # disarm
        0, 0, 0, 0, 0, 0,
    )
    ack = conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=3)
    print(f"Disarm ack={ack}")


def send_manual_control(conn: mavutil.mavfile, x: int, y: int, z: int, r: int) -> None:
    """x/y/r in [-1000,1000], z (throttle) in [0,1000]. 0 stick = neutral."""
    conn.mav.manual_control_send(
        conn.target_system,
        x, y, z, r,
        0,  # buttons bitmask
    )


def print_telemetry(conn: mavutil.mavfile) -> None:
    msg = conn.recv_match(
        type=["GPS_RAW_INT", "SYS_STATUS", "HEARTBEAT", "VFR_HUD"],
        blocking=False,
    )
    if msg:
        print(msg)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/serial0")
    parser.add_argument("--baud", type=int, default=57600)
    parser.add_argument("--force-arm", action="store_true", help="skip GPS fix check (bench only, props off)")
    parser.add_argument("--test-manual-control", action="store_true", help="send a few seconds of neutral MANUAL_CONTROL after arming")
    args = parser.parse_args()

    conn = connect(args.port, args.baud)

    print("Sending heartbeats + telemetry for 5s (sanity check)...")
    last_hb = 0.0
    end = time.time() + 5
    while time.time() < end:
        now = time.time()
        if now - last_hb >= 1.0 / HEARTBEAT_HZ:
            send_heartbeat(conn)
            last_hb = now
        print_telemetry(conn)
        time.sleep(0.05)

    if not arm(conn, force=args.force_arm):
        return 1

    if args.test_manual_control:
        print("Sending neutral MANUAL_CONTROL for 3s at 30Hz (props OFF)...")
        end = time.time() + 3
        last_hb = 0.0
        while time.time() < end:
            now = time.time()
            if now - last_hb >= 1.0 / HEARTBEAT_HZ:
                send_heartbeat(conn)
                last_hb = now
            send_manual_control(conn, x=0, y=0, z=0, r=0)
            time.sleep(1.0 / MANUAL_CONTROL_HZ)

    disarm(conn)

    print(
        "\nNow run the failsafe drill: Ctrl+C this script (or unplug Raspi WiFi) "
        "and confirm on a separate GCS / by FC LED behavior that RTL/Land triggers "
        "within FS_GCS_TIMEOUT seconds of heartbeat loss."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
