// Predictive Machine Health Monitor - device tier (Arduino Uno).
//
// Reads the sensors, prints one CSV line per second over USB serial (115200 baud, format in
// docs/DATA_CONTRACT.md), and runs the stand-alone device rules: dev_state, buzzer, 16x2 LCD.
// Works with no laptop connected.
//
// Limits, hysteresis, hold time and which sensors are fitted come from config_generated.h,
// generated from backend/config/sensors.json + settings.json (gen_firmware_config.py).
// Never edit limits here.
//
// Uno constraints: 2 KB RAM, so no String class, F()/PROGMEM for literal text, and no
// delay() in loop(): everything is scheduled with millis().

#include <avr/wdt.h>

#ifndef PARITY_TEST
#define PARITY_TEST 0          // 1 = run the state machine parity vectors at boot (firmware_parity.py)
#endif

#include "config_generated.h"
#include "state_machine.h"
#include "buzzer.h"
#include "display.h"

#if USE_DHT11
#include <DHT.h>
#endif
#if USE_INA219
#include <Adafruit_INA219.h>
#endif

// ---- user settings ----------------------------------------------------------------------
#define FW_VERSION "1.0.2"
#ifndef BUZZER_ENABLED
#define BUZZER_ENABLED 1       // 0 = silent (testing); patterns and LCD still run
#endif
#ifndef BUZZER_PASSIVE
#define BUZZER_PASSIVE 1       // 1 = passive buzzer, driven with tone() (the fitted module); 0 = active, steady HIGH
#endif
#ifndef BUZZER_FREQ_HZ
#define BUZZER_FREQ_HZ 2500    // tone pitch for a passive buzzer (clearly audible at 2-2.7 kHz)
#endif
// Optional: power the leak sensor from this pin only while reading (less corrosion by
// electrolysis). Not used now: the sensor's + is wired to 5V. To use it, move the sensor's
// + wire to the pin (e.g. D7) and uncomment:
// #define LEAK_POWER_PIN 7

// ---- pins (firmware/README.md) -----------------------------------------------------------
#define PIN_VIB     2          // SW-420 DO, INT0
#define PIN_BUZZER  8
#define PIN_TRIG    9          // HC-SR04
#define PIN_ECHO    10
#define PIN_DHT     A0
#define PIN_LEAK    A1
#define PIN_SOUND   A2

// ---- timing ------------------------------------------------------------------------------
#define TICK_MS            1000UL   // one CSV line per second
#define DHT_EVERY_TICKS    2        // DHT11: at most one read per 2 s
#define DHT_MAX_FAILS      3        // consecutive failed reads before the fields go empty
#define PHASE_LEAK_ON_MS   300      // offsets inside each second, so blocking reads never
#define PHASE_LEAK_READ_MS 320      // land on the output tick (20 ms for a powered leak sensor)
#define PHASE_DIST_MS      500
#define PHASE_DHT_MS       700
#define ECHO_TIMEOUT_US    25000UL  // HC-SR04: > 400 cm round trip (23.3 ms)
#define STATS_EVERY_MS     60000UL  // "# free_ram=... loop_max_ms=..." comment line

// ---- sound: peak deviation from a running baseline ----------------------------------------
#define SOUND_QUIET        20       // |sample - baseline| below this counts as quiet
#define SOUND_EMA_SHIFT    10       // baseline EMA: alpha = 1/1024 per sample (only when quiet)
#define SOUND_RESEED_TICKS 10       // seconds with no quiet sample -> re-seed the baseline

// CSV decimals per column (DATA_CONTRACT.md section 3), in IDX_* order.
static const uint8_t CSV_DECIMALS[SENSOR_COUNT] = {1, 1, 0, 0, 0, 1, 1, 2};

static StateMachine sm;
static Buzzer buzzer;
static Display display;
#if USE_DHT11
static DHT dht(PIN_DHT, DHT11);
#endif
#if USE_INA219
static Adafruit_INA219 ina219;
static bool inaOk = false;
#endif

static float values[SENSOR_COUNT];      // the current row; NAN = empty field

// Sound
static int32_t soundBase = 0;            // baseline x 1024
static uint16_t soundPeak = 0;           // max deviation in the current second
static uint32_t soundSum = 0;            // for re-seeding
static uint16_t soundCount = 0;
static bool soundQuietSeen = false;
static uint8_t soundLoudTicks = 0;

