# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See `PRD.md` for full design/decisions and `README.md` for day-to-day running instructions.

## What this is

A WiFi control system for a drone with **no backup RC transmitter** — this is the single most
important fact about the project and shapes almost every design/safety decision. The Raspberry Pi
link is the sole control path; the ArduPilot flight controller's native `FS_GCS_ENABLE` failsafe
(RTL/Land on heartbeat loss) is the only safety net if the Pi or WiFi drops. Any change touching
arming, the heartbeat loop, or control-message handling has real physical safety implications —
treat it accordingly, and don't weaken the GPS-fix arm gate or heartbeat cadence without reason.

## Architecture

```
[Browser PWA]  <--WebSocket (WiFi AP)-->  [Raspi Zero 2W backend]  <--UART2/MAVLink2-->  [F405 V4 / ArduPilot]
```

- `raspi/mavlink_bridge.py` — `MavlinkBridge` owns the UART2/MAVLink link on its own thread
  (pymavlink I/O is blocking). Exposes a thread-safe "latest value" control surface: `set_control()`
  overwrites the previous stick state rather than queuing, so a backed-up link never replays stale
  input. Runs the heartbeat (1Hz) and `MANUAL_CONTROL` (30Hz) send loops, tracks FC link liveness
  (`FC_HEARTBEAT_TIMEOUT_S`), and pushes telemetry updates to the server via a callback.
- `raspi/server.py` — FastAPI app. Single `/ws` WebSocket multiplexes control-in and telemetry-out
  as JSON (protocol documented in the module docstring). Also serves the PWA (`web/`) as static
  files. Owns one `MavlinkBridge` instance for the process lifetime.
- `raspi/bench_test.py` — standalone script, no FastAPI/server dependency. Talks MAVLink directly
  for Phase 0 bench validation (link, arm/disarm, `MANUAL_CONTROL`, failsafe drill) before the
  backend service exists in the loop. Keep it runnable independent of `server.py`/`mavlink_bridge.py`.
- `web/` — vanilla JS PWA client, no build step or framework. `joystick.js` implements
  `VirtualJoystick` (canvas-based touch stick with per-axis self-centering). `app.js` wires
  joysticks/Gamepad API to the WS protocol and renders telemetry into the HUD.
- `firmware-config/drone.param` — ArduPilot parameters (serial protocol/baud, GCS failsafe,
  arming-without-RC, geofence) applied manually via Mission Planner/QGroundControl/MAVProxy; not
  loaded by any script in this repo.
- `raspi/ap-setup/` — one-time hostapd/dnsmasq scripts turning the Pi's `wlan0` into a standalone
  AP (`192.168.4.1`) so the controller device needs no field/home network.

The GPS-fix arm gate (`fix_type >= 3` required to arm) is enforced independently at two layers by
design: `server.py::_handle_client_message` (app-layer, so the client gets fast feedback) and
`MavlinkBridge._handle_arm_request` (bridge-layer, so arming is refused even if a caller bypasses
the server). Keep both in sync if this logic changes.

## Commands

```bash
cd raspi
pip install -r requirements.txt

# Phase 0 — raw MAVLink link sanity check (run first, props off)
python3 bench_test.py --port /dev/serial0 --baud 57600
python3 bench_test.py --test-manual-control   # also exercise MANUAL_CONTROL
python3 bench_test.py --force-arm             # skip GPS-fix gate, command-path testing only, indoors

# Backend service (WS bridge + serves the PWA)
FC_PORT=/dev/serial0 FC_BAUD=57600 uvicorn server:app --host 0.0.0.0 --port 8000

# One-time WiFi AP setup on the Pi
sudo ap-setup/install.sh
```

There is no test suite, linter, or build step in this repo — validation is physical bench testing
against real (or at least connected) hardware, per `docs/bench-test-checklist.md`.

## Safety-critical docs — read before touching control/arming/failsafe code

- `docs/bench-test-checklist.md` — phase-gated checklist; do not skip ahead to flight-relevant
  work until each phase's boxes are checked.
- `docs/failsafe-drill.md` — the entire safety case for this project. Any change to heartbeat
  timing, arming, or the control-loss path should be re-validated against this drill.
- `docs/wiring.md` — UART2/GPIO wiring and Raspi UART setup (`/dev/serial0` must map to the PL011
  UART, not the Bluetooth mini-UART).

## Conventions

- Control axes throughout (bench script, bridge, WS protocol, PWA) are `x`=roll, `y`=pitch,
  `z`=throttle, `r`=yaw, matching MAVLink `MANUAL_CONTROL`: `x`/`y`/`r` in `[-1000, 1000]`, `z`
  (throttle) in `[0, 1000]`.
- `SERIAL2_BAUD`/`FC_BAUD`/`--baud` must match `FC_PORT` value in `firmware-config/drone.param`.
