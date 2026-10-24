// GENERATED - do not edit, run gen_firmware_config.py
// (backend\venv\Scripts\python backend\scripts\gen_firmware_config.py, from the repo root)
// Source: backend/config/sensors.json + backend/config/settings.json
//         (+ the worked examples in docs/DATA_CONTRACT.md for the parity test).
#pragma once

#include "state_machine.h"

#define CSV_HEADER "# ms,temp_c,humidity,sound_peak,vib_count,leak_raw,distance_cm,current_ma,bus_v,dev_state"
#define SENSOR_COUNT 8
#define HOLD_SECONDS 5

// Fitted modules (sensors.json 'enabled'; 1 = read it, 0 = print an empty field).
#define USE_DHT11     1  // temp_c, humidity
#define USE_SOUND     1  // sound_peak
#define USE_VIBRATION 1  // vib_count
#define USE_LEAK      1  // leak_raw
#define USE_HCSR04    1  // distance_cm
#define USE_INA219    0  // current_ma, bus_v

// Column index of each sensor in the values array (CSV order without ms/dev_state).
#define IDX_TEMP_C 0
#define IDX_HUMIDITY 1
#define IDX_SOUND_PEAK 2
#define IDX_VIB_COUNT 3
#define IDX_LEAK_RAW 4
#define IDX_DISTANCE_CM 5
#define IDX_CURRENT_MA 6
#define IDX_BUS_V 7

// 'Nothing in range' readings (a real, clear value, not a fault).
#define DISTANCE_CM_OUT_OF_RANGE 400.0f

// Limits: {warn, critical, hysteresis, flags}. Tier core/optional = RULE_CORE.
static const SensorRule SENSOR_RULES[8] = {
  {32.0f, 35.0f, 0.5f, RULE_HAS_WARN | RULE_HAS_CRIT | RULE_CORE | RULE_ENABLED},  // temp_c (core)
  {0.0f, 0.0f, 0.0f, RULE_CORE | RULE_ENABLED},  // humidity (core)
  {40.0f, 120.0f, 10.0f, RULE_HAS_WARN | RULE_HAS_CRIT | RULE_CORE | RULE_ENABLED},  // sound_peak (core)
  {50.0f, 100.0f, 10.0f, RULE_HAS_WARN | RULE_HAS_CRIT | RULE_CORE | RULE_ENABLED},  // vib_count (core)
  {50.0f, 200.0f, 20.0f, RULE_HAS_WARN | RULE_HAS_CRIT | RULE_ENABLED},  // leak_raw (optional)
  {20.0f, 10.0f, 3.0f, RULE_HAS_WARN | RULE_HAS_CRIT | RULE_BELOW | RULE_ENABLED},  // distance_cm (optional)
  {0.0f, 0.0f, 0.0f, 0},  // current_ma (optional)
  {0.0f, 0.0f, 0.0f, 0},  // bus_v (optional)
};

// Short LCD names (lcd_name) and module names for 'SENSOR FAULT' (hardware).
static const char LCD_NAME_TEMP_C[] PROGMEM = "TMP";
static const char HW_NAME_TEMP_C[] PROGMEM = "DHT11";
static const char LCD_NAME_HUMIDITY[] PROGMEM = "HUM";
static const char HW_NAME_HUMIDITY[] PROGMEM = "DHT11";
static const char LCD_NAME_SOUND_PEAK[] PROGMEM = "SND";
static const char HW_NAME_SOUND_PEAK[] PROGMEM = "Sound module";
static const char LCD_NAME_VIB_COUNT[] PROGMEM = "VIB";
static const char HW_NAME_VIB_COUNT[] PROGMEM = "SW-420";
static const char LCD_NAME_LEAK_RAW[] PROGMEM = "LEAK";
static const char HW_NAME_LEAK_RAW[] PROGMEM = "Water leak";
static const char LCD_NAME_DISTANCE_CM[] PROGMEM = "DIST";
static const char HW_NAME_DISTANCE_CM[] PROGMEM = "HC-SR04";
static const char LCD_NAME_CURRENT_MA[] PROGMEM = "CUR";
static const char HW_NAME_CURRENT_MA[] PROGMEM = "INA219";
static const char LCD_NAME_BUS_V[] PROGMEM = "VBUS";
static const char HW_NAME_BUS_V[] PROGMEM = "INA219";
static const char* const LCD_NAMES[SENSOR_COUNT] PROGMEM = {LCD_NAME_TEMP_C, LCD_NAME_HUMIDITY, LCD_NAME_SOUND_PEAK, LCD_NAME_VIB_COUNT, LCD_NAME_LEAK_RAW, LCD_NAME_DISTANCE_CM, LCD_NAME_CURRENT_MA, LCD_NAME_BUS_V};
static const char* const HW_NAMES[SENSOR_COUNT] PROGMEM = {HW_NAME_TEMP_C, HW_NAME_HUMIDITY, HW_NAME_SOUND_PEAK, HW_NAME_VIB_COUNT, HW_NAME_LEAK_RAW, HW_NAME_DISTANCE_CM, HW_NAME_CURRENT_MA, HW_NAME_BUS_V};

