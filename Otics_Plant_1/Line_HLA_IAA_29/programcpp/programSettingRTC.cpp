
#include <Arduino.h>
#include <WiFi.h>
#include <Adafruit_I2CDevice.h>
#include <SPI.h>
#include <RTClib.h>

RTC_DS3231 rtc;

char daysOfTheWeek[7][12] = {"Minggu", "Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"};

void setup () {
  Serial.begin(9600);

  if (! rtc.begin()) {
    Serial.println("Couldn't find RTC");
    Serial.flush();
    abort();
  }

  if (rtc.lostPower()) {
    Serial.println("RTC lost power, let's set the time!");
    }
  rtc.adjust(DateTime(2026, 4, 14, 14, 10, 0));
  // DateTime(YYYY, MM, DD, HH, mm, ss)

}

void loop () {
    // .nais
}