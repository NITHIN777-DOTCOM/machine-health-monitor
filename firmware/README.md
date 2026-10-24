# Firmware: Arduino Uno

The sketch reads the sensors, prints one CSV line per second over USB serial (format in
[`../docs/DATA_CONTRACT.md`](../docs/DATA_CONTRACT.md)), and runs the stand-alone device
tier: threshold rules → `dev_state`, the buzzer and the 16x2 LCD. It works with no
laptop connected.

| Folder / file | Contents |
|---|---|
| `machine_monitor/machine_monitor.ino` | Main sketch: sensors, 1 s scheduler, CSV output, watchdog. The folder name must match the `.ino` name. |
| `machine_monitor/config_generated.h` | **GENERATED, do not edit.** Limits, hysteresis, direction, hold time, `USE_<SENSOR>` flags, LCD names, parity vectors. |
| `machine_monitor/state_machine.h` | C++ port of `DeviceStateMachine` (`backend/app/device_rules.py`), no Arduino dependencies. |
| `machine_monitor/display.h` | LCD screens (hd44780), writes only changed text. |
| `machine_monitor/buzzer.h` | Non-blocking buzzer patterns. |
| `tests/` | Single-sensor test sketches and [`tests/RESULTS.md`](tests/RESULTS.md) (bench results). |
| `archive/` | Old sketches kept for reference. |
| `build/` | Compiler output (gitignored). |

## Pin map

| Pin      | Connected to                        | Signal                | Tier     | Status |
|----------|-------------------------------------|-----------------------|----------|--------|
| D0, D1   | **Keep free**: USB serial (RX/TX)   | –                     | –        | – |
| D2       | Vibration module SW-420 (board marked HW-072), DO | Digital, interrupt (INT0), edges counted per second | Core | Tested |
| D8       | Passive buzzer module               | `tone()` 2.5 kHz when sounding, high impedance when silent (see Buzzer) | Core (device tier) | Tested (HIL 2026-10-24) |
| D9       | HC-SR04 Trig                        | Digital out           | Optional | Tested 2026-10-23 |
| D10      | HC-SR04 Echo                        | Digital in            | Optional | Tested 2026-10-23 |
| A0       | DHT11 data                          | Used as a digital pin | Core     | Tested |
| A1       | Water leak sensor, analog out (+ → 5V) | Analog in          | Optional | Tested 2026-10-23 |
| A2       | Sound module, analog out            | Analog in             | Core     | Tested |
| A4       | I2C SDA: LCD 0x27 + INA219 0x40     | I2C                   | LCD core; INA219 optional | LCD tested; INA219 **not fitted** |
| A5       | I2C SCL: LCD 0x27 + INA219 0x40     | I2C                   | as above | as above |

Parked (not used): OLED display, MPU6050.

## Limits and sensor flags come from the registry

**Never edit limits or `USE_<SENSOR>` flags in the sketch.** They live in
`backend/config/sensors.json` (`warn`, `critical`, `hysteresis`, `direction`, `enabled`,
`tier`, `firmware_flag`, `lcd_name`) and `backend/config/settings.json` (`hold_seconds`).
After changing either file, regenerate the header (from the repo root):

```
backend\venv\Scripts\python backend\scripts\gen_firmware_config.py
```

then compile and upload. A backend test (`tests/test_firmware_config.py`) fails while
`config_generated.h` is out of date, and `--check` reports it without writing.

Generated flags (currently):

| Flag | Sensors | Now |
|---|---|---|
| `USE_DHT11` | temp_c, humidity | 1 |
| `USE_SOUND` | sound_peak | 1 |
| `USE_VIBRATION` | vib_count | 1 |
| `USE_LEAK` | leak_raw | 1 |
| `USE_HCSR04` | distance_cm | 1 |
| `USE_INA219` | current_ma, bus_v | 0 (not fitted) |

`0` = not read; its CSV columns are still printed, **empty**.

## Defines in the sketch (hardware/testing options)

