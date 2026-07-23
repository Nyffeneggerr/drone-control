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
- [x] Arm succeeds (command-path testing, motors disconnected/props off).
  - **2026-07-21: root cause found — this airframe has no GPS module at all** (never wired, confirmed by the user; not a wiring/config bug). Outdoor test showed `SYS_STATUS` GPS sensor bit `present=False` and `sats=0` throughout. Accelerometer calibration (QGroundControl, USB) resolved `3D Accel calibration needed`. Removed the now-obsolete app-layer/bridge-layer GPS-fix arm gates in `server.py`/`mavlink_bridge.py` (see `CLAUDE.md`); `bench_test.py --force-arm` still bypasses its own standalone gate the same way as before.
  - FC-side changes applied via QGroundControl (USB, battery disconnected each time): `ARMING_CHECK` relaxed to exclude RC + GPS-lock (+ compass, since it was still reporting unhealthy with no module); `FS_GCS_ENABLE=3` (Land, not RTL); `FENCE_TYPE=1` (altitude-only).
  - Hit two more blockers along the way, both resolved: (1) `Logging failed`/`Logging not started` — the SD card slot was empty; inserting a card wasn't enough on its own (SD is only detected at FC boot, needed a power cycle), and the card also had no partition/filesystem at all (`lsblk`/`blkid` showed nothing) — reformatted as MBR + single FAT32 partition (`ARDULOG` label) from the laptop, reinserted, rebooted FC, logging check cleared. (2) `Radio Failsafe - Disarming` immediately after a successful arm — `FS_THR_ENABLE` (RC/throttle failsafe, distinct from `FS_GCS_ENABLE`) was still at its factory default and expects RC signal that will never exist on this airframe; set to `0` via QGC, documented in `firmware-config/drone.param`. `FS_GCS_ENABLE` remains the sole/intended failsafe.
  - 2026-07-21: `bench_test.py --port /dev/serial0 --baud 57600 --force-arm --test-manual-control` ran clean end to end — arm accepted, 3s neutral `MANUAL_CONTROL` at 30Hz with no rejection/disconnect, disarm accepted.
- [x] `--test-manual-control` sends neutral MANUAL_CONTROL for 3s without FC rejecting/disconnecting. (2026-07-21: confirmed, see above.)
- [x] Disarm succeeds. (2026-07-21: confirmed, see above — also separately observed the FC auto-disarm on its own a few seconds after a test script exited and heartbeats stopped, consistent with `FS_GCS_ENABLE` Land + landed-disarm behavior.)
- [ ] **Failsafe drill (non-negotiable):** with script running and armed (props off), kill the script (Ctrl+C) or pull Raspi WiFi power. Confirm via a separate GCS (Mission Planner / QGroundControl on another device connected to the FC, or FC status LED pattern) that **Land** triggers within `FS_GCS_TIMEOUT` seconds (not RTL — no GPS home position exists on this airframe). Do not proceed to Phase 1 until this is confirmed.
  - **2026-07-21: ran on the bench (props off, stationary, armed via SSH), partial/inconclusive result.** Timing was right — armed went `True`→`False` at t=5.8s, matching `FS_GCS_TIMEOUT=5`. But flight mode stayed `STABILIZE` throughout; it never switched to `LAND`. Read: ArduCopter's landed-detector most likely short-circuited the failsafe straight to a disarm, since the vehicle was stationary at zero throttle the whole time — switching to `LAND` mode is probably suppressed as pointless when already on the ground. This is a safe outcome for a ground test but does **not** confirm the actual in-flight behavior (`LAND` engaging and executing a controlled descent), which can only be observed while the FC believes it's airborne.
  - Separately, **no FC LED or buzzer change was observed** at the failsafe moment, despite telemetry (via the same Pi/UART link) clearly showing the disarm at t=5.8s. This matters: if the real-world failure is "Pi crashes/loses power entirely" rather than "script gets killed," that same telemetry channel is gone too — the FC's own physical indicators would be the only signal available in the field, and today we don't know if this board gives one reliably. Watch closely for any LED/buzzer change during the outdoor repeat.
  - Deferred to the outdoor low-altitude hover repeat (see "Outdoor pre-flight repeat" below) per user decision 2026-07-21 — do not mark this box done until Land-engagement and the LED/buzzer question are both actually confirmed there, with a spotter present.

