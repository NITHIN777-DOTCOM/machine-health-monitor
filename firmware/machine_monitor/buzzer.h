// Buzzer patterns on D8, non-blocking: call tick() every loop.
//   boot      one 200 ms beep
//   WARNING   one short chirp (80 ms) when the state enters WARNING
//   CRITICAL  200 ms on / 200 ms off, three beeps, then a 1 s pause, repeating
//   NORMAL    silent
// BUZZER_ENABLED 0 keeps it silent (testing); the patterns still run.
// BUZZER_PASSIVE 1 (default, the fitted module): a passive buzzer, driven with tone() at
// BUZZER_FREQ_HZ; a steady level makes no sound (bench test 2026-10-24, HIL_RESULTS.md).
// BUZZER_PASSIVE 0: an active (self-oscillating) buzzer, driven with a steady HIGH.
//
// tone() uses Timer2. Nothing else in the sketch does: millis()/micros() are Timer0, D2 is
// INT0, the watchdog and I2C (TWI) are their own hardware, pulseIn() is a counting loop.
// While a tone plays its interrupt steals a few % of the CPU, so a pulseIn() distance taken
// during a beep reads a few % short (firmware/README.md, Buzzer).
//
// Sensor blanking: the microphone hears the buzzer (sound_peak 30-39 during a beep on the
// bench, inside the sound hysteresis band), so the sketch ignores sound samples while
// blanking() is true: while it sounds and BLANK_MS after (HIL_RESULTS.md).
//
// Silent = noTone() and the pin back to INPUT (high impedance), not driven: on the bench,
// holding D8 LOW made the buzzer module draw a steady current that lifted every analog
// reading by ~20 counts (dry leak ~6 -> ~26, sound baseline 15 -> 35).
#pragma once

#include <Arduino.h>

class Buzzer {
 public:
  void begin(uint8_t pin, bool enabled, bool passive, uint16_t freqHz) {
    pin_ = pin;
    enabled_ = enabled;
    passive_ = passive;
    freqHz_ = freqHz;
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

  // True while the buzzer sounds and for BLANK_MS after it stops (sensor blanking).
  bool blanking(uint32_t now) const {
    return pinOn_ || now - offAt_ < BLANK_MS;
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
      if (on && passive_) {
        tone(pin_, freqHz_);                 // sets the pin to OUTPUT itself
      } else if (on) {
        digitalWrite(pin_, HIGH);
        pinMode(pin_, OUTPUT);
      } else {
        if (passive_) noTone(pin_);          // stops Timer2, leaves the pin OUTPUT LOW
        pinMode(pin_, INPUT);                // high impedance, see above
        digitalWrite(pin_, LOW);             // and no pull-up
        offAt_ = now;
      }
      pinOn_ = on;
    }
  }

 private:
  static const uint16_t CRIT_CYCLE_MS = 3 * 400 + 1000;
  static const uint16_t BLANK_MS = 50;      // the beep's tail and the sound module settling
  uint8_t pin_ = 0;
  bool enabled_ = true;
  bool passive_ = true;
  uint16_t freqHz_ = 2500;
  bool critical_ = false;
  bool pinOn_ = false;
  uint32_t critStart_ = 0;
  uint32_t beepStart_ = 0;
  uint16_t beepMs_ = 0;
  uint32_t offAt_ = 0;
};
