# Bench Test Checklist

Props OFF for all steps below unless explicitly noted otherwise. This checklist gates every phase in PRD.md — do not skip ahead to flight until every phase's checklist passes.

## Phase 0 — raw link (`raspi/bench_test.py`)

- [ ] FC parameters loaded from `firmware-config/drone.param`, reviewed against actual FC (baud, fence radius/alt for your site).
- [ ] Wiring per `docs/wiring.md` confirmed with a multimeter continuity check before power-on.
- [ ] `python3 raspi/bench_test.py --port /dev/serial0 --baud 57600` connects, prints heartbeat from FC.
- [ ] Telemetry (`GPS_RAW_INT`, `SYS_STATUS`, `VFR_HUD`) visible in script output.
- [ ] Arm refused while GPS fix_type < 3 (script default behavior) — confirm the refusal path actually triggers by testing indoors/no-fix.
- [ ] Arm succeeds outdoors with GPS fix (or via `--force-arm` indoors, motors disconnected/props off, for command-path testing only).
- [ ] `--test-manual-control` sends neutral MANUAL_CONTROL for 3s without FC rejecting/disconnecting.
- [ ] Disarm succeeds.
- [ ] **Failsafe drill (non-negotiable):** with script running and armed (props off), kill the script (Ctrl+C) or pull Raspi WiFi power. Confirm via a separate GCS (Mission Planner / QGroundControl on another device connected to the FC, or FC status LED pattern) that RTL or Land triggers within `FS_GCS_TIMEOUT` seconds. Do not proceed to Phase 1 until this is confirmed.

## Phase 1 — backend service (`raspi/server.py`)

- [ ] `pip install -r raspi/requirements.txt` on the Raspi.
- [ ] AP up: `raspi/ap-setup/install.sh` run once, `hostapd.conf` passphrase changed from default, AP visible from a phone/laptop, DHCP lease obtained.
- [ ] `FC_PORT=/dev/serial0 FC_BAUD=57600 uvicorn server:app --host 0.0.0.0 --port 8000` (from `raspi/`) starts without error, connects to FC.
- [ ] From a WS client (browser devtools or `websocat ws://192.168.4.1:8000/ws`), send `{"type":"arm"}` / `{"type":"disarm"}` / `{"type":"control",...}` and confirm FC responds (motors beep / arm state changes) with props off.
- [ ] Telemetry JSON streams back over the same socket at a reasonable rate.
- [ ] Repeat the Phase 0 failsafe drill through the service: kill `server.py` (or the whole Pi's WiFi), confirm FC-side RTL/Land within `FS_GCS_TIMEOUT`.

## Phase 2/3 — full stack via PWA

- [ ] Connect a phone/tablet to the `drone-control` AP, load `http://192.168.4.1:8000/` (or whatever host:port `server.py` binds).
- [ ] Status bar shows CONNECTED, HUD populates (armed state, mode, battery, GPS, alt).
- [ ] Virtual joysticks: left stick throttle holds position on release, yaw snaps to center; right stick (roll/pitch) snaps to center on both axes.
- [ ] Connect a physical gamepad (Gamepad API) — virtual sticks hide, gamepad indicator shows, stick movement drives MANUAL_CONTROL identically.
- [ ] ARM/DISARM buttons and mode dropdown work from the UI.
- [ ] Subjective input latency check: stick movement to visible motor/telemetry response feels acceptable on the local AP link (note actual delay if measurable).
- [ ] Repeat the failsafe drill one more time through the full PWA stack: kill the Pi's WiFi or the `server.py` process while "armed" (props off), confirm RTL/Land triggers, confirm the PWA's status bar correctly flips to "FC LINK LOST".

## Before first real flight

- [ ] All boxes above checked, on the actual airframe, at the actual flight site.
- [ ] Outdoor failsafe drill repeated per `docs/failsafe-drill.md`, low altitude, spotter ready to catch/land manually.
- [ ] Geofence (`FENCE_*` params) values confirmed correct for the site.
