# Drone WiFi Control System — Plan

## Context

Drone hardware ready (Speedy Bee F405 V4 flight controller, likely running ArduPilot; Raspberry Pi Zero 2 W soldered to FC UART2 / R2-T2). Goal: rebuild the control chain from scratch — Raspi acts as WiFi bridge between flight controller and a browser-based (PWA) control client, replacing a laggy 2-years-ago Python prototype. **The Raspi link is the sole control path — no backup RC transmitter exists**, which makes flight-controller-native failsafe the critical safety net and shapes several decisions below.

All project files go in `/home/rolf/workspace/drone-control` (currently empty).

## Decisions made with user

- **Firmware:** ArduPilot (to confirm/flash on FC) — chosen over Betaflight/iNAV because MAVLink + companion-computer joystick control (`MANUAL_CONTROL` message) is a first-class, well-documented ArduPilot use case, with mature Python tooling (`pymavlink`).
- **FC link:** keep existing UART2 (R2/T2) solder joints, configure as MAVLink2 serial port.
- **Failsafe:** flight-controller-native, using `FS_GCS_ENABLE` (FC watches for MAVLink heartbeats from the Raspi acting as GCS; loss of heartbeat — whether from WiFi drop *or* Raspi crash — triggers RTL/Land automatically, independent of Raspi health).
- **Network:** Raspi runs as its own WiFi Access Point (hostapd/dnsmasq); controller device connects directly, no dependency on field/home infrastructure.
- **Client:** browser-based PWA (not native Android) — instant deployment, no install/signing, Gamepad API covers physical controllers, easiest iteration.
- **Control feel:** start with direct manual stick control (roll/pitch/yaw/throttle via `MANUAL_CONTROL`), semi-autonomous (GUIDED-mode position/velocity targets) as later phase.
- **No backup transmitter exists** → safety design leans entirely on FC-side failsafe + deliberate arm/disarm UX + bench validation before any flight.

## Architecture

```
[Browser PWA]  <--WebSocket (WiFi AP)-->  [Raspi Zero 2W backend]  <--UART2/MAVLink2-->  [F405 V4 / ArduPilot]
  - gamepad or virtual sticks               - hostapd+dnsmasq (AP)
  - telemetry HUD                           - FastAPI/aiohttp: serves PWA + WS endpoint
  - arm/disarm, mode buttons                - pymavlink: MANUAL_CONTROL @ ~30Hz,
                                               heartbeat @1Hz, telemetry relay
```

## Project layout (`/home/rolf/workspace/drone-control`)

