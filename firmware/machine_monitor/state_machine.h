// Device state machine: a C++ port of DeviceStateMachine in backend/app/device_rules.py.
// The behaviour must stay IDENTICAL (docs/DATA_CONTRACT.md section 3); the parity test
// (backend/scripts/firmware_parity.py) checks it row by row on the real board.
//
//   - escalation is immediate (can skip WARNING)
//   - de-escalation only when every enabled sensor is clear of the current level's limit
//     by its hysteresis (in the limit's direction) for holdSeconds consecutive rows,
//     one level at a time
//   - an enabled core sensor with an empty field (NAN) -> at least WARNING
//
// No Arduino dependencies: plain C++ so it can be reasoned about (and compiled) on its own.
#pragma once

#include <math.h>
#include <stdint.h>

enum Level : uint8_t { LVL_NORMAL = 0, LVL_WARNING = 1, LVL_CRITICAL = 2 };

// SensorRule.flags
#define RULE_HAS_WARN 0x01   // warn limit set (null in sensors.json = no limit)
#define RULE_HAS_CRIT 0x02
#define RULE_BELOW    0x04   // direction "below": a value at or below the limit is bad
#define RULE_CORE     0x08   // tier "core": an empty field is a sensor fault
#define RULE_ENABLED  0x10   // sensors.json "enabled"

struct SensorRule {
  float warn;
  float critical;
  float hyst;      // hysteresis margin (0 when null)
  uint8_t flags;
};

enum TriggerKind : uint8_t { TRIG_LIMIT = 0, TRIG_FAULT = 1 };

// One reason for the current state (Trigger in device_rules.py).
struct Trigger {
  uint8_t sensor;  // index into the rules array
  uint8_t kind;    // TRIG_LIMIT or TRIG_FAULT
  uint8_t level;   // LVL_WARNING or LVL_CRITICAL
  bool inBand;     // past limit-minus-hysteresis, but not the limit itself
  float value;
  float limit;
};

#define SM_MAX_REASONS 4

class StateMachine {
 public:
  uint8_t state = LVL_NORMAL;
  uint8_t holdCount = 0;     // consecutive rows the current level has been clear
  bool clearing = false;
  Trigger reasons[SM_MAX_REASONS];
  uint8_t reasonCount = 0;

  void begin(const SensorRule* rules, uint8_t count, uint8_t holdSeconds) {
    rules_ = rules;
    count_ = count;
    hold_ = holdSeconds;
    reset();
  }

  void reset() {
    state = LVL_NORMAL;
    holdCount = 0;
    clearing = false;
    reasonCount = 0;
  }

  // Seconds left before the next step down, or -1 when not counting down (hold_remaining_s).
  int8_t holdRemaining() const { return clearing ? (int8_t)(hold_ - holdCount) : -1; }

  // One row (one second). values[i] = NAN for an empty field. Returns the new state.
  uint8_t update(const float* values) {
    uint8_t instant = LVL_NORMAL, sticky = LVL_NORMAL;
    Trigger t;
    for (uint8_t i = 0; i < count_; i++) {
      if (trigger(i, values[i], false, t) && t.level > instant) instant = t.level;
      if (trigger(i, values[i], true, t) && t.level > sticky) sticky = t.level;
    }

    if (instant > state) {
      state = instant;            // escalate immediately, possibly by two levels
      holdCount = 0;
    } else if (sticky < state) {
      holdCount++;                // clear of the current level (with margin)
      if (holdCount >= hold_) {
        state--;                  // one level down only
        holdCount = 0;
      }
    } else {
      holdCount = 0;
    }

    clearing = sticky < state;
    if (state == LVL_NORMAL) {
      reasonCount = 0;
    } else {
      // Active reasons: hysteresis triggers at or above the current level. When there are
      // none (clearing), keep the reasons that put us here so the LCD can still show them.
      Trigger active[SM_MAX_REASONS];
      uint8_t n = 0;
      for (uint8_t i = 0; i < count_ && n < SM_MAX_REASONS; i++) {
        if (trigger(i, values[i], true, t) && t.level >= state) active[n++] = t;
      }
      if (n > 0) {
        for (uint8_t k = 0; k < n; k++) reasons[k] = active[k];
        reasonCount = n;
      }
    }
    return state;
  }

 private:
  const SensorRule* rules_ = nullptr;
  uint8_t count_ = 0;
  uint8_t hold_ = 5;

  // value at/past limit; the margin moves the limit towards "safe" (hysteresis).
  static bool breaches(float value, float limit, bool below, float margin) {
    return below ? value <= limit + margin : value >= limit - margin;
  }

  static uint8_t sensorLevel(const SensorRule& r, float value, float margin) {
    bool below = r.flags & RULE_BELOW;
    if ((r.flags & RULE_HAS_CRIT) && breaches(value, r.critical, below, margin)) return LVL_CRITICAL;
    if ((r.flags & RULE_HAS_WARN) && breaches(value, r.warn, below, margin)) return LVL_WARNING;
    return LVL_NORMAL;
  }

  // The trigger for sensor i (triggers() in device_rules.py); false when it pushes nothing.
  bool trigger(uint8_t i, float value, bool useHysteresis, Trigger& out) const {
    const SensorRule& r = rules_[i];
    if (!(r.flags & RULE_ENABLED)) return false;
    if (isnan(value)) {
      if (!(r.flags & RULE_CORE)) return false;   // optional sensor empty: no effect
      out = {i, TRIG_FAULT, LVL_WARNING, false, NAN, NAN};
      return true;
    }
    float margin = useHysteresis ? r.hyst : 0.0f;
    uint8_t level = sensorLevel(r, value, margin);
    if (level == LVL_NORMAL) return false;
    float limit = level == LVL_CRITICAL ? r.critical : r.warn;
    out = {i, TRIG_LIMIT, level, !breaches(value, limit, r.flags & RULE_BELOW, 0.0f), value, limit};
    return true;
  }
};
