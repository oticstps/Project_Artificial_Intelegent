//main.cpp




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
#include <RTClib.h>


#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define MSG_BUFFER_SIZE 100


const char* ssid = "otics-camai-iaa29";
const char* password = "pt_otics1*";
const char* mqtt_server = "10.42.0.1";


const char* MQTT_TOPIC_RESULT = "11220223_core_nais_result";
const char* MQTT_TOPIC_JUDG   = "11220223_core_nais_judg";


const int buttonPin = 23;


const byte rxPinDfplayer = 27;
const byte txPinDfplayer = 26;


char msg[MSG_BUFFER_SIZE];


WiFiClient espClient;
PubSubClient client(espClient);
SoftwareSerial dfplayer(rxPinDfplayer, txPinDfplayer);
DFRobotDFPlayerMini myDFPlayer;
Adafruit_SH1106G display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
RTC_DS3231 rtc;


// Debounce tombol
const unsigned long debounceDelay = 200;
bool buttonStableState = HIGH;
bool lastButtonReading = HIGH;
unsigned long lastDebounceTime = 0;


// =====================================================
// Helper display
// =====================================================
void showMessage(const String& line1, const String& line2 = "", const String& line3 = "") {
  display.clearDisplay();
  display.setCursor(0, 0);
  display.println(line1);
  if (line2.length() > 0) display.println(line2);
  if (line3.length() > 0) display.println(line3);
  display.display();
}


// =====================================================
// WiFi
// =====================================================
void setup_wifi() {
  delay(10);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);


  showMessage("WiFi connecting...");


  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }


  showMessage("WiFi connected", WiFi.localIP().toString());
  delay(1500);
}


// =====================================================
// DFPlayer
// =====================================================
void playTrack(uint8_t track) {
  myDFPlayer.play(track);
  Serial.print("[DFPLAYER] Play track: ");
  Serial.println(track);


  showMessage("Play sound", "Track: " + String(track));
}


// =====================================================
// Parsing helper
// =====================================================
int getFirstDataResultValue(const String& message) {
  // format contoh:
  // data_result,1,1,1,1,1,1,1,1,1,#
  int firstComma = message.indexOf(',');
  if (firstComma < 0) return -1;


  int secondComma = message.indexOf(',', firstComma + 1);
  if (secondComma < 0) return -1;


  String firstValue = message.substring(firstComma + 1, secondComma);
  return firstValue.toInt();
}


int getTrackFromTestSound(const String& message) {
  // format: test_sound,7
  int commaPos = message.indexOf(',');
  if (commaPos < 0) return -1;




  String trackStr = message.substring(commaPos + 1);  trackStr.trim();
  return trackStr.toInt();
}


// =====================================================
// MQTT callback
// =====================================================
void callback(char* topic, byte* payload, unsigned int length) {
  String incomingTopic = String(topic);
  String message;


  for (unsigned int i = 0; i < length; i++) {
    message += (char)payload[i];
  }


  Serial.println("====================================");
  Serial.print("[MQTT] Topic   : ");
  Serial.println(incomingTopic);
  Serial.print("[MQTT] Message : ");
  Serial.println(message);


  showMessage("Msg arrived:", incomingTopic, message);


  // -------------------------------------------------
  // 1) Perintah manual sound dari button_reset.py
  // -------------------------------------------------
  if (incomingTopic == MQTT_TOPIC_JUDG) {
    if (message.startsWith("test_sound,")) {
      int track = getTrackFromTestSound(message);


      if (track >= 1 && track <= 10) {
        playTrack((uint8_t)track);
      } else {
        showMessage("Invalid test_sound", message);
      }
      return;
    }


    // data_reset dari GUI reset
    if (message.startsWith("data_reset,")) {
      // sesuai label di button_reset.py:
      // 10 = Reset berhasil
      playTrack(10);
      showMessage("Reset command", "Track 10 played");
      return;
    }


    // data_judg dari tombol fisik / sistem lain
    if (message.startsWith("data_judg,")) {
      showMessage("Judgment cmd", "Received");
      return;
    }
  }


  // -------------------------------------------------
  // 2) Hasil judgment dari sistem vision
  // -------------------------------------------------
  if (incomingTopic == MQTT_TOPIC_RESULT) {
    if (message.startsWith("data_result,")) {
      int firstValue = getFirstDataResultValue(message);


      // logika lama dipertahankan:
      // 1 = OK -> track 1
      // selain itu -> track 3
      if (firstValue == 1) {
        playTrack(1);   // Oke selesai
        showMessage("Result: OK", "Track 1");
      } else {
        playTrack(3);   // Alarm
        showMessage("Result: NG", "Track 3");
      }
      return;
    }
  }
}


// =====================================================
// MQTT reconnect
// =====================================================
void reconnect() {
  while (!client.connected()) {
    showMessage("MQTT connecting...");


    String clientId = "ESP32Client-";
    clientId += String(random(0xffff), HEX);


    if (client.connect(clientId.c_str())) {
      client.subscribe(MQTT_TOPIC_RESULT);
      client.subscribe(MQTT_TOPIC_JUDG);


      showMessage("MQTT connected", "Sub result + judg");
      Serial.println("[MQTT] Connected and subscribed");
    } else {
      showMessage("MQTT error", "Retrying...");
      delay(2000);
    }
  }
}


// =====================================================
// Setup
// =====================================================
void setup() {
  Serial.begin(115200);


  display.begin(0x3C);
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SH110X_WHITE);
  showMessage("App Run!", "CAMAI 1.1 TPS");
  delay(1500);


  pinMode(buttonPin, INPUT_PULLUP);
  pinMode(rxPinDfplayer, INPUT);
  pinMode(txPinDfplayer, OUTPUT);


  setup_wifi();


  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);


  dfplayer.begin(9600);
  if (myDFPlayer.begin(dfplayer)) {
    myDFPlayer.volume(25);   // 0 - 30
    showMessage("DFPlayer OK", "Volume 25");
  } else {
    showMessage("DFPlayer fail");
  }
  delay(1000);


  if (!rtc.begin()) {
    showMessage("RTC not found");
    while (1);
  }


  esp_task_wdt_init(5, true);
  esp_task_wdt_add(NULL);
}


// =====================================================
// Loop
// =====================================================
void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    showMessage("Reconnecting WiFi...");
    setup_wifi();
  }


  if (!client.connected()) {
    reconnect();
  }


  client.loop();


  // =================================================
  // Debounce tombol fisik, publish 1 kali saat ditekan
  // =================================================
  bool reading = digitalRead(buttonPin);


  if (reading != lastButtonReading) {
    lastDebounceTime = millis();
  }


  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (reading != buttonStableState) {
      buttonStableState = reading;


      // trigger hanya saat transisi HIGH -> LOW
      if (buttonStableState == LOW) {
        DateTime now = rtc.now();


        snprintf(
          msg,
          MSG_BUFFER_SIZE,
          "data_judg,1,1,1,%d,%d,%d,%d,%d,%d,#",
          now.year(), now.month(), now.day(),
          now.hour(), now.minute(), now.second()
        );


        showMessage("Publish message:", msg);
        Serial.print("[MQTT] Publish: ");
        Serial.println(msg);


        client.publish(MQTT_TOPIC_JUDG, msg);
      }
    }
  }


  lastButtonReading = reading;


  // Info DFPlayer selesai play
  if (myDFPlayer.available()) {
    int type = myDFPlayer.readType();
    if (type == DFPlayerPlayFinished) {
      int track = myDFPlayer.read();
      showMessage("Track finished", "Track: " + String(track));
    }
  }


  esp_task_wdt_reset();
  delay(20);
}

