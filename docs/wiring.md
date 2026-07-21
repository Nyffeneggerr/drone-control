# Wiring: Raspi Zero 2 W <-> Speedy Bee F405 V4 (UART3 / R3-T3)

**2026-07-21: moved from UART2 (R2/T2) to UART3 (R3/T3).** Bench testing found the FC's R2 pin
electrically damaged — idles at 2.6V instead of 3.3V (T2, R3, and T3 all read a clean 3.3V), a
multi-megohm leakage path consistent with pin damage, not a wiring/config issue (Pi TX/RX proven
good via loopback, SERIAL2 protocol/baud confirmed correct over USB, T2 downlink always worked).
R2/UART2 should be treated as unusable; do not rewire back to it without re-verifying that voltage.

## Connections

| FC (UART3) | Raspi                          | Notes |
|------------|--------------------------------|-------|
| T3 (TX)    | GPIO 15 / RXD (pin 10)         | FC transmits -> Pi receives |
| R3 (RX)    | GPIO 14 / TXD (pin 8)          | Pi transmits -> FC receives |
| GND        | GND (e.g. pin 6)               | Common ground, required |

Cross-connect TX->RX as usual. Confirm FC UART3 is 3.3V logic (it is, on F405 V4) — matches Raspi GPIO UART directly, no level shifter needed. Do not power the Pi from the FC's 5V rail unless you've checked available current budget; prefer a dedicated BEC/UBEC for the Pi if margins are tight.

## Raspi UART setup

The Pi's primary UART (`/dev/serial0`) is used by Bluetooth by default on models that have it (Zero 2 W does). To free it for the FC link:

1. `sudo raspi-config` -> Interface Options -> Serial Port -> "login shell over serial" = No, "serial port hardware enabled" = Yes.
2. Disable the Bluetooth-UART overlay so `/dev/serial0` maps to the PL011 UART, not `/dev/ttyS0` (mini-UART): add `dtoverlay=disable-bt` to `/boot/firmware/config.txt`, then `sudo systemctl disable hciuart`.
3. Reboot, confirm `/dev/serial0 -> /dev/ttyAMA0` (`ls -l /dev/serial0`).

## FC-side parameters

See `firmware-config/drone.param` — `SERIAL3_PROTOCOL=2` (MAVLink2), baud matched between `SERIAL3_BAUD` and the `--baud` passed to `bench_test.py` / `FC_BAUD` env var for `server.py`. (`SERIAL2_*` is left at its prior MAVLink2 config for reference but is not physically connected — see the R2 hardware note above.)