// Vibration (ISR)
static volatile uint16_t vibEdges = 0;

// DHT11
static float dhtTemp = NAN, dhtHum = NAN;
static uint8_t dhtFails = 0;

// Scheduler
static uint32_t lastTick = 0;
static uint32_t tickCount = 0;
static bool leakOnDone = false, leakReadDone = false, distDone = false, dhtDone = false;
static uint32_t lastStats = 0;
static uint32_t loopMaxUs = 0;
static float leakValue = NAN, distValue = NAN;

static void onVibration() {
  if (vibEdges < 65535) vibEdges++;
}

static int freeRam() {
  extern int __heap_start, *__brkval;
  int v;
  return (int)&v - (__brkval == 0 ? (int)&__heap_start : (int)__brkval);
}

static const __FlashStringHelper* stateName(uint8_t s) {
  return s == LVL_CRITICAL ? F("CRITICAL") : (s == LVL_WARNING ? F("WARNING") : F("NORMAL"));
}

// ---- sensors -----------------------------------------------------------------------------

static void soundSample(uint32_t now) {
#if USE_SOUND
  if (buzzer.blanking(now)) return;      // sensor blanking: the mic would hear our own beep
  int s = analogRead(PIN_SOUND);
  int base = (int)(soundBase >> SOUND_EMA_SHIFT);
  uint16_t dev = (uint16_t)abs(s - base);
  if (dev > soundPeak) soundPeak = dev;
  if (dev < SOUND_QUIET) {
    soundBase += s - (soundBase >> SOUND_EMA_SHIFT);    // EMA, updated only when quiet
    soundQuietSeen = true;
  }
  soundSum += s;
  soundCount++;
#endif
}

// 1 s of samples at boot: the starting baseline (keep the room quiet).
static void soundCalibrate() {
#if USE_SOUND
  uint32_t sum = 0, n = 0, start = millis();
  while (millis() - start < 1000UL) {
    sum += analogRead(PIN_SOUND);
    n++;
  }
  soundBase = (int32_t)(sum / n) << SOUND_EMA_SHIFT;
  Serial.print(F("# sound_baseline="));
  Serial.println(sum / n);
#endif
}

// Peak of the last second; resets the window. Re-seeds the baseline if no sample was quiet
// for SOUND_RESEED_TICKS seconds (the module's DC level moved), so it can never get stuck.
static float soundTake() {
#if USE_SOUND
  float peak = soundPeak;
  if (soundQuietSeen) {
    soundLoudTicks = 0;
  } else if (++soundLoudTicks >= SOUND_RESEED_TICKS && soundCount) {
    soundBase = (int32_t)(soundSum / soundCount) << SOUND_EMA_SHIFT;
    soundLoudTicks = 0;
  }
  soundPeak = 0;
  soundSum = 0;
  soundCount = 0;
  soundQuietSeen = false;
  return peak;
#else
  return NAN;
#endif
}

static float vibTake() {
#if USE_VIBRATION
  noInterrupts();                        // copy and clear atomically
  uint16_t n = vibEdges;
  vibEdges = 0;
  interrupts();
  return n;
#else
  return NAN;
#endif
}

static void dhtRead() {
#if USE_DHT11
  // The library blocks ~25 ms (20 ms start signal for the DHT11).
  bool ok = dht.read(true);
  float t = ok ? dht.readTemperature() : NAN;
  float h = ok ? dht.readHumidity() : NAN;
  if (ok && !isnan(t) && !isnan(h)) {
    dhtTemp = t;
    dhtHum = h;
    dhtFails = 0;
  } else if (++dhtFails >= DHT_MAX_FAILS) {
    dhtTemp = dhtHum = NAN;              // sensor fault: fields go empty
    dhtFails = DHT_MAX_FAILS;
  }
#endif
}

// Leak, in two steps 20 ms apart (non-blocking): power the sensor (only with LEAK_POWER_PIN),
// then read it once it has settled and power it off again.
static void leakStart() {
#ifdef LEAK_POWER_PIN
  digitalWrite(LEAK_POWER_PIN, HIGH);
#endif
}

