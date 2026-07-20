# Failsafe Drill Procedure

This drill is the entire safety case for this project: there is no backup RC transmitter, so FC-native `FS_GCS_ENABLE` failsafe is the only thing standing between "Raspi crashes or WiFi drops" and "drone falls out of the sky uncontrolled." Run it at every phase boundary (see `docs/bench-test-checklist.md`), not just once.

## What it proves

The FC autonomously executes RTL (or Land, if no GPS fix) when it stops receiving MAVLink heartbeats from the Raspi — regardless of *why* the heartbeats stopped (WiFi dropped, Raspi kernel panicked, process crashed, battery died). The drone must never rely on the Raspi to *notice* its own failure and react; the FC watches from the outside.

## Procedure (bench, props off)

1. Power FC and Raspi, establish MAVLink link (Phase 0 script, or full backend + PWA in later phases).
2. Arm (props off, GPS fix present or `--force-arm` for command-path-only testing).
3. Start a stopwatch, then kill the heartbeat source using one of:
   - Ctrl+C the bench script / stop the `server.py` process.
   - `sudo systemctl stop hostapd` (or physically power off the Pi) to simulate a full link loss.
   - Unplug the Pi's power entirely (simulates Pi crash, not just WiFi drop — the more realistic worst case).
4. Watch the FC (via a second GCS session — separate laptop with Mission Planner/QGroundControl on a second telemetry link if available, or the FC's status LED/buzzer patterns per ArduCopter docs) for RTL or Land to engage.
5. Record the actual elapsed time from heartbeat loss to failsafe action. It should match `FS_GCS_TIMEOUT` (`firmware-config/drone.param`) within a second or two.
6. Confirm the FC **stays** in the failsafe mode and does not un-arm/re-arm oddly or accept stale MANUAL_CONTROL data if the link flickers back briefly (a real WiFi drop is rarely clean).

## Pass criteria

- Failsafe consistently triggers within expected timeout, every time, across at least 3 repeated trials.
- Behavior is identical whether the cause is WiFi-only loss or full Raspi power loss.
- No scenario found where the FC keeps executing stale MANUAL_CONTROL input after heartbeat loss.

## If it fails

Do not proceed to the next phase or to real flight. Recheck `FS_GCS_ENABLE`/`FS_GCS_TIMEOUT` params, confirm the Raspi is actually the declared GCS heartbeat source (`MAV_TYPE_GCS`), and recheck ArduCopter failsafe docs for your firmware version — behavior/param names have changed across ArduCopter releases.

## Outdoor pre-flight repeat

Before the first real flight: repeat this entire drill outdoors, on the actual airframe, low altitude (a meter or two, or props-off ground test if altitude isn't needed to trust the result), with a spotter ready to catch or manually intervene if the drone does anything unexpected.
