// Buzzer patterns on D8, non-blocking: call tick() every loop.
//   boot      one 200 ms beep
//   WARNING   one short chirp (80 ms) when the state enters WARNING
//   CRITICAL  200 ms on / 200 ms off, three beeps, then a 1 s pause, repeating
//   NORMAL    silent
// BUZZER_ENABLED 0 keeps it silent (testing); the patterns still run.
// BUZZER_ACTIVE_LOW 1 for a low-trigger module (sounds on LOW); default 0 = sounds on HIGH.
//
// Silent = the pin is an INPUT (high impedance), not driven: on the bench, holding D8 LOW
// made the buzzer module draw a steady current that lifted every analog reading by ~20
// counts (dry leak ~6 -> ~26, sound baseline 15 -> 35). High impedance is silent for both
// module types (firmware/tests/test_buzzer checks which level sounds).
#pragma once

#include <Arduino.h>

class Buzzer {
 public:
  void begin(uint8_t pin, bool enabled, bool activeLow) {
    pin_ = pin;
    enabled_ = enabled;
    activeLow_ = activeLow;
    digitalWrite(pin_, LOW);
    pinMode(pin_, INPUT);
  }

  // One beep of `ms` (boot beep, WARNING chirp). Does not interrupt the CRITICAL pattern.
  void beep(uint16_t ms) {
    beepStart_ = millis();
    beepMs_ = ms;
  }

  void setCritical(bool on) {
    if (on && !critical_) critStart_ = millis();
    critical_ = on;
  }

  void tick(uint32_t now) {
    bool on = false;
    if (critical_) {
      uint16_t phase = (now - critStart_) % CRIT_CYCLE_MS;     // 3 x (200 on + 200 off) + 1000 pause
      on = phase < 3 * 400 && (phase % 400) < 200;
    } else if (beepMs_ && now - beepStart_ < beepMs_) {
      on = true;
    } else {
      beepMs_ = 0;
    }
    on = on && enabled_;
    if (on != pinOn_) {
      if (on) {
        digitalWrite(pin_, activeLow_ ? LOW : HIGH);
        pinMode(pin_, OUTPUT);
      } else {
        pinMode(pin_, INPUT);                // high impedance, see above
        digitalWrite(pin_, LOW);             // and no pull-up
      }
      pinOn_ = on;
    }
  }

 private:
  static const uint16_t CRIT_CYCLE_MS = 3 * 400 + 1000;
  uint8_t pin_ = 0;
  bool enabled_ = true;
  bool activeLow_ = false;
  bool critical_ = false;
  bool pinOn_ = false;
  uint32_t critStart_ = 0;
  uint32_t beepStart_ = 0;
  uint16_t beepMs_ = 0;
};