**2026-07-23 — `firmware-config/drone.param` synced with the live FC (was drifted).** The FC-side
changes applied via QGroundControl on 2026-07-21 (see arm-succeeds entry above) had never been
written back to the checked-in param file — reloading it onto a reset FC would have silently
reintroduced RTL-without-GPS and full arming checks. Read the actual live values directly over
MAVLink (`PARAM_REQUEST_READ`) rather than guess, and corrected the file:
- `FS_GCS_ENABLE`: file said `1` (RTL), live FC has `5` (Land). (Checklist prose above says the
  applied value was "3" — that was a recording mistake; 5 is what's actually on the FC and is the
  correct value: Land, not RTL, since there's no GPS. Note the discrepancy in case "3" is ever
  quoted elsewhere.)
- `ARMING_CHECK`: file said `1` (all checks), live FC has `9650` (excludes RC/GPS-lock/Compass,
  per the arm-succeeds entry above). Documented the exact bitmask in `drone.param` now.
- `FENCE_TYPE`: file said `7` (alt+circle+polygon), live FC has `1` (altitude-only, matching
  CLAUDE.md's no-GPS constraint).

## Phase 1 — backend service (`raspi/server.py`)

- [x] `pip install -r raspi/requirements.txt` on the Raspi. (2026-07-23: Raspi OS is now Bookworm,
  which blocks system-wide pip installs — needed a venv, `README.md`/`CLAUDE.md` updated.
  `requirements.txt` was also missing `pyserial`, a hard dependency of pymavlink's serial backend —
  without it the bridge thread crashed on startup with `ModuleNotFoundError: No module named
  'serial'`. Fixed; installed clean.)
- [ ] AP up: `raspi/ap-setup/install.sh` run once, `hostapd.conf` passphrase changed from default, AP visible from a phone/laptop, DHCP lease obtained. (Not attempted this session — remote/SSH only, no phone in hand.)
- [x] `FC_PORT=/dev/serial0 FC_BAUD=57600 uvicorn server:app --host 0.0.0.0 --port 8000` (from `raspi/`) starts without error, connects to FC. (2026-07-23: confirmed after the `pyserial` fix above. Also found `raspi/sync-to-pi.sh` only ever synced `raspi/` — `server.py` expects `web/` as a sibling directory and would fail `StaticFiles` mount without it. Fixed to sync both.)
- [x] From a WS client, send `{"type":"arm"}` / `{"type":"disarm"}` / `{"type":"control",...}` and confirm FC responds with props off. (2026-07-23: exercised over a plain Python `websockets` script, not a browser — arm/disarm/mode/control messages all accepted with no server errors, and telemetry's `armed` field reflected disarm correctly. **Did not visually/audibly confirm props-off arm behavior (motor beep) — no one was physically present at the airframe during this remote session.** Treat this box as protocol-level only; do a hands-on repeat before trusting it fully.)
- [x] Telemetry JSON streams back over the same socket at a reasonable rate. (2026-07-23: initially `battery_voltage`/`alt` came back `null` even with the FC connected — root cause: the bridge never sent `REQUEST_DATA_STREAM`, so the FC only ever pushed unsolicited `HEARTBEAT`. Added an explicit `REQUEST_DATA_STREAM` request (`MAV_DATA_STREAM_ALL` @ 4Hz) to both `mavlink_bridge.py` and `bench_test.py`. After the fix, confirmed live: `battery_voltage=24.05`, `battery_remaining=78%`, `alt≈0`, `gps_fix_type=0`/`satellites_visible=0` (expected, no GPS module).)
- [ ] Repeat the Phase 0 failsafe drill through the service: kill `server.py` (or the whole Pi's WiFi), confirm FC-side RTL/Land within `FS_GCS_TIMEOUT`.

## Phase 2/3 — full stack via PWA

**2026-07-23 — mode dropdown offered GPS-dependent modes on a no-GPS airframe.** `web/index.html`'s
`#mode-select` listed LOITER/GUIDED/RTL alongside STABILIZE/ALT_HOLD/LAND — the first three all need
a position estimate per CLAUDE.md, which this airframe cannot produce. Removed; dropdown now only
offers STABILIZE/ALT_HOLD/LAND. Bumped the service worker's `CACHE_NAME` so a browser that already
cached the old shell picks up the fix on next load instead of serving stale HTML.

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