| Define | Default | Meaning |
|---|---|---|
| `BUZZER_ENABLED` | `1` | `0` = silent for testing (patterns and LCD still run). |
| `BUZZER_PASSIVE` | `1` | `1` = passive buzzer, driven with `tone()` (the fitted module). `0` = active (self-oscillating) buzzer, driven with a steady HIGH. |
| `BUZZER_FREQ_HZ` | `2500` | Tone pitch for a passive buzzer (clearly audible at 2–2.7 kHz). |
| `LEAK_POWER_PIN` | not defined | Power the leak sensor from this pin only while reading (see below). |
| `PARITY_TEST` | `0` | `1` = print the state machine parity vectors at boot (set by `firmware_parity.py`). |

All of them can also be set at compile time, e.g.
`arduino-cli compile ... --build-property "build.extra_flags=-DBUZZER_ENABLED=0"`.

## What the sketch does

- **Output:** at boot `# fw machine_monitor v1.0.2`, a few `#` info lines (`lcd=ok`,
  `sound_baseline=…`, `dht11=ok`, `free_ram=…`), then the contract header line, then one
  CSV line per second in contract order. Every 60 s: `# free_ram=<bytes> loop_max_ms=<n>`
  (longest loop() pass in the last minute).
- **Scheduling:** `millis()` only, no `delay()` in `loop()`. Inside each second the slow reads
  are spread so none lands on the output tick: leak at 300/320 ms, HC-SR04 at 500 ms, DHT11
  at 700 ms (every second tick). Libraries still block briefly: the DHT11 read ~25 ms
  (20 ms start signal), `pulseIn()` up to 25 ms; that is the `loop_max_ms` you see (23–25).
- **DHT11 (A0):** read every 2 s, the last value is reused in between; 3 failed reads in a
  row → `temp_c`/`humidity` empty (sensor fault → WARNING).
- **Sound (A2):** sampled on every loop pass (except while the buzzer sounds, see Buzzer:
  sensor blanking); the line reports the peak deviation from a
  running baseline during the last second. The baseline is an EMA (α = 1/1024 per sample)
  updated only on quiet samples (|deviation| < 20), seeded by a 1 s quiet calibration at
  boot (**keep the room quiet for the first second**). If no sample is quiet for 10 s the
  baseline is re-seeded, so it can never get stuck.
- **Vibration (D2):** interrupt on every edge (CHANGE), count copied and cleared atomically
  once per second. Bench calibration (Phase 7.2, limits warn 50 / crit 100): light taps
  2–49, firm knocks 51–87, very hard knocks 109–286 edges/s. **Demo: tap the sensor itself**,
  not the table: a knock on the table is also loud (sound 46–136) and shakes the whole
  breadboard.
- **Leak (A1):** `analogRead`, dry ≈ 4–9, wet 240–576. **Optional `LEAK_POWER_PIN`:** a leak
  sensor powered all the time slowly corrodes its traces (electrolysis). To power it only
  while reading: move the sensor's **+** wire from 5V to a free digital pin (e.g. D7) and
  uncomment `#define LEAK_POWER_PIN 7`. The sketch then switches it on 20 ms before the
  reading and off right after (≈ 2 % duty).
