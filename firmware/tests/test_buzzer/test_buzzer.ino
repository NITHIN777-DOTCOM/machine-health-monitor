// Buzzer polarity test: which D8 level makes the module sound?
// Repeats: 2 s OUTPUT HIGH, 2 s high impedance, 2 s OUTPUT LOW, 2 s high impedance, and
// prints the current step at 115200 baud.
//   sounds on HIGH -> an active buzzer: set BUZZER_PASSIVE 0 in machine_monitor.ino
//   neither        -> a passive buzzer (needs tone()): keep BUZZER_PASSIVE 1 (default), or a
//                     wiring fault. The fitted module is passive (HIL 2026-10-24).
// Results: firmware/tests/RESULTS.md and HIL_RESULTS.md.

const uint8_t PIN_BUZZER = 8;

void step(const __FlashStringHelper* what) {
  Serial.println(what);
  delay(2000);
}

void setup() {
  Serial.begin(115200);
  Serial.println(F("# test_buzzer: listen and watch the step names"));
}

void loop() {
  digitalWrite(PIN_BUZZER, HIGH);
  pinMode(PIN_BUZZER, OUTPUT);
  step(F("D8 OUTPUT HIGH  <- beeping now? then the module is active HIGH"));
  pinMode(PIN_BUZZER, INPUT);
  digitalWrite(PIN_BUZZER, LOW);
  step(F("D8 high impedance (should be silent)"));
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);
  step(F("D8 OUTPUT LOW   <- beeping now? then the module is active LOW"));
  pinMode(PIN_BUZZER, INPUT);
  step(F("D8 high impedance (should be silent)"));
}
