# Sensor bench tests

Single-sensor checks of the optional and device-tier modules before they were enabled in
the main sketch (Phase 7.1). The sketches are in this folder; each prints one reading per
second at 115200 baud.

## 2026-10-23: manual tests (Arduino IDE Serial Monitor)

**Conditions:** Arduino Uno (genuine, COM5) on USB from the laptop, all modules wired on the
breadboard as in the [pin map](../README.md#pin-map), Arduino IDE Serial Monitor at 115200
baud, 1 reading per second, indoors on a desk. *(Room temperature / humidity were not
recorded; the next morning the DHT11 read 29–30 °C and 80–84 %RH in the same place.)*

| Test | Sketch | Wiring | Procedure | Result |
|---|---|---|---|---|
| Ultrasonic HC-SR04 | `test_ultrasonic/` | Trig D9, Echo D10, 5V, GND | Hand moved towards the sensor and back; then nothing in front | **Working.** Hand 7.4 → 73.1 cm and back, tracking smoothly. Open space 149–309 cm (walls/ceiling). No timeouts seen. |
| Water leak | `test_leak/` | S → A1, + → 5V, − → GND | Dry; wet finger / water on the traces; wiped dry | **Working.** Dry 4–9. Wet 240–576. Back to 6–9 within ~2 s after wiping. |
| Sound + LCD (clap) | `test_sound_lcd/` | Sound AO → A2; LCD SDA A4, SCL A5, 0x27 | Claps near the microphone | **Working.** Clap detection shown on the LCD. |
| I2C scan | `i2c_scanner/` | LCD backpack on A4/A5 | Scan the bus | LCD found at 0x27 (INA219 not fitted). |

## 2026-10-24: checks with the final sketch (`machine_monitor`, v1.0.0)

Same bench, read with `arduino-cli`/pyserial at 115200 baud.

| Check | Result |
|---|---|
| `test_leak` re-run, dry | 6–7 |
| `machine_monitor`, leak dry (62 s live run) | 3–8 (mean 5.9). Before the buzzer-pin fix it read 24–28: holding D8 LOW lifted every analog reading by ~20 counts (see firmware README, Buzzer). |
| `test_ultrasonic` vs `machine_monitor`, same object | 24.7–24.8 cm vs 23.8–25.9 cm (`machine_monitor` uses the same `pulseIn()` measurement) |
| Sound, quiet room (`machine_monitor`) | baseline 15, peak deviation 1–4 |
| Buzzer, microphone check (`test_buzzer` levels) | D8 HIGH and high impedance: no current, A2 flat. D8 LOW: steady current (A2 and A1 +20 counts) but no tone the microphone picks up. **Which level sounds is still to be confirmed by ear** with `test_buzzer/`. |
| Parity test (`backend/scripts/firmware_parity.py`) | 71/71 rows match `device_rules.py` (both worked examples + 32-row multi-sensor sequence) |
| Watchdog / timing | `loop_max_ms` 23–25 (DHT11 read), `free_ram` 1032 B, 128 lines in 128 s |

## Still to test

- Buzzer polarity by ear (`test_buzzer/`), then the CRITICAL pattern and WARNING chirp.
- Leak with `LEAK_POWER_PIN` (needs the + wire moved to D7).
- INA219 (not fitted).
