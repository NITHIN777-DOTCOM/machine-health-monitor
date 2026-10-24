// Sound module + 16x2 I2C LCD test (clap detection).
// Sound AO -> A2; LCD backpack SDA -> A4, SCL -> A5, address 0x27 (hd44780 library).
// Once per second prints the peak deviation from the quiet level at 115200 baud and shows it
// on the LCD; a peak above CLAP_LEVEL shows "CLAP!" for 2 s.
// Results: firmware/tests/RESULTS.md.

#include <Wire.h>
#include <hd44780.h>
#include <hd44780ioClass/hd44780_I2Cexp.h>

const uint8_t PIN_SOUND = A2;
const int CLAP_LEVEL = 40;

hd44780_I2Cexp lcd(0x27);
long baseline = 0;
unsigned long clapUntil = 0;

void setup() {
  Serial.begin(115200);
  if (lcd.begin(16, 2) != 0) Serial.println(F("# LCD not found at 0x27"));
  lcd.print(F("Sound test"));
  lcd.setCursor(0, 1);
  lcd.print(F("Keep quiet..."));
  // 1 s quiet calibration: the average level is the baseline.
  long sum = 0, n = 0;
  unsigned long t0 = millis();
  while (millis() - t0 < 1000) {
    sum += analogRead(PIN_SOUND);
    n++;
  }
  baseline = sum / n;
  Serial.print(F("# test_sound_lcd: baseline="));
  Serial.println(baseline);
  lcd.clear();
}

void loop() {
  int peak = 0;
  unsigned long t0 = millis();
  while (millis() - t0 < 1000) {          // sample for one second
    int dev = abs(analogRead(PIN_SOUND) - (int)baseline);
    if (dev > peak) peak = dev;
  }
  if (peak >= CLAP_LEVEL) clapUntil = millis() + 2000;
  Serial.print(F("sound_peak="));
  Serial.println(peak);

  lcd.setCursor(0, 0);
  lcd.print(F("Peak: "));
  lcd.print(peak);
  lcd.print(F("        "));
  lcd.setCursor(0, 1);
  lcd.print(millis() < clapUntil ? F("CLAP!           ") : F("listening...    "));
}