static void leakRead() {
#if USE_LEAK
  analogRead(PIN_LEAK);                  // first read after switching the ADC channel settles it
  leakValue = analogRead(PIN_LEAK);
#ifdef LEAK_POWER_PIN
  digitalWrite(LEAK_POWER_PIN, LOW);
#endif
#endif
}

// HC-SR04: 400 = no echo (nothing in range, clear); NAN = the module does not answer.
// pulseIn() as in firmware/tests/test_ultrasonic (the bench-tested numbers).
static void distanceRead() {
#if USE_HCSR04
  if (digitalRead(PIN_ECHO) == HIGH) {   // still high from before: cannot measure
    distValue = NAN;
    return;
  }
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  unsigned long us = pulseIn(PIN_ECHO, HIGH, ECHO_TIMEOUT_US);
  if (us == 0) {
    // Echo still HIGH at the timeout: the module is waiting for an echo that never came,
    // i.e. nothing within range. Echo LOW: no pulse at all, the module did not answer.
    distValue = digitalRead(PIN_ECHO) == HIGH ? DISTANCE_CM_OUT_OF_RANGE : NAN;
    return;
  }
  float cm = us / 58.0f;
  distValue = cm > DISTANCE_CM_OUT_OF_RANGE ? DISTANCE_CM_OUT_OF_RANGE : cm;
#endif
}

static void ina219Read() {
#if USE_INA219
  if (inaOk) {
    values[IDX_CURRENT_MA] = ina219.getCurrent_mA();
    values[IDX_BUS_V] = ina219.getBusVoltage_V();
    return;
  }
#endif
  values[IDX_CURRENT_MA] = NAN;
  values[IDX_BUS_V] = NAN;
}

// ---- output ------------------------------------------------------------------------------

static void printRow(uint32_t ms) {
  Serial.print(ms);
  for (uint8_t i = 0; i < SENSOR_COUNT; i++) {
    Serial.print(',');
    if (isnan(values[i])) continue;      // empty field rule: never 0 / -1 / NaN
    if (CSV_DECIMALS[i] == 0) {
      Serial.print((long)values[i]);
    } else {
      Serial.print(values[i], CSV_DECIMALS[i]);
    }
  }
  Serial.print(',');
  Serial.println(stateName(sm.state));
}

static void tick(uint32_t now) {
  values[IDX_TEMP_C] = dhtTemp;
  values[IDX_HUMIDITY] = dhtHum;
  values[IDX_SOUND_PEAK] = soundTake();
  values[IDX_VIB_COUNT] = vibTake();
  values[IDX_LEAK_RAW] = USE_LEAK ? leakValue : NAN;
  values[IDX_DISTANCE_CM] = USE_HCSR04 ? distValue : NAN;
  ina219Read();

  uint8_t before = sm.state;
  sm.update(values);
  if (sm.state == LVL_WARNING && before != LVL_WARNING) buzzer.beep(80);   // chirp
  buzzer.setCritical(sm.state == LVL_CRITICAL);

  printRow(now);
  display.render(sm, values, now / 1000UL);
}

#if PARITY_TEST
// Feeds every parity case through a fresh StateMachine and prints one comment line per row:
//   # parity,<case>,<row>,<STATE>,<hold_remaining or empty>,<first reason sensor index or empty>
static void runParity() {
  display.showP(PSTR("PARITY TEST"), PSTR("see serial"));
  float row[SENSOR_COUNT];
  uint16_t total = 0;
  for (uint8_t c = 0; c < PARITY_CASE_COUNT; c++) {
    const ParityCase& pc = PARITY_CASES[c];
    StateMachine p;
    p.begin(pc.rules, pc.count, pc.hold);
    for (uint8_t r = 0; r < pc.rows; r++) {
      for (uint8_t i = 0; i < pc.count; i++) row[i] = pgm_read_float(&pc.values[r * pc.count + i]);
      p.update(row);
      Serial.print(F("# parity,"));
      Serial.print(pc.name);
      Serial.print(',');
      Serial.print(r + 1);
      Serial.print(',');
      Serial.print(stateName(p.state));
      Serial.print(',');
      if (p.holdRemaining() >= 0) Serial.print(p.holdRemaining());
      Serial.print(',');
      if (p.reasonCount) Serial.print(p.reasons[0].sensor);
      Serial.println();
      total++;
    }
  }
  Serial.print(F("# parity_done,"));
  Serial.println(total);
}
#endif