- **HC-SR04 (D9/D10) = safety zone:** `pulseIn()` with a 25 ms timeout. Distance is how close
  a person or object is to the running machine: **≤ 20 cm WARNING, ≤ 10 cm CRITICAL**
  (direction "below"). **No echo = nothing in range = `400`** (the sensor's maximum), which
  is clear. An empty field means the module did not answer (echo line never went high).
- **INA219:** behind `USE_INA219` (currently 0); columns stay empty. The `USE_INA219 1` build
  compiles (67 % flash) but is untested on hardware.

## State machine and parity test

`state_machine.h` is a line-by-line port of `DeviceStateMachine`: immediate escalation,
de-escalation only when every value is clear of the limit by its hysteresis (in the limit's
direction) for `HOLD_SECONDS` consecutive rows, one level at a time, an enabled core
sensor empty → at least WARNING. It runs once per data line.

**Parity test** (board on USB, COM port free):

```
cd backend
venv\Scripts\python scripts\firmware_parity.py --port COM5
```

It compiles with `-DPARITY_TEST=1`, uploads, reads the board's answers for both worked
examples in DATA_CONTRACT.md (temp_c "above", distance_cm "below") and a 32-row
multi-sensor sequence with the real limits, compares state, hold countdown and first reason
row by row with `device_rules.py`, then re-uploads the normal build. **Result 2026-10-24:
71/71 rows match** (v1.0.0, and again for v1.0.1 and v1.0.2 after the buzzer changes). Floats are 32-bit on the Uno (64-bit in Python); a value within ~1e-6
of a limit could in theory compare differently, no real reading is that precise.

## LCD screens (16x2, I2C 0x27)

| Situation | Line 1 | Line 2 |
|---|---|---|
| Boot | `Machine Monitor` | `Calibrating...` |
| NORMAL | `NORMAL  T30.3C` | every 3 s: `S4 V2 L6` (sound, vibration, leak) ↔ `Dist 158cm` / `Dist clear` (400) |
| WARNING / CRITICAL | `CRIT VIB 206>100`, `CRIT DIST 8<10`, `WARN TMP 32.3>32` | every 2 s: the second reason (e.g. `WARN LEAK 60>50`) and, while counting down, `Recover in 4s`; with neither, the limits (`warn>50 crit>100`) |
| Core sensor fault | `SENSOR FAULT` | `DHT11` (and the countdown while recovering) |
| Parity build | `PARITY TEST` | `see serial` |

`>` / `<` = past the limit (direction above / below); `~` = back inside the hysteresis band
but not yet clear. Disabled sensors are left out. The LCD is only written when the text
changes (no flicker). If no LCD answers at 0x27 the sketch prints `# lcd=not found` and runs on.

## Buzzer (D8)

| State | Pattern |
|---|---|
| Boot | one 200 ms beep |
| Entering WARNING | one short chirp (80 ms) |
| CRITICAL | 200 ms on / 200 ms off, 3 beeps, then a 1 s pause, repeating |
| NORMAL | silent |

**The fitted buzzer is passive** (bench test 2026-10-24): it sounds only with a tone
(`tone(8, 2000)` in the Arduino IDE), not on a steady HIGH, LOW or floating pin. So the sketch
drives it with `tone()` at `BUZZER_FREQ_HZ` (2.5 kHz) and stops it with `noTone()`. For an
active buzzer set `BUZZER_PASSIVE 0` (steady HIGH while sounding). Everything stays
non-blocking (`millis()`).

**While silent the pin is high impedance (INPUT), not driven LOW** (`noTone()` leaves it
OUTPUT LOW, so the sketch switches it back to INPUT). On the bench, holding D8 LOW made the
buzzer module draw a steady current that lifted every analog reading by about 20 counts (dry
leak 6 → 26, sound baseline 15 → 35). With the tone build, silent readings are unchanged
(sound 3–5, dry leak 3–8).

**Timer2:** `tone()` uses Timer2. Nothing else in the sketch does: `millis()`/`micros()` run on
Timer0, D2 is the INT0 interrupt, the watchdog and I2C (TWI) are separate hardware, and the
DHT and LCD libraries use no timer. `pulseIn()` measures by counting a loop, so the tone's
interrupt makes a distance read **during a beep** a few % short (< 0.3 cm at the 10 cm limit).

**Sensor blanking to avoid self-interference.** The microphone hears the buzzer: during a
beep `sound_peak` read 30–39 on the bench, inside the sound hysteresis band (30–40). After a
CRITICAL vibration alarm the device then named sound as the WARNING reason and recovered
1–2 s later. So `soundSample()` ignores the microphone while the buzzer sounds and for 50 ms
after (`Buzzer::blanking()`, `BLANK_MS`). With blanking, sound read 3 on every beeping row.
Trade-off: a real noise that happens only inside a 200 ms beep (CRITICAL) or the 80 ms chirp
is not measured; a machine noise normally lasts longer than one beep.

## Watchdog

The AVR watchdog is enabled at the end of `setup()` with a 2 s timeout and reset on every
`loop()` pass. If anything hangs (an I2C bus lock-up, a stuck library call) the board resets
itself within 2 s and starts again (boot lines, header, data). The longest normal loop pass
is ~25 ms, far below the limit. The I2C bus also has a 3 ms timeout (`Wire.setWireTimeout`).

## Memory (arduino-cli 1.5.1, arduino:avr 1.8.8)

| Build | Flash | RAM (globals) |
|---|---|---|
| Normal (v1.0.2) | 19 822 B (61 %) | 877 B (42 %), ~1010 B free at runtime |
| `PARITY_TEST=1` (v1.0.2) | 21 662 B (67 %) | 953 B (46 %) |
| `USE_INA219 1` (v1.0.0) | 21 686 B (67 %) | 875 B (42 %) |

No `String`, all literal text in flash (`F()`, `PSTR`, `PROGMEM`), parity vectors in `PROGMEM`.

## Libraries (pinned)

| Library | Version | Used for |
|---|---|---|
| DHT sensor library (Adafruit) | 1.4.7 | DHT11 |
| Adafruit Unified Sensor | 1.1.15 | dependency of the DHT library |
| hd44780 (Bill Perry) | 1.3.2 | 16x2 I2C LCD (`hd44780_I2Cexp`) |
| Adafruit INA219 | 1.2.3 | INA219 (only with `USE_INA219 1`) |
| Adafruit BusIO | 1.17.4 | dependency of the INA219 library |
| Wire | built in | I2C |

The HC-SR04 needs no library (`pulseIn()`), the vibration counter uses `attachInterrupt()`.

## Upload with arduino-cli (preferred)

One-time setup:

```
arduino-cli core update-index
arduino-cli core install arduino:avr@1.8.8
arduino-cli lib install "DHT sensor library@1.4.7" "Adafruit Unified Sensor@1.1.15" "hd44780@1.3.2" "Adafruit INA219@1.2.3" "Adafruit BusIO@1.17.4"
```

Every upload (from the repo root; replace `COM5` with your port; stop the backend first):

```
arduino-cli board list
arduino-cli compile --fqbn arduino:avr:uno --build-path firmware/build/normal firmware/machine_monitor
arduino-cli upload  --fqbn arduino:avr:uno -p COM5 --input-dir firmware/build/normal firmware/machine_monitor
arduino-cli monitor -p COM5 -c baudrate=115200
```

`arduino-cli board list` shows the COM port. A genuine Uno is listed as
`Arduino Uno  arduino:avr:uno`. A CH340 clone shows up as `Unknown` with no FQBN; that's
fine, just pass `--fqbn arduino:avr:uno` yourself. If no port appears at all with a clone,
install the CH340 driver.

## Upload with the Arduino IDE (backup)

1. Open `firmware/machine_monitor/machine_monitor.ino` (the `.h` files open as tabs).
2. **Tools → Board → Arduino AVR Boards → Arduino Uno**.
3. **Tools → Port →** your COM port.
4. Install the libraries above (same versions) in **Library Manager**.
5. Click **Upload**. To check the output, open **Serial Monitor** at **115200** baud.

## Lessons learned

- **I2C works only on A4 (SDA) and A5 (SCL)** on the Uno. The LCD and the INA219 share
  those two pins, with different addresses (0x27 and 0x40).
- **Keep D0 and D1 free.** They are the USB serial lines; anything wired there breaks
  uploads and the data stream.
- **Female jumper ends don't fit breadboard holes.** Use male–male jumpers on the
  breadboard and male–female ones to go from the breadboard to module headers.
- **Only one program can open the COM port at a time.** Close the Arduino IDE Serial
  Monitor (or `arduino-cli monitor`) before starting the backend, or the backend can't
  connect. Uploading also needs the port free, so stop the backend before uploading.
- **A module drawing current shifts every analog reading** on this breadboard (shared ground
  wiring): see the buzzer note. Compare a sensor's value in the full sketch with its
  single-sensor test sketch when something looks off.
- **A loose 5V/GND jumper looks like a software bug.** In the HIL test a few loose wires made
  the Uno drop off USB, scrambled the LCD (boxes, `?`), sent random sound spikes and read the
  leak sensor as 0. Push every rail jumper in and tape the HC-SR04 wires before a demo.
- **The HC-SR04 sees your arm.** Reach for the other sensors from the side or from behind it,
  or the safety zone trips (correctly).
- **Opening the port resets the Uno.** Output from before the reset can still be buffered;
  the backend flushes it 1 s after opening and drops a row cut off by the reset.
