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
- Consider `FENCE_ENABLE` (geofence) as an extra safety net given the single-link-of-failure design.

## Implementation phases

1. **Phase 0 — Bench link validation.** Props off. Verify FC param config above. Write a minimal `pymavlink` script on the Raspi to connect over UART2, send heartbeats, arm/disarm, send test `MANUAL_CONTROL` values, read telemetry. Physically unplug/kill the Raspi WiFi or process and confirm the FC actually triggers RTL/Land — this drill is non-negotiable before any real flight given the no-backup-RC setup.
2. **Phase 1 — Raspi backend MVP.** WiFi AP config, FastAPI/aiohttp server with a WebSocket endpoint, MAVLink bridge module sending `MANUAL_CONTROL` from a simple test input (keyboard/CLI) at a fixed rate with latest-value semantics (never queue stale stick data). Bench-test motors (props off) end to end.
3. **Phase 2 — PWA client.** Virtual on-screen joysticks (fallback for touch) + Gamepad API support for physical controllers, telemetry HUD (battery, GPS fix, armed state, link status), explicit ARM/DISARM and flight-mode controls, prominent connection-status indicator.
4. **Phase 3 — End-to-end bench validation.** Full stack, repeat the failsafe drill from Phase 0 through the real app, confirm latency feels acceptable on local AP link before first real flight.
5. **Phase 4 — Stretch.** GUIDED-mode semi-autonomous commands (position hold, go-to-point). If TCP/WebSocket latency proves insufficient once flying, upgrade the control channel to a WebRTC DataChannel in unreliable/unordered mode (true UDP-like semantics) — noted as the likely fix if the old prototype's latency issue turns out to be TCP head-of-line blocking, but not built until proven necessary.

## Verification

- Phase 0: bench script confirms arm/disarm, motor test (props off), and FC autonomously enters RTL/Land when Raspi-side MAVLink heartbeat stops.
- Phase 1: same drill, but through the backend service instead of the raw script.
- Phase 2/3: manual control test on bench (props off) via the actual PWA over the Raspi's own WiFi AP, checking input latency and telemetry display.
- Before first real flight: repeat the WiFi-kill failsafe drill through the full stack outdoors in a safe open area, low altitude, ready to catch/land manually.
