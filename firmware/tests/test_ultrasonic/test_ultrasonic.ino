// HC-SR04 ultrasonic test: Trig -> D9, Echo -> D10, VCC -> 5V, GND -> GND.
// Prints the distance once per second at 115200 baud. Move a hand towards the sensor and
// back; with nothing in front it shows the room (walls/ceiling) or "no echo".
// Results: firmware/tests/RESULTS.md.

const uint8_t PIN_TRIG = 9;
const uint8_t PIN_ECHO = 10;
const unsigned long TIMEOUT_US = 25000UL;   // > 400 cm round trip (23.3 ms)

void setup() {
  Serial.begin(115200);
  pinMode(PIN_TRIG, OUTPUT);
  digitalWrite(PIN_TRIG, LOW);
  pinMode(PIN_ECHO, INPUT);
  Serial.println(F("# test_ultrasonic: distance in cm, 1 reading/s"));
}

void loop() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  unsigned long us = pulseIn(PIN_ECHO, HIGH, TIMEOUT_US);
  if (us == 0) {
    Serial.println(F("no echo (nothing in range or timeout)"));
  } else {
    Serial.print(F("distance_cm="));
    Serial.println(us / 58.0, 1);
  }
  delay(1000);
}