// ---- setup / loop ------------------------------------------------------------------------

void setup() {
  wdt_disable();
  Serial.begin(115200);
  Serial.println(F("# fw machine_monitor v" FW_VERSION));
  buzzer.begin(PIN_BUZZER, BUZZER_ENABLED, BUZZER_PASSIVE, BUZZER_FREQ_HZ);

  bool lcd = display.begin();
  display.showP(PSTR("Machine Monitor"), PSTR("Calibrating..."));
  Serial.println(lcd ? F("# lcd=ok") : F("# lcd=not found (running without it)"));

#if PARITY_TEST
  runParity();
#endif

#if USE_VIBRATION
  pinMode(PIN_VIB, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_VIB), onVibration, CHANGE);
#endif
#if USE_HCSR04
  pinMode(PIN_TRIG, OUTPUT);
  digitalWrite(PIN_TRIG, LOW);
  pinMode(PIN_ECHO, INPUT);
#endif
#ifdef LEAK_POWER_PIN
  pinMode(LEAK_POWER_PIN, OUTPUT);
  digitalWrite(LEAK_POWER_PIN, LOW);
#endif
#if USE_INA219
  inaOk = ina219.begin();
  Serial.println(inaOk ? F("# ina219=ok") : F("# ina219=not found"));
#endif
#if USE_DHT11
  dht.begin();
#endif

  // The DHT11 needs ~1 s after power-up; the sound calibration covers it.
  soundCalibrate();
#if USE_DHT11
  dhtRead();
  Serial.println(isnan(dhtTemp) ? F("# dht11=no reading yet") : F("# dht11=ok"));
#endif
  leakStart();
  uint32_t settle = millis();
  while (millis() - settle < PHASE_LEAK_READ_MS - PHASE_LEAK_ON_MS) {}
  leakRead();
  distanceRead();
  vibTake();                             // drop edges counted during setup

  sm.begin(SENSOR_RULES, SENSOR_COUNT, HOLD_SECONDS);
  buzzer.beep(200);                      // boot beep
  Serial.print(F("# free_ram="));
  Serial.println(freeRam());
  Serial.println(F(CSV_HEADER));         // last line of setup (DATA_CONTRACT.md section 2)

  lastTick = millis() - TICK_MS;         // first data line right away
  lastStats = millis();
  wdt_enable(WDTO_2S);                   // a hang resets the board after 2 s
}

void loop() {
  uint32_t startUs = micros();
  uint32_t now = millis();
  wdt_reset();

  buzzer.tick(now);                      // first, so soundSample() sees the current buzzer state
  soundSample(now);

  uint32_t phase = now - lastTick;
  if (phase >= TICK_MS) {
    // Next tick on the 1 s grid; if we fell more than a tick behind, resync (no bursts).
    lastTick = (phase >= 2 * TICK_MS) ? now : lastTick + TICK_MS;
    tick(now);
    tickCount++;
    leakOnDone = leakReadDone = distDone = dhtDone = false;
  } else {
    if (!leakOnDone && phase >= PHASE_LEAK_ON_MS) {
      leakStart();
      leakOnDone = true;
    }
    if (!leakReadDone && phase >= PHASE_LEAK_READ_MS) {
      leakRead();
      leakReadDone = true;
    }
    if (!distDone && phase >= PHASE_DIST_MS) {
      distanceRead();
      distDone = true;
    }
    if (!dhtDone && phase >= PHASE_DHT_MS) {
      if (tickCount % DHT_EVERY_TICKS == 0) dhtRead();
      dhtDone = true;
    }
  }

  if (now - lastStats >= STATS_EVERY_MS) {
    lastStats = now;
    Serial.print(F("# free_ram="));
    Serial.print(freeRam());
    Serial.print(F(" loop_max_ms="));
    Serial.println((loopMaxUs + 999) / 1000);
    loopMaxUs = 0;
  }

  uint32_t took = micros() - startUs;
  if (took > loopMaxUs) loopMaxUs = took;
}
