# Data Contract: Arduino → Backend serial format

This document is the single source of truth for what the Arduino sends over USB serial
and what the backend stores. Firmware, backend, ML and dashboard must all follow it.
If something here changes, change it here first.

## 1. Link settings

| Setting      | Value                                         |
|--------------|-----------------------------------------------|
| Transport    | USB serial (UART over the Uno's USB port)     |
| Baud rate    | **115200**, 8N1                               |
| Rate         | **one data line per second**                  |
| Line ending  | newline (`\n`); a trailing `\r` must be tolerated |
| Encoding     | ASCII                                         |
| Separator    | comma, no spaces, no quoting                  |

## 2. Line types

There are only two kinds of line:

1. **Comment / log lines** start with `#`. The backend **ignores** them for data (it may
   show them in a debug log). The firmware uses them for boot messages, sensor init
   results, errors, etc.
2. **Data lines**: everything else. Exactly 10 comma-separated fields (so exactly 9 commas).
   A data line with the wrong field count is dropped and logged by the backend.

### Header line

On boot (after `setup()` finishes) the Arduino prints exactly one header line. It is a
comment line whose content is the column list:

```
# ms,temp_c,humidity,sound_peak,vib_count,leak_raw,distance_cm,current_ma,bus_v,dev_state
```

The backend recognises it because the first name after `#` is `ms`. The backend can use it
to check that the firmware and backend agree on columns. Note that opening the COM port
resets the Uno, so the backend will normally see the header right after it connects.

## 3. Columns

The column order is **fixed**. Every column is always present, even when the sensor
behind it is disabled or not fitted; the field is then empty.

| # | Column        | Type    | Unit     | Sensor / source            | Meaning |
|---|---------------|---------|----------|----------------------------|---------|
| 1 | `ms`          | integer | ms       | `millis()`                 | Time since boot. Wraps after ~49.7 days. Never empty. |
| 2 | `temp_c`      | 1 dp    | °C       | DHT11 (A0)                 | Air temperature. |
| 3 | `humidity`    | 1 dp    | %RH      | DHT11 (A0)                 | Relative humidity. |
| 4 | `sound_peak`  | integer | counts   | Sound module (A2)          | Peak deviation from a running baseline during the last second. Quiet room ≈ 3–5; claps 60–590. |
| 5 | `vib_count`   | integer | edges/s  | SW-420 / HW-072 (D2, interrupt) | Interrupt edges counted in the last second. Still = 0; taps 5–40; knocks 100+. |
| 6 | `leak_raw`    | integer | 0–1023   | Water leak sensor (A1)     | Raw ADC value; higher = wetter. *Optional.* |
| 7 | `distance_cm` | 1 dp    | cm       | HC-SR04 (D9 Trig / D10 Echo) | Echo distance. Out of range / no echo = empty. *Optional.* |
| 8 | `current_ma`  | 1 dp    | mA       | INA219 (I2C 0x40)          | Load current. *Optional.* |
| 9 | `bus_v`       | 2 dp    | V        | INA219 (I2C 0x40)          | Bus voltage. *Optional.* |
| 10 | `dev_state`  | enum    | –        | computed on the Arduino    | `NORMAL`, `WARNING` or `CRITICAL`. Never empty. |

"dp" = decimal places. Decimal separator is always `.`.

### The empty-field rule

> A sensor that is **missing, disabled or failed** sends an **empty field**: never `0`,
> `-1`, `NaN` or any other placeholder.

`0` is a real reading (for example, no vibration), so it must never mean "no data". The
backend turns empty fields into "no value" (`None`/`null`), never into 0.

The backend tells the two cases apart using the sensor registry (section 6):

- sensor `enabled: false` and field empty → shown as **"not connected"**
- sensor `enabled: true` and field empty → shown as **"no reading / sensor fault"**

### `dev_state` (device-side rules)

The Arduino computes `dev_state` itself so that the buzzer and LCD work with no laptop.
It is the worst of:

1. the threshold state of every enabled sensor that has a value this second (table
   below), and
2. **the sensor-fault rule:** if any **core** sensor that is enabled sends an empty field
   (read failed, timeout, checksum error), `dev_state` is **at least `WARNING`, never
   `NORMAL`**. The LCD shows the reason, e.g. `SENSOR FAULT: DHT`. If another sensor is
   over its critical limit at the same time, the state is `CRITICAL`.

Each limit has a direction (`direction` in the registry, section 7): `above` means a
value at or above the limit is bad; `below` means a value at or below the limit is bad.
All limits below are `above`.

| Sensor       | WARNING at | CRITICAL at |
|--------------|-----------|-------------|
| `temp_c`     | ≥ 35 °C   | ≥ 40 °C     |
| `humidity`   | TBD       | TBD         |
| `sound_peak` | TBD       | TBD         |
| `vib_count`  | TBD       | TBD         |
| `leak_raw`   | TBD       | TBD         |
| `distance_cm`| TBD       | TBD         |
| `current_ma` | TBD       | TBD         |
| `bus_v`      | TBD       | TBD         |

TBD limits will be set after recording real data. The same numbers live in
`backend/config/sensors.json` (`warn` / `critical`) and must be kept in sync with the
firmware by hand.

## 4. Example lines

Header plus three data lines:

```
# ms,temp_c,humidity,sound_peak,vib_count,leak_raw,distance_cm,current_ma,bus_v,dev_state
12000,29.0,62.0,4,0,18,41.3,182.4,4.98,NORMAL
13000,36.0,61.0,212,47,,,,,WARNING
14000,,,5,0,,,,,WARNING
```

1. **All sensors present** (`12000`): every field filled, everything inside limits.
2. **Core sensors only** (`13000`): leak, ultrasonic and INA219 are not fitted, so their
   four fields are empty. Temperature 36 °C is above the 35 °C warning limit → `WARNING`.
3. **Failed core sensor** (`14000`): the DHT11 read failed (timeout/checksum), so
   `temp_c` and `humidity` are empty, not 0. Sound and vibration are normal, but because
   an enabled core sensor failed, the sensor-fault rule raises `dev_state` to `WARNING`
   and the LCD shows `SENSOR FAULT: DHT`. The backend also flags it as a sensor fault,
   because the DHT11 is enabled in the registry.

## 5. What the backend stores

When the backend saves a row (to `data/recordings/*.csv`), it keeps all 10 device columns
unchanged and adds these columns:

| Column   | Values                              | Meaning |
|----------|-------------------------------------|---------|
| `ts_iso` | ISO 8601 with timezone, e.g. `2026-10-23T18:40:05+05:30` | Laptop wall-clock time when the line was received. |
| `mode`   | `live` / `recorded` / `simulated`   | `live` = from the Arduino right now; `recorded` = replayed from a file; `simulated` = generated by the backend's simulator. |
| `source` | `real` / `synthetic`                | Whether the numbers came from real sensors or were generated. A replayed real recording stays `real`. |
| `label`  | `normal` / `fault` / `unknown`      | Ground truth for ML training. Default `unknown`; set when recording a known condition. |

Stored column order:

```
ts_iso,ms,temp_c,humidity,sound_peak,vib_count,leak_raw,distance_cm,current_ma,bus_v,dev_state,mode,source,label
```

Empty device fields stay empty in the stored file.

## 6. ML scope

> **Rule:** a sensor is **used by ML** only if `enabled` **and** `include_in_ml` are both
> `true`. A sensor is **shown on the dashboard** if `enabled` is `true`. (A sensor with
> `enabled: false` is still listed on the dashboard, but as "not connected" with no value.)

- A disabled optional sensor is simply left out of the ML features.
- **Current (`current_ma`) and bus voltage (`bus_v`) are shown on the dashboard but are
  excluded from ML.** Without a real motor load the INA219 only measures a constant
  bench current, which carries no information about machine health. If a real motor
  load is added later, set `include_in_ml: true` for both and retrain.
- `ms` and `dev_state` are never ML features. `dev_state` is the device's rule-based
  verdict and can be compared against the ML result.

## 7. Sensor registry: `backend/config/sensors.json`

The registry describes every sensor. **The backend, ML pipeline and dashboard must read
the sensor list from this file and never hard-code it.**

Top-level fields:

| Field            | Meaning |
|------------------|---------|
| `schema_version` | Registry format version (currently 2: version 2 added `direction`, `group` and `comment`). |
| `csv_columns`    | The exact column order of a data line (same as section 3). |
| `sensors`        | One entry per sensor column (everything except `ms` and `dev_state`). |

Fields of each sensor entry:

| Field           | Type            | Meaning |
|-----------------|-----------------|---------|
| `key`           | string          | Must equal the CSV column name. |
| `display_name`  | string          | Label shown on the dashboard. |
| `unit`          | string          | Unit shown on the dashboard. |
| `hardware`      | string          | Physical module (for docs and the dashboard tooltip). |
| `pin`           | string          | Arduino pin(s), for reference. |
| `warn`          | number or null  | Warning limit; `null` = TBD / no limit. |
| `critical`      | number or null  | Critical limit; `null` = TBD / no limit. |
| `direction`     | `above` / `below` | `above`: a value **at or above** the limit is bad. `below`: a value **at or below** the limit is bad. |
| `tier`          | `core` / `optional` | Core sensors must work in the final build; optional ones may be left out. |
| `enabled`       | boolean         | Whether this sensor is fitted in the current build. `false` → dashboard shows "not connected". |
| `include_in_ml` | boolean         | Whether this sensor is used as an ML feature (only when also enabled; see section 6). |
| `group`         | string, optional | Sensors that come from one physical module. All entries in a group must be enabled or disabled **together**. Currently only `ina219` (`current_ma` + `bus_v`). |
| `comment`       | string, optional | Free-text note for humans; ignored by the software. |

Current state: the four core values are enabled; leak, ultrasonic and INA219 are
`enabled: false`; `current_ma` and `bus_v` are `include_in_ml: false`. Every entry uses
`direction: "above"`; for `distance_cm` the direction is still TBD (see its `comment`),
because "object too close" would need `below`.

**Groups:** enabling or disabling a group means toggling `enabled` on **every** entry with
that `group` value. For the INA219 that's both `current_ma` and `bus_v`; the firmware
flag `USE_INA219` switches both columns at once. The backend should treat a group whose
members disagree as a configuration error.

### How to add or remove an optional sensor (no code changes)

1. **Firmware:** in `firmware/machine_monitor/machine_monitor.ino`, set the sensor's
   `#define USE_<SENSOR>` flag to `1` (fitted) or `0` (removed), then compile and upload.
   When it is `0` the firmware still prints the column, just empty.
2. **Registry:** in `backend/config/sensors.json`, set `"enabled"` to `true` or `false`
   for that sensor's entry. If the entry has a `group` (e.g. `ina219`), change every
   entry in that group (`current_ma` **and** `bus_v`).
   Set `include_in_ml` if it should or shouldn't be an ML feature.
3. **Restart and retrain:** restart the backend (`start.bat`) so it rereads the registry,
   and retrain the ML model if the set of ML features changed. The dashboard picks up
   the change on its own.

Adding a **brand-new kind** of sensor (a column that does not exist yet) is a contract
change: add the column to section 3 and to `csv_columns`, add a registry entry, and
update the firmware to print it. New columns go at the end of the line so old
recordings stay readable.
