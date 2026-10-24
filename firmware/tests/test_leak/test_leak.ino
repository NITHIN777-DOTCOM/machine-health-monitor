// Water leak sensor test: S -> A1, + -> 5V, - -> GND.
// Prints the raw ADC value once per second at 115200 baud (Serial Monitor or arduino-cli monitor).
// Dry: single digits. Touch the traces with a wet finger: hundreds. Wipe dry: back within ~2 s.
// Results: firmware/tests/RESULTS.md.

const uint8_t PIN_LEAK = A1;

void setup() {
  Serial.begin(115200);
  Serial.println(F("# test_leak: raw ADC on A1, 1 reading/s"));
}

void loop() {
  int raw = analogRead(PIN_LEAK);
  Serial.print(F("leak_raw="));
  Serial.println(raw);
  delay(1000);
}
