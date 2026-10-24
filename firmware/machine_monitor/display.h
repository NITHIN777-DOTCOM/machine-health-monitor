// 16x2 I2C LCD (hd44780 library, PCF8574 backpack at 0x27): screen texts and flicker-free
// updates. Screens (see firmware/README.md):
//   boot      "Machine Monitor" / "Calibrating..."
//   NORMAL    "NORMAL  T30.3C"  / rotates every 3 s: "S4 V2 L6" <-> "Dist 158cm" ("Dist clear" = 400)
//   WARN/CRIT "CRIT VIB 66>60"  / alternates every 2 s: second reason, "Recover in 4s" (counting down);
//             with neither, the sensor's limits ("warn>20 crit>60")
//   fault     "SENSOR FAULT"    / "DHT11"
// Value vs limit: '>' / '<' = past the limit (direction above / below), '~' = back inside the
// hysteresis band (not yet clear). If no LCD answers, every call is a no-op and the sketch runs on.
#pragma once

#include <Arduino.h>
#include <Wire.h>
#include <hd44780.h>
#include <hd44780ioClass/hd44780_I2Cexp.h>

#include "config_generated.h"
#include "state_machine.h"

#define LCD_ADDR 0x27
#define LCD_COLS 16

class Display {
 public:
  bool begin() {
    Wire.begin();
    Wire.setWireTimeout(3000, true);     // a stuck I2C bus must not hang the sketch
    ok_ = lcd_.begin(LCD_COLS, 2) == 0;
    shown_[0][0] = shown_[1][0] = '\0';
    return ok_;
  }

  bool ok() const { return ok_; }

  // Writes only the lines whose text changed (no flicker, little I2C traffic).
  void show(const char* line1, const char* line2) {
    if (!ok_) return;
    const char* lines[2] = {line1, line2};
    for (uint8_t row = 0; row < 2; row++) {
      char padded[LCD_COLS + 1];
      fit(padded, lines[row]);
      if (strcmp(padded, shown_[row]) != 0) {
        lcd_.setCursor(0, row);
        lcd_.print(padded);
        strcpy(shown_[row], padded);
      }
    }
  }

  // Same, for two PROGMEM strings: showP(PSTR("Machine Monitor"), PSTR("Calibrating...")).
  void showP(PGM_P line1, PGM_P line2) {
    char l1[LCD_COLS + 1], l2[LCD_COLS + 1];
    strncpy_P(l1, line1, LCD_COLS);
    strncpy_P(l2, line2, LCD_COLS);
    l1[LCD_COLS] = l2[LCD_COLS] = '\0';
    show(l1, l2);
  }

  // The screen for the current state. values[i] = NAN for an empty field; sec = seconds since boot.
  void render(const StateMachine& sm, const float* values, uint32_t sec) {
    char l1[24], l2[24];
    if (sm.state == LVL_NORMAL) {
      normalScreen(values, sec, l1, l2);
    } else {
      alertScreen(sm, sec, l1, l2);
    }
    show(l1, l2);
  }

 private:
  hd44780_I2Cexp lcd_{LCD_ADDR};
  bool ok_ = false;
  char shown_[2][LCD_COLS + 1];

  // Truncate / pad with spaces to exactly 16 characters.
  static void fit(char* out, const char* in) {
    uint8_t i = 0;
    for (; i < LCD_COLS && in[i]; i++) out[i] = in[i];
    for (; i < LCD_COLS; i++) out[i] = ' ';
    out[LCD_COLS] = '\0';
  }

  // Appends a number: dp decimals, or none when it is whole.
  static void num(char* out, float v, uint8_t dp) {
    char buf[12];
    if (v == (long)v) dp = 0;
    dtostrf(v, 0, dp, buf);
    strcat(out, buf);
  }

  static uint8_t lcdDecimals(uint8_t i) { return i == IDX_TEMP_C ? 1 : (i == IDX_BUS_V ? 2 : 0); }

  static void name(char* out, uint8_t i, const char* const* table) {
    strcat_P(out, (PGM_P)pgm_read_word(&table[i]));
  }

  // "CRIT VIB 66>60" (withState) or "VIB 66>60"; faults: "SENSOR FAULT" / "FAULT DHT11".
  static void reasonText(char* out, const Trigger& t, bool withState) {
    out[0] = '\0';
    if (t.kind == TRIG_FAULT) {
      if (withState) {
        strcpy_P(out, PSTR("SENSOR FAULT"));
      } else {
        strcpy_P(out, PSTR("FAULT "));
        name(out, t.sensor, HW_NAMES);
      }
      return;
    }
    if (withState) strcpy_P(out, t.level == LVL_CRITICAL ? PSTR("CRIT ") : PSTR("WARN "));
    name(out, t.sensor, LCD_NAMES);
    strcat_P(out, PSTR(" "));
    num(out, t.value, lcdDecimals(t.sensor));
    const char op[2] = {t.inBand ? '~' : ((SENSOR_RULES[t.sensor].flags & RULE_BELOW) ? '<' : '>'), '\0'};
    strcat(out, op);
    num(out, t.limit, 1);
  }

