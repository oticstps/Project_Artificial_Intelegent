#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <DFRobotDFPlayerMini.h>
#include <SoftwareSerial.h>
#include <Adafruit_I2CDevice.h>
#include <SPI.h>
#include <esp_task_wdt.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>
#include <RTClib.h> // RTC Library

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define MSG_BUFFER_SIZE (100)

const char* ssid = "otics-camai-plant2";
const char* password = "pt_otics1*";
const char* mqtt_server = "10.42.0.1";

// const char* ssid = "otics-camai-iaa30";
// const char* password = "pt_otics1*";
// const char* mqtt_server = "10.42.0.1";



const int buttonPin = 23;

const byte rxPinDfplayer = 17;
const byte txPinDfplayer = 16;
char msg[MSG_BUFFER_SIZE];

WiFiClient espClient;
PubSubClient client(espClient);
SoftwareSerial dfplayer(rxPinDfplayer, txPinDfplayer);
DFRobotDFPlayerMini myDFPlayer;
Adafruit_SH1106G display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
RTC_DS3231 rtc;

const unsigned long debounceDelay = 200;
unsigned long lastDebounceTime = 0;
bool lastButtonState = HIGH;

void setup_wifi() {
  delay(10);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  display.clearDisplay();
  display.setCursor(0, 0);
  display.println("WiFi connecting...");
  display.display();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }

  display.clearDisplay();
  display.setCursor(0, 0);
  display.println("WiFi connected");
  display.display();
  delay(2000);
}

void callback(char* topic, byte* payload, unsigned int length) {
  String message;
  for (unsigned int i = 0; i < length; i++) {
    message += (char)payload[i];
  }
  display.clearDisplay();
  display.setCursor(0, 0);
  display.println("Message arrived:");
  display.println(topic);
  display.display();
  if (message.startsWith("data_result,")) {
    int commaPos[5];
    int startPos = 12;
    for (int i = 0; i < 5; i++) {
      commaPos[i] = message.indexOf(',', startPos);
      startPos = commaPos[i] + 1;
    }

    String data[5];
    for (int i = 0; i < 5; i++) {
      if (i == 0) {
        data[i] = message.substring(12, commaPos[i]);
      } else {
        data[i] = message.substring(commaPos[i - 1] + 1, commaPos[i]);
      }
    }

    display.clearDisplay();
    display.setCursor(0, 0);
    display.println("Parsed Data:");
    for (int i = 0; i < 5; i++) {
      display.print("Data ");
      display.print(i + 1);
      display.print(": ");
      display.println(data[i]);
    }
    display.display();
    if (data[0] == "1") {
      myDFPlayer.play(1);
    } else {
      myDFPlayer.play(3);
    }
  }
}


void reconnect() {
  while (!client.connected()) {
    display.clearDisplay();
    display.setCursor(0, 0);
    display.println("CAMAI connecting...");
    display.display();
    String clientId = "ESP32Client-";
    clientId += String(random(0xffff), HEX);
    if (client.connect(clientId.c_str())) {
      display.clearDisplay();
      display.println("CAMAI connected");
      display.display();
      client.subscribe("11220223_core_nais_result");
    } else {
      display.clearDisplay();
      display.println("CAMAI Error");
      display.display();
      delay(2000);
    }
  }
}


void setup() {
  display.begin(0x3C);
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SH110X_WHITE);
  display.setCursor(20, 20);
  display.println("App Run!");
  display.setCursor(20, 40);
  display.println("CAMAI 1.0 TPS");
  display.display();
  delay(2000);
  setup_wifi();
  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);
  dfplayer.begin(9600);
  myDFPlayer.begin(dfplayer);
  if (!rtc.begin()) {
    display.clearDisplay();
    display.setCursor(0, 0);
    display.println("Couldn't find RTC");
    display.display();
    while (1);
  }

  esp_task_wdt_init(5, true);
  esp_task_wdt_add(NULL);
  pinMode(rxPinDfplayer, INPUT);
  pinMode(txPinDfplayer, OUTPUT);
  pinMode(buttonPin, INPUT_PULLUP);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    display.clearDisplay();
    display.setCursor(0, 0);
    display.println("Reconnecting WiFi...");
    display.display();
    setup_wifi();
  }
  if (!client.connected()) {
    reconnect();
  }
  client.loop();
  bool currentButtonState = digitalRead(buttonPin);
  if (currentButtonState != lastButtonState) {
    lastDebounceTime = millis();
  }
  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (currentButtonState == LOW) {
      DateTime now = rtc.now(); // Get current time from RTC
      snprintf(msg, MSG_BUFFER_SIZE,
               "data_judg,1,1,1,%d,%d,%d,%d,%d,%d,#",
               now.year(), now.month(), now.day(),
               now.hour(), now.minute(), now.second());
      display.clearDisplay();
      display.setCursor(0, 0);
      display.println("Publish message:");
      display.println(msg);
      display.display();
      client.publish("11220223_core_nais_judg", msg);
      delay(200);
    }
  }

  lastButtonState = currentButtonState;
  if (myDFPlayer.available()) {
    int type = myDFPlayer.readType();
    if (type == DFPlayerPlayFinished) {
      display.clearDisplay();
      display.setCursor(0, 0);
      display.println("Track finished playing");
      display.display();
    }
  }
  esp_task_wdt_reset();
  delay(100);
}
