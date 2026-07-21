# Bench Test Checklist

Props OFF for all steps below unless explicitly noted otherwise. This checklist gates every phase in PRD.md — do not skip ahead to flight until every phase's checklist passes.

## Phase 0 — raw link (`raspi/bench_test.py`)

**✅ 2026-07-21 — uplink (Pi→FC) dead-link issue found and resolved; root cause was a damaged FC pin.**
Investigation trail (kept for reference — don't repeat this diagnosis if the link ever goes dead
again, check the resolution first):
1. `/dev/serial0` was mapped to the Bluetooth mini-UART (`ttyS0`) instead of the PL011 UART
   (`ttyAMA0`) — `docs/wiring.md` setup step 2 had never been applied. Fixed (confirmed
   `/dev/serial0 -> ttyAMA0`), but not the root cause: uplink was still dead after this fix.
2. Ruled out (all tested and eliminated): MAVLink2 signing, missing GCS-heartbeat-presence,
   MAVLink1-vs-2 wire format, wiring/pinout per docs (multimeter continuity), SBUS-pin-inversion
   sharing.
3. Moved to UART3 (R3/T3) as an experiment — dead silence (zero bytes), but this was a red herring:
   `SERIAL3_PROTOCOL` was still at its factory default (5 = GPS), not MAVLink. Confirmed via direct
   USB connection to the FC (`SERIAL2_PROTOCOL=2`/`SERIAL2_BAUD=57` already correct, matching
   `drone.param`; full 1111-param diff against `drone.param` showed **zero differences** — params
   were never the problem).
4. Root cause found via voltage measurement with the FC back on UART2 and powered: **R2 reads
   2.6V to GND, where T2, R3, and T3 all read a clean 3.3V idle-high.** A Pi-side TX/RX loopback
   test (GPIO14 jumpered to GPIO15) passed perfectly, ruling out the Pi entirely. Conclusion: the
   FC's R2 pin is electrically damaged (multi-megohm leakage to ground) — not a wiring, baud, or
   config issue.
5. **Fix:** moved the physical link to UART3 (R3/T3), set `SERIAL3_PROTOCOL=2`/`SERIAL3_BAUD=57`
   over USB (bypassing the chicken-and-egg problem of needing a working uplink to configure the
   port that provides the uplink). Re-tested `PARAM_REQUEST_READ` from the Pi over the new UART3
   link — got a real `PARAM_VALUE` response, repeatably. **Uplink confirmed working.**
   `docs/wiring.md` and `firmware-config/drone.param` updated to UART3/`SERIAL3_*`. Do not rewire
   back to UART2/R2 without re-checking that 2.6V reading first.

- [x] FC parameters loaded from `firmware-config/drone.param`, reviewed against actual FC (baud, fence radius/alt for your site). (2026-07-21: confirmed via full param diff over USB, FC matches `drone.param` exactly, 1111/1111 params, no differences.)
- [x] Wiring per `docs/wiring.md` confirmed with a multimeter continuity check before power-on. (2026-07-21: UART3/R3-T3 wiring confirmed; see root-cause note above for the R2/UART2 story.)
- [x] `python3 raspi/bench_test.py --port /dev/serial0 --baud 57600` connects, prints heartbeat from FC. (2026-07-20: confirmed, heartbeat `{type: 2, autopilot: 3, ...}` received.)
- [x] Telemetry (`GPS_RAW_INT`, `SYS_STATUS`, `VFR_HUD`) visible in script output. (2026-07-21: confirmed over UART3 with an explicit `REQUEST_DATA_STREAM` — 14x `GPS_RAW_INT`, 14x `SYS_STATUS`, 15x `VFR_HUD` in 8s. `GPS_RAW_INT.fix_type=0`/`satellites_visible=0` is now known to be a genuine no-fix indoors, not a missing-stream artifact, since the stream is confirmed flowing.)
- [x] Arm refused while GPS fix_type < 3 (script default behavior) — confirm the refusal path actually triggers by testing indoors/no-fix. (2026-07-20: confirmed, `Refusing to arm: GPS fix_type=0 (< 3D fix)` — see telemetry caveat above on whether this is a real no-fix or a missing stream.)
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