- `raspi/` — Python backend: MAVLink bridge, WebSocket/HTTP server, AP setup scripts/config
- `web/` — PWA client (vanilla JS or minimal framework; small scope doesn't need much)
- `firmware-config/` — ArduPilot `.param` file(s) documenting required parameter changes
- `docs/` — wiring notes, bench-test checklist, failsafe test procedure

## Key ArduPilot configuration (bench work, Phase 0)

- `SERIAL2_PROTOCOL = 2` (MAVLink2) on the UART2 port wired to the Raspi; baud matched on both ends (start conservative, e.g. 57600, raise later if needed for telemetry rate).
- `FS_GCS_ENABLE` set so loss of companion-computer heartbeat triggers RTL (or Land if no GPS fix) — this is the sole safety net given no backup transmitter, so it must be bench-verified before ever flying.
- Arming without an RC receiver: confirm `ARMING_CHECKS`/`RC_PROTOCOLS` allow MAVLink-commanded arm (`MAV_CMD_COMPONENT_ARM_DISARM`) with no RC input present.
- Confirm GPS present and required for RTL; app should block arming if no GPS fix.
- `FENCE_ENABLE=1` (geofence) set in `drone.param` (`FENCE_TYPE=7`, `FENCE_ALT_MAX=100`, `FENCE_RADIUS=300`, `FENCE_ACTION=1`) as an extra safety net given the single-link-of-failure design. Radius/altitude are placeholders — confirm against the real flight site. App-level surfacing of fence status/breach is Phase 4.

## Implementation phases

1. **Phase 0 — Bench link validation.** Props off. Verify FC param config above. Write a minimal `pymavlink` script on the Raspi to connect over UART2, send heartbeats, arm/disarm, send test `MANUAL_CONTROL` values, read telemetry. Physically unplug/kill the Raspi WiFi or process and confirm the FC actually triggers RTL/Land — this drill is non-negotiable before any real flight given the no-backup-RC setup.
2. **Phase 1 — Raspi backend MVP.** WiFi AP config, FastAPI/aiohttp server with a WebSocket endpoint, MAVLink bridge module sending `MANUAL_CONTROL` from a simple test input (keyboard/CLI) at a fixed rate with latest-value semantics (never queue stale stick data). Bench-test motors (props off) end to end.
3. **Phase 2 — PWA client.** Virtual on-screen joysticks (fallback for touch) + Gamepad API support for physical controllers, telemetry HUD (battery, GPS fix, armed state, link status), explicit ARM/DISARM and flight-mode controls, prominent connection-status indicator.
4. **Phase 3 — End-to-end bench validation.** Full stack, repeat the failsafe drill from Phase 0 through the real app, confirm latency feels acceptable on local AP link before first real flight.
5. **Phase 4 — Safety & reliability hardening.** Lowest-risk, highest-priority new work; land before any UI/feature phase below.
   - *systemd unit*: new `raspi/drone-control.service` (`ExecStart=uvicorn server:app --host 0.0.0.0 --port 8000`, `WorkingDirectory=.../drone-control/raspi`, `Environment=FC_PORT=... FC_BAUD=...`, `Restart=on-failure`, `RestartSec=2`, `StartLimitIntervalSec=60`, `StartLimitBurst=5`); replaces the manual-run note in README. Open concern: fast auto-restart could resume heartbeats before `FS_GCS_TIMEOUT` (5s) elapses, masking a crash that should trip failsafe — bench-check by killing only the `server.py` process (not power) and timing restart vs. `FS_GCS_TIMEOUT`; add to `docs/failsafe-drill.md`.
   - *Geofence app-level handling*: firmware side already set (see above). Add: `mavlink_bridge.py` parses fence-breach `STATUSTEXT`/`SYS_STATUS` geofence health bit into a `fence_breached` telemetry field; extend the WS JSON schema; `web/` adds a prominent breach banner (same visual language as the existing "FC LINK LOST" banner). Confirm `FENCE_RADIUS`/`FENCE_ALT_MAX` against the real site.
   - *WS reconnect/retry*: `web/app.js`'s `connect()` already retries on `onclose` with a fixed 1s timer — upgrade to exponential backoff (1s→2s→4s→8s, cap 10s), a `connecting` guard against overlapping timers, and a visible retry-state indicator in the status bar.
   - *Battery failsafe surfaced in-app*: add `BATT_MONITOR`, `BATT_LOW_VOLT`, `BATT_CRT_VOLT`, `BATT_FS_LOW_ACT`, `BATT_FS_CRT_ACT` to `drone.param` (exact voltage thresholds depend on battery chemistry/cell count — confirm with user, don't guess). Mirror the same thresholds in `mavlink_bridge.py`/`app.js` (comment cross-referencing `drone.param` as source of truth); add a distinct low/critical HUD banner beyond the current arbitrary battery-number color threshold.
   - Verification: extend `docs/bench-test-checklist.md` and `docs/failsafe-drill.md` with a checklist item per sub-item above.

6. **Phase 5 — GUIDED-mode semi-autonomous control.** Merges the old "position hold, go-to-point" stretch item with waypoint missions into one phase. Start with single-target GUIDED goto (`SET_POSITION_TARGET_GLOBAL_INT` via pymavlink), new WS message `{"type":"guided_goto","lat":..,"lon":..,"alt":..}`, gated on armed+GPS-fix+mode==GUIDED (same refusal pattern as the existing arm-request handler). Only after that's bench/flight-proven, extend to sequenced waypoints — either client-driven sequential goto-on-reach (reuses the same primitive) or a full MAVLink mission upload (`MISSION_COUNT`/`MISSION_ITEM_INT`/`MISSION_ACK`) if an autonomously-flown uploaded route is actually wanted (open question). Safety-critical: confirm losing the link mid-GUIDED-command still triggers FC-side RTL rather than the FC continuing toward a stale target — add as a new section in `docs/failsafe-drill.md`.

7. **Phase 6 — Transport upgrade: WebRTC DataChannel + FPV video.** Merges the old WebRTC-DataChannel stretch item with a new FPV video feed, since both need the same peer-connection plumbing — only build if Phase 3 latency testing actually shows a problem (per original "not built until proven necessary"). Raspi side: `aiortc` (new `raspi/requirements.txt` entry), SDP offer/answer signaling reused over the existing `/ws` connection before handing off to the DataChannel (`ordered=false, maxRetransmits=0`), plus a camera-fed `MediaStreamTrack` if video is in scope. Browser side: `RTCPeerConnection` setup in `app.js`, control calls move to `datachannel.send()` once connected (open question: keep WS as a permanent fallback path, or fully replace it). **Open questions, don't guess**: does the Pi actually have a camera module/USB webcam attached today (nothing in the repo references one)? If so, can the Pi Zero 2W do real-time H.264 encode in software, or does it need the camera's hardware/V4L2 M2M encoder path — materially changes the implementation. Verification: repeat Phase 3's latency test over the new transport; re-run the failsafe drill to confirm FC-side heartbeat/RTL (unaffected by this change, lives in the UART/MAVLink layer) still passes.

8. **Phase 7 — HUD & UI polish.**
   - *Telemetry history*: add `heading` to telemetry parsing (from `VFR_HUD.heading`, already received but currently dropped) and the WS schema; client-side ~60s ring buffer of altitude/heading/battery, rendered as canvas sparklines near the HUD, following the existing hand-rolled canvas pattern in `web/joystick.js` rather than adding a charting dependency.
   - *Prominent RTL button*: promote the existing `RTL` option in the mode-select dropdown to a dedicated large button, same pattern as the existing arm/disarm buttons.
   - *Outdoor readability mode*: a high-contrast/large-numeral toggle (`body.outdoor-mode`, localStorage-persisted) rather than literal "dark mode," since the app is already dark by default (open question: is a true light theme also wanted, despite likely being counterproductive for sunlight glare).
   - Verification: bench-only visual check in `docs/bench-test-checklist.md`; no failsafe-drill implications (pure UI).

9. **Phase 8 — Flight log recording.** In `mavlink_bridge.py`, after connecting set `self._conn.logfile_raw = open(path, 'wb')` (pymavlink's standard raw-tee) writing a timestamped `.tlog` under a new gitignored `raspi/logs/`, replayable directly in Mission Planner/QGC — deliberately not a custom log format. New `LOG_DIR` env var, documented in README. Optionally a `GET /logs/latest` route on the existing FastAPI app to pull a log without SSH. Verification: confirm a valid `.tlog` opens in a GCS log viewer; sanity-check disk growth rate against SD card headroom given ~30Hz `MANUAL_CONTROL` + 1Hz heartbeat + telemetry traffic.

10. **Phase 9 — Multi-vehicle support.** Sequenced last: highest architectural risk, deprioritize until there's an actual second airframe (open question: is this speculative, or is a second drone planned?). Replace `server.py`'s single global bridge/subscriber-set with a registry keyed by vehicle ID, each owning its own MAVLink bridge and subscriber set; per-vehicle config; WS endpoint becomes `/ws/{vehicle_id}`. **Open architectural question, needs resolving before scoping further**: is "multi-vehicle" one Pi driving multiple FCs over multiple UARTs, or one-Pi-per-drone with the PWA becoming a multi-endpoint client — very different designs. Must also close a pre-existing gap this phase would otherwise inherit: today *any* connected WS client's control messages drive the one shared bridge with no ownership/authority model, which becomes actively dangerous with multiple armed vehicles — needs explicit "which vehicle has control" UI state and a new `docs/multi-vehicle-checklist.md`.

**Ordering notes**: Phase 4 before Phase 9 (safe prerequisites before added complexity); Phase 4's geofence/battery work before Phase 5 (tighten safety nets before adding autonomy); Phase 6 is independent of Phase 5 but gated on Phase 3's latency finding, not on Phase 5; Phases 7 and 8 have no hard dependencies and can interleave anywhere after Phase 4; Phase 9 last, and possibly never, pending its open question.

## Verification

- Phase 0: bench script confirms arm/disarm, motor test (props off), and FC autonomously enters RTL/Land when Raspi-side MAVLink heartbeat stops.
- Phase 1: same drill, but through the backend service instead of the raw script.
- Phase 2/3: manual control test on bench (props off) via the actual PWA over the Raspi's own WiFi AP, checking input latency and telemetry display.
- Before first real flight: repeat the WiFi-kill failsafe drill through the full stack outdoors in a safe open area, low altitude, ready to catch/land manually.
- Phases 4-9: see per-phase verification notes above; safety-relevant items (geofence, battery failsafe, systemd restart timing, GUIDED-mode link loss) each get a bench-test-checklist and/or failsafe-drill addition before being considered done — same bar as Phase 0-3 work.
