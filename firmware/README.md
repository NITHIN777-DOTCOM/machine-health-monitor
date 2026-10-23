# Firmware: Arduino Uno

The sketch reads the sensors, prints one CSV line per second over USB serial (format in
[`../docs/DATA_CONTRACT.md`](../docs/DATA_CONTRACT.md)), and runs the stand-alone device
tier: threshold rules → `dev_state`, the buzzer and the 16x2 LCD. It works with no
laptop connected.

| Folder             | Contents |
|--------------------|----------|
| `machine_monitor/` | The main sketch (`machine_monitor.ino`). The folder name must match the `.ino` name. |
| `tests/`           | Small single-sensor test sketches used to check wiring. |
| `archive/`         | Old sketches kept for reference. |

## Pin map

| Pin      | Connected to                        | Signal                | Tier     | Status |
|----------|-------------------------------------|-----------------------|----------|--------|
| D0, D1   | **Keep free**: USB serial (RX/TX)   | –                     | –        | – |
| D2       | Vibration module SW-420 (board marked HW-072), DO | Digital, interrupt (INT0), edges counted per second | Core | Tested (sensitivity screw tuned) |
| D8       | Buzzer module                       | Digital out, active HIGH | Core (device tier) | Tested |
| D9       | HC-SR04 Trig                        | Digital out           | Optional | **Not yet tested** |
| D10      | HC-SR04 Echo                        | Digital in            | Optional | **Not yet tested** |
| A0       | DHT11 data                          | Used as a digital pin | Core     | Tested |
| A1       | Water leak sensor, analog out       | Analog in             | Optional | **Not yet tested** |
| A2       | Sound module, analog out            | Analog in             | Core     | Tested |
| A4       | I2C SDA: LCD 0x27 + INA219 0x40     | I2C                   | LCD core; INA219 optional | LCD tested; INA219 **not yet tested** |
| A5       | I2C SCL: LCD 0x27 + INA219 0x40     | I2C                   | as above | as above |

Parked (not used): OLED display, MPU6050.

## Optional sensors: `USE_<SENSOR>` flags

The final sketch will have one flag per optional sensor at the top of the file:

```cpp
#define USE_LEAK     0   // water leak sensor on A1
#define USE_HCSR04   0   // ultrasonic on D9/D10
#define USE_INA219   0   // current sensor on I2C 0x40
```

`1` = fitted, `0` = not fitted. When a flag is `0` the sensor isn't read, but its CSV
column is still printed, **empty**. Keep these flags in sync with `enabled` in
`backend/config/sensors.json` (see "How to add or remove an optional sensor" in the data
contract).

## Libraries

Install with arduino-cli (or Library Manager in the IDE):

| Library | Used for | Install name |
|---------|----------|--------------|
| DHT sensor library (Adafruit) | DHT11 | `DHT sensor library` |
| Adafruit Unified Sensor | dependency of the DHT library | `Adafruit Unified Sensor` |
| hd44780 (Bill Perry) | 16x2 I2C LCD (`hd44780_I2Cexp`) | `hd44780` |
| Adafruit INA219 | INA219 current sensor (optional) | `Adafruit INA219` |
| Wire | I2C | built in |

The HC-SR04 needs no library (`pulseIn()`), and the vibration counter uses
`attachInterrupt()`.

## Upload with arduino-cli (preferred)

One-time setup:

```
arduino-cli core update-index
arduino-cli core install arduino:avr
arduino-cli lib install "DHT sensor library" "Adafruit Unified Sensor" "hd44780" "Adafruit INA219"
```

Every upload (run from the repo root; replace `COM5` with your port):

```
arduino-cli board list
arduino-cli compile --fqbn arduino:avr:uno firmware/machine_monitor
arduino-cli upload  --fqbn arduino:avr:uno -p COM5 firmware/machine_monitor
arduino-cli monitor -p COM5 -c baudrate=115200
```

`arduino-cli board list` shows the COM port. A genuine Uno is listed as
`Arduino Uno  arduino:avr:uno`. A CH340 clone shows up as `Unknown` with no FQBN; that's
fine, just pass `--fqbn arduino:avr:uno` yourself. If no port appears at all with a clone,
install the CH340 driver.

## Upload with the Arduino IDE (backup)

1. Open `firmware/machine_monitor/machine_monitor.ino`.
2. **Tools → Board → Arduino AVR Boards → Arduino Uno**.
3. **Tools → Port →** your COM port.
4. Install the libraries above in **Library Manager**.
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
