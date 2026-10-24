// I2C scanner: lists every device on SDA (A4) / SCL (A5) every 5 s at 115200 baud.
// Expected: 0x27 = LCD backpack (PCF8574); 0x40 = INA219 when fitted.
// (The copy that was on the board before Phase 7 ran at 9600 baud.)

#include <Wire.h>

void setup() {
  Wire.begin();
  Serial.begin(115200);
  Serial.println(F("# i2c_scanner"));
}

void loop() {
  uint8_t found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.print(F("I2C device found at 0x"));
      if (addr < 16) Serial.print('0');
      Serial.println(addr, HEX);
      found++;
    }
  }
  if (!found) Serial.println(F("No I2C devices found"));
  Serial.println(F("done"));
  delay(5000);
}