#if PARITY_TEST
// Parity cases: rows of values (NAN = empty field), run through StateMachine at boot.
static const SensorRule PARITY_RULES_EXAMPLE1[1] = {
  {32.0f, 35.0f, 0.5f, RULE_HAS_WARN | RULE_HAS_CRIT | RULE_CORE | RULE_ENABLED},  // temp_c (core)
};
static const float PARITY_VALUES_EXAMPLE1[19] PROGMEM = {
  32.1f,
  31.8f,
  31.4f,
  31.4f,
  31.4f,
  31.4f,
  31.4f,
  35.0f,
  34.4f,
  34.4f,
  34.4f,
  34.4f,
  34.4f,
  31.0f,
  31.0f,
  31.0f,
  31.0f,
  31.0f,
  NAN,
};
static const SensorRule PARITY_RULES_EXAMPLE2[1] = {
  {20.0f, 10.0f, 3.0f, RULE_HAS_WARN | RULE_HAS_CRIT | RULE_BELOW | RULE_ENABLED},  // distance_cm (optional)
};
static const float PARITY_VALUES_EXAMPLE2[20] PROGMEM = {
  150.0f,
  20.0f,
  22.0f,
  25.0f,
  25.0f,
  25.0f,
  25.0f,
  25.0f,
  8.0f,
  14.0f,
  14.0f,
  14.0f,
  14.0f,
  14.0f,
  400.0f,
  400.0f,
  400.0f,
  400.0f,
  400.0f,
  NAN,
};
static const float PARITY_VALUES_FULL[256] PROGMEM = {
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 60.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 45.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 8.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 8.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 8.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 8.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 8.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 15.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 70.0f, 6.0f, 8.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 70.0f, 6.0f, 400.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 58.0f, 6.0f, 400.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 400.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 400.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 400.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 400.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 400.0f, NAN, NAN,
  NAN, NAN, 5.0f, 1.0f, 6.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 130.0f, 1.0f, 250.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 130.0f, 1.0f, 6.0f, NAN, NAN, NAN,
  34.6f, 85.0f, 5.0f, 1.0f, 6.0f, NAN, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 150.0f, NAN, NAN,
  29.0f, 60.0f, 5.0f, 1.0f, 6.0f, 150.0f, NAN, NAN,
};
struct ParityCase { const char* name; const SensorRule* rules; uint8_t count; uint8_t hold;
                    const float* values; uint8_t rows; };
static const ParityCase PARITY_CASES[3] = {
  {"example1", PARITY_RULES_EXAMPLE1, 1, 5, PARITY_VALUES_EXAMPLE1, 19},
  {"example2", PARITY_RULES_EXAMPLE2, 1, 5, PARITY_VALUES_EXAMPLE2, 20},
  {"full", SENSOR_RULES, 8, 5, PARITY_VALUES_FULL, 32},
};
#define PARITY_CASE_COUNT 3
#endif  // PARITY_TEST
