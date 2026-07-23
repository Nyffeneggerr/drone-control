# Drone WiFi Control System

See `PRD.md` for full design/decisions. This README covers day-to-day running.

## 1. Apply `drone.param` to ArduPilot

Do this once per FC (or after a firmware reset). Review every value against your actual FC first — `firmware-config/drone.param` is a starting point, not gospel (baud rate, fence radius/altitude especially).

**Mission Planner:**
1. Connect to the FC over USB.
2. CONFIG/TUNING -> Full Parameter List -> "Load from file" -> select `firmware-config/drone.param` -> "Write Params".

**QGroundControl:**
1. Connect over USB.
2. Vehicle Setup -> Parameters -> Tools (top right) -> "Load from file" -> select `firmware-config/drone.param`.

**MAVProxy (CLI):**
```
mavproxy.py --master=/dev/ttyACM0
param load firmware-config/drone.param
```

After loading, reboot the FC and confirm with `param show SERIAL3_PROTOCOL` (or the GCS's parameter list) that values stuck.

## 2. Run the Raspi side

On the Raspi (after wiring per `docs/wiring.md`):

```bash
cd raspi
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt  # Raspi OS Bookworm blocks system-wide pip installs
source .venv/bin/activate
```

**One-time AP setup** (turns wlan0 into the `drone-control` WiFi AP):
```bash
sudo ap-setup/install.sh
```
Edit `ap-setup/hostapd.conf`'s `wpa_passphrase` before running this on a real flight box — it ships with a placeholder.

**Phase 0 — raw link sanity check** (run this first, props off, before trusting anything else):
```bash
python3 bench_test.py --port /dev/serial0 --baud 57600
```
Add `--test-manual-control` to also exercise MANUAL_CONTROL, `--force-arm` to skip the GPS-fix gate for command-path-only testing indoors. Full checklist: `docs/bench-test-checklist.md`. Do not skip the failsafe drill (`docs/failsafe-drill.md`) at this stage.

**Status (2026-07-23):** this airframe has no GPS module at all (confirmed 2026-07-21) — the GPS-fix arm gate has since been removed, not confirmed. Link, arm/disarm, `--test-manual-control`, and telemetry streaming (`GPS_RAW_INT`/`SYS_STATUS`/`VFR_HUD`, which need an explicit `REQUEST_DATA_STREAM` — added 2026-07-23) are all confirmed working, on UART3 (not UART2 — see `docs/wiring.md`). Phase 1's service-level failsafe drill and the Phase 2/3 full-stack drill through the actual PWA (run over the existing home WiFi, not the dedicated AP) are now also confirmed — same timing/mode-caveat as the Phase 0 result each time. A real reconnect-race bug was found in `web/app.js` (status bar can get stuck on DISCONNECTED after repeated link drops within one page session even though the socket is actually fine) — matches the already-planned PRD Phase 4 reconnect hardening, not yet fixed. Outstanding: the AP setup (`ap-setup/install.sh` not yet run on the actual flight box), a hands-on pass with a real touchscreen/gamepad (this session used browser automation, no physical device), and the outdoor failsafe drill (Land-engagement + FC LED/buzzer behavior, deferred from every bench attempt so far — see checklist). See `docs/bench-test-checklist.md` for the live checklist.

**Backend service** (WS bridge + serves the PWA):
```bash
FC_PORT=/dev/serial0 FC_BAUD=57600 uvicorn server:app --host 0.0.0.0 --port 8000
```
`FC_PORT`/`FC_BAUD` default to `/dev/serial0`/`57600` if unset — must match `SERIAL3_BAUD` on the FC.

To deploy code changes from a dev machine instead of editing on the Pi directly: `raspi/sync-to-pi.sh` rsyncs both `raspi/` and `web/` to the Pi as siblings (`~/raspi`, `~/web` by default) — `server.py` expects that layout since it serves `web/` relative to its own location.

To run this automatically on boot, add a systemd unit (`ExecStart=uvicorn server:app --host 0.0.0.0 --port 8000`, `WorkingDirectory=.../drone-control/raspi`) and `systemctl enable` it — not included yet, add when you're ready to stop running it by hand.

## 3. Run the controller (PWA)

1. Connect your phone/tablet/laptop to the `drone-control` WiFi AP (password set in `hostapd.conf`).
2. Open `http://192.168.4.1:8000/` in the browser.
3. Status bar should read CONNECTED; HUD should populate once the FC link is up.
4. Optional: plug in a physical gamepad — the Gamepad API takes over from the on-screen virtual sticks automatically.
5. Optional: "Add to Home Screen" / install the PWA for a fullscreen app-like launch.

Full verification steps for this stage: `docs/bench-test-checklist.md` (Phase 2/3 section).

## Safety

No backup RC transmitter exists for this vehicle. The FC-native `FS_GCS_ENABLE` failsafe (set by `drone.param`) is the sole safety net if the Raspi or WiFi link fails. Run the failsafe drill in `docs/failsafe-drill.md` at every phase boundary, and again outdoors before the first real flight.