  void normalScreen(const float* v, uint32_t sec, char* l1, char* l2) const {
    strcpy_P(l1, PSTR("NORMAL"));
#if USE_DHT11
    if (!isnan(v[IDX_TEMP_C])) {
      strcat_P(l1, PSTR("  T"));
      num(l1, v[IDX_TEMP_C], 1);
      strcat_P(l1, PSTR("C"));
    }
#endif
    char a[24] = "";                       // page A: "S4 V2 L6" (enabled sensors only)
#if USE_SOUND
    part(a, 'S', v[IDX_SOUND_PEAK]);
#endif
#if USE_VIBRATION
    part(a, 'V', v[IDX_VIB_COUNT]);
#endif
#if USE_LEAK
    part(a, 'L', v[IDX_LEAK_RAW]);
#endif
#if USE_HCSR04
    char b[24];                            // page B: "Dist 158cm" / "Dist clear"
    strcpy_P(b, PSTR("Dist "));
    float d = v[IDX_DISTANCE_CM];
    if (isnan(d)) {
      strcat_P(b, PSTR("--"));
    } else if (d >= DISTANCE_CM_OUT_OF_RANGE) {
      strcat_P(b, PSTR("clear"));
    } else {
      num(b, d, 0);
      strcat_P(b, PSTR("cm"));
    }
    strcpy(l2, (a[0] == '\0' || (sec / 3) % 2) ? b : a);
#else
    strcpy(l2, a);
#endif
  }

  static void part(char* out, char letter, float value) {
    if (out[0]) strcat_P(out, PSTR(" "));
    const char p[2] = {letter, '\0'};
    strcat(out, p);
    if (isnan(value)) {
      strcat_P(out, PSTR("-"));
    } else {
      num(out, value, 0);
    }
  }

  static void alertScreen(const StateMachine& sm, uint32_t sec, char* l1, char* l2) {
    if (sm.reasonCount == 0) {             // cannot happen above NORMAL, but never show garbage
      strcpy_P(l1, sm.state == LVL_CRITICAL ? PSTR("CRITICAL") : PSTR("WARNING"));
      l2[0] = '\0';
      return;
    }
    const Trigger& first = sm.reasons[0];
    reasonText(l1, first, true);

    // Second reason: skip faults from the same module (temp_c + humidity are both the DHT11).
    char second[24] = "";
    for (uint8_t k = 1; k < sm.reasonCount; k++) {
      const Trigger& t = sm.reasons[k];
      if (t.kind == TRIG_FAULT && first.kind == TRIG_FAULT &&
          strcmp_P(HW_NAME_FOR(t.sensor), (PGM_P)pgm_read_word(&HW_NAMES[first.sensor])) == 0) continue;
      reasonText(second, t, true);
      break;
    }
    char recover[24] = "";
    if (sm.clearing) {
      strcpy_P(recover, PSTR("Recover in "));
      num(recover, sm.holdRemaining(), 0);
      strcat_P(recover, PSTR("s"));
    }

    char base[24];                         // line 2 when there is nothing else to say
    if (first.kind == TRIG_FAULT) {
      base[0] = '\0';
      name(base, first.sensor, HW_NAMES);
    } else {
      limitsText(base, first.sensor);
    }
    // Line 2 pages, 2 s each: [module name for a fault], [second reason], [countdown].
    const char* pages[3];
    uint8_t n = 0;
    if (first.kind == TRIG_FAULT) pages[n++] = base;
    if (second[0]) pages[n++] = second;
    if (recover[0]) pages[n++] = recover;
    if (n == 0) pages[n++] = base;         // nothing else to say: the limits
    strcpy(l2, pages[(sec / 2) % n]);
  }

  // "warn>20 crit>60" ('<' for direction below).
  static void limitsText(char* out, uint8_t i) {
    const SensorRule& r = SENSOR_RULES[i];
    const char* op = (r.flags & RULE_BELOW) ? "<" : ">";
    out[0] = '\0';
    if (r.flags & RULE_HAS_WARN) {
      strcat_P(out, PSTR("warn"));
      strcat(out, op);
      num(out, r.warn, 1);
    }
    if (r.flags & RULE_HAS_CRIT) {
      if (out[0]) strcat_P(out, PSTR(" "));
      strcat_P(out, PSTR("crit"));
      strcat(out, op);
      num(out, r.critical, 1);
    }
  }

  // A sensor's module name in RAM, for comparing two names (both live in PROGMEM).
  static const char* HW_NAME_FOR(uint8_t i) {
    static char buf[17];
    strncpy_P(buf, (PGM_P)pgm_read_word(&HW_NAMES[i]), sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';
    return buf;
  }
};
