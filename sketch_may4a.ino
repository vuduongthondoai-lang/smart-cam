  #include <WiFi.h>
  #include <PubSubClient.h>
  #include <ArduinoJson.h>
  #include <Wire.h>
  #include <Adafruit_GFX.h>
  #include <Adafruit_SSD1306.h>
  #include <DHT.h>
  #include <Keypad.h>

  // =====================================================
  // WIFI
  // =====================================================
  const char* WIFI_SSID = "Bin Bon";
  const char* WIFI_PASSWORD = "21101995";

  // =====================================================
  // THINGSBOARD MQTT
  // =====================================================
  const char* MQTT_SERVER = "192.168.1.218";  
  const int MQTT_PORT = 1883;
  const char* TOKEN = "ij9G16lwtLQuoTtTAk4U";

  // =====================================================
  // GPIO
  // =====================================================
  #define LED_PIN 4
  #define FAN_PIN 5
  #define BUZZER_PIN 19
  #define DHT_PIN 23
  #define MQ2_PIN 34

  // =====================================================
  // DOOR MOTOR
  // =====================================================
  #define DOOR_IN1 18
  #define DOOR_IN2 15

  // =====================================================
  // DHT
  // =====================================================
  #define DHTTYPE DHT11
  DHT dht(DHT_PIN, DHTTYPE);

  // =====================================================
  // OLED
  // =====================================================
  #define SCREEN_WIDTH 128
  #define SCREEN_HEIGHT 64
  #define OLED_RESET -1

  Adafruit_SSD1306 display(
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    &Wire,
    OLED_RESET
  );

  // =====================================================
  // WIFI + MQTT
  // =====================================================
  WiFiClient espClient;
  PubSubClient client(espClient);

  // =====================================================
  // SENSOR
  // =====================================================
  float temperature = 0;
  float humidity = 0;
  int gasValue = 0;

  // =====================================================
  // ALERT THRESHOLD
  // =====================================================
  float tempThreshold = 10000;
  float humidityThreshold = 10000;
  int gasThreshold = 10000;

  // =====================================================
  // DEVICE STATUS
  // =====================================================
  bool ledState = false;
  bool fanState = false;
  bool doorOpen = false;

  // ===== FAN CONTROL MODE =====
  bool manualFan = false;
  bool autoFan = false;
  bool lastAlarmState = false;
  // =====================================================
  // PASSWORD SYSTEM
  // =====================================================
  String password = "1234";

  String inputPassword = "";

  bool loggedIn = false;

  bool showWrongPassword = false;

  bool showAccessGranted = false;

  // =====================================================
  // KEYPAD
  // =====================================================
  const byte ROWS = 4;
  const byte COLS = 4;

  char keys[ROWS][COLS] = {

    {'1','2','3','A'},
    {'4','5','6','B'},
    {'7','8','9','C'},
    {'*','0','#','D'}
  };

  byte rowPins[ROWS] = {
    13,12,14,27
  };

  byte colPins[COLS] = {
    26,25,33,32
  };

  Keypad keypad = Keypad(
    makeKeymap(keys),
    rowPins,
    colPins,
    ROWS,
    COLS
  );

  // =====================================================
  // TIMER SYSTEM
  // =====================================================
  struct DeviceTimer {

    bool active;

    bool originalState;

    bool toggled;

    unsigned long startTime;

    unsigned long delayTime;

    unsigned long implementTime;

    int pin;

    bool* stateVar;
  };

  DeviceTimer ledTimer;
  DeviceTimer fanTimer;

  // =====================================================
  // WIFI CONNECT
  // =====================================================
  void connectWiFi() {

    Serial.println("Connecting WiFi...");

    WiFi.begin(
      WIFI_SSID,
      WIFI_PASSWORD
    );

    while (
      WiFi.status()
      != WL_CONNECTED
    ) {

      delay(500);

      Serial.print(".");
    }

    Serial.println();

    Serial.println("WiFi Connected");

    Serial.println(WiFi.localIP());
  }

  // =====================================================
  // MQTT CONNECT
  // =====================================================
  void connectMQTT() {

    while (!client.connected()) {

      Serial.println("Connecting MQTT...");

      if (
        client.connect(
          "ESP32_Client",
          TOKEN,
          NULL
        )
      ) {

        Serial.println("MQTT Connected");

        client.subscribe(
          "v1/devices/me/rpc/request/+"
        );

      } else {

        Serial.print("MQTT Failed: ");

        Serial.println(client.state());

        delay(2000);
      }
    }
  }

  // =====================================================
  // START TIMER
  // =====================================================
  void startDeviceTimer(
    DeviceTimer &timer,
    int pin,
    bool &stateVar,
    int delaySeconds,
    int implementSeconds
  ) {

    timer.active = true;

    timer.originalState = stateVar;

    timer.toggled = false;

    timer.startTime = millis();

    timer.delayTime =
      delaySeconds * 1000UL;

    timer.implementTime =
      implementSeconds * 1000UL;

    timer.pin = pin;

    timer.stateVar = &stateVar;
    if(pin == LED_PIN)
{
   sendEvent("LED TIMER START");
}

if(pin == FAN_PIN)
{
   sendEvent("FAN TIMER START");
}

    Serial.println("Timer Started");
  }

  // =====================================================
  // HANDLE TIMER
  // =====================================================
  void handleDeviceTimer(
    DeviceTimer &timer
  ) {

    if (!timer.active) return;

    unsigned long now = millis();

    // =====================================
    // DELAY FINISHED
    // =====================================
    if (
      !timer.toggled &&
      now - timer.startTime
      >= timer.delayTime
    ) {

      bool newState =
        !timer.originalState;

      digitalWrite(
        timer.pin,
        newState
      );

      *(timer.stateVar) =
        newState;
        if (timer.pin == FAN_PIN) {
    fanState = newState;
    manualFan = newState;
  }
  if(timer.pin == LED_PIN)
{
    sendEvent(
      newState ?
      "LED ON (TIMER)" :
      "LED OFF (TIMER)"
    );
}

if(timer.pin == FAN_PIN)
{
    sendEvent(
      newState ?
      "FAN ON (TIMER)" :
      "FAN OFF (TIMER)"
    );
}

      timer.toggled = true;

      timer.startTime = now;
      sendTelemetry();

      Serial.println(
        "STATE TOGGLED"
      );
    }

    // =====================================
    // IMPLEMENT FINISHED
    // =====================================
    else if (
    timer.toggled &&
    now - timer.startTime
    >= timer.implementTime
)
{
    digitalWrite(
      timer.pin,
      timer.originalState
    );

    *(timer.stateVar) =
      timer.originalState;

    if (timer.pin == FAN_PIN) {
      fanState = timer.originalState;
      manualFan = timer.originalState;
    }

    if (timer.pin == LED_PIN) {
      ledState = timer.originalState;
    }

    if(timer.pin == LED_PIN)
{
    sendEvent(
      timer.originalState ?
      "LED ON (TIMER END)" :
      "LED OFF (TIMER END)"
    );
}

if(timer.pin == FAN_PIN)
{
    sendEvent(
      timer.originalState ?
      "FAN ON (TIMER END)" :
      "FAN OFF (TIMER END)"
    );
}

    timer.active = false;
    sendTelemetry();
    Serial.println("STATE RESTORED");
}
}

void sendEvent(String eventText)
{
  StaticJsonDocument<128> doc;

  doc["event"] = eventText;

  char buffer[128];

  serializeJson(doc, buffer);

  client.publish(
    "v1/devices/me/telemetry",
    buffer
  );
}

  // =====================================================
  // OPEN DOOR
  // =====================================================
  void openDoor() {

    if (doorOpen) return;

    Serial.println("OPENING DOOR");

    digitalWrite(DOOR_IN1, HIGH);
    digitalWrite(DOOR_IN2, LOW);

    delay(5000);

    digitalWrite(DOOR_IN1, LOW);
    digitalWrite(DOOR_IN2, LOW);

    doorOpen = true;
    sendEvent("DOOR OPEN");
    sendTelemetry();
    Serial.println("DOOR OPENED");
  }

  // =====================================================
  // CLOSE DOOR
  // =====================================================
  void closeDoor() {

    if (!doorOpen) return;

    Serial.println("CLOSING DOOR");

    digitalWrite(DOOR_IN1, LOW);
    digitalWrite(DOOR_IN2, HIGH);

    delay(5000);

    digitalWrite(DOOR_IN1, LOW);
    digitalWrite(DOOR_IN2, LOW);

    doorOpen = false;
    sendEvent("DOOR CLOSE");
    sendTelemetry();
    Serial.println("DOOR CLOSED");
  }

  // =====================================================
  // MQTT CALLBACK
  // =====================================================
  void callback(
    char* topic,
    byte* payload,
    unsigned int length
  ) {

    String msg = "";

    for (int i = 0; i < length; i++) {

      msg += (char)payload[i];
    }

    Serial.println(msg);

    StaticJsonDocument<512> doc;

    deserializeJson(doc, msg);

    String method =
      doc["method"];

    // =====================================
    // LED
    // =====================================
    if (method == "setLed") {

      bool state =
        doc["params"];

      ledState = state;

      digitalWrite(
        LED_PIN,
        ledState
      );
          sendEvent(
      state ?
      "LED ON" :
      "LED OFF"
    );
      sendTelemetry();
    }

    // =====================================
    // FAN
    // =====================================
    else if (method == "setFan") {

    bool state = doc["params"];

    fanState = state;
    manualFan = state;

    digitalWrite(FAN_PIN, state);
    sendEvent(
    state ?
    "FAN ON" :
    "FAN OFF"
);
    sendTelemetry();
  }

    // =====================================
    // LED TIMER
    // =====================================
    else if (
      method == "setLedTimer"
    ) {

      int delayTime =
        doc["params"]["delay"];

      int implementTime =
        doc["params"]["implement"];

      startDeviceTimer(
        ledTimer,
        LED_PIN,
        ledState,
        delayTime,
        implementTime
      );
    }

    // =====================================
    // FAN TIMER
    // =====================================
    else if (method == "setFanTimer") {

    int delayTime =
      doc["params"]["delay"];

    int implementTime =
      doc["params"]["implement"];

    startDeviceTimer(
      fanTimer,
      FAN_PIN,
      fanState,
      delayTime,
      implementTime
    );

    manualFan = fanState;
  }

    // =====================================
    // OPEN DOOR
    // =====================================
    else if (method == "openDoor") {

      openDoor();
    }

    // =====================================
    // CLOSE DOOR
    // =====================================
    else if (method == "closeDoor") {

      closeDoor();
    }

    // =====================================
    // SET THRESHOLD
    // =====================================
    else if (method == "setThreshold") {

      tempThreshold =
        doc["params"]["temp"];

      humidityThreshold =
        doc["params"]["humidity"];

      gasThreshold =  
        doc["params"]["gas"];
        sendEvent(
  "THRESHOLD UPDATED"
);

      Serial.println("Threshold Updated");
    }
  }

  // =====================================================
  // READ SENSOR
  // =====================================================
  void readSensors() {

    temperature =
      dht.readTemperature();

    humidity =
      dht.readHumidity();

    gasValue =
      analogRead(MQ2_PIN);

    if (
      isnan(temperature) ||
      isnan(humidity)
    ) {

      Serial.println(
        "DHT Error"
      );

      return;
    }
  }

  // =====================================================
  // SEND TELEMETRY
  // =====================================================
  void sendTelemetry() {

    StaticJsonDocument<256> doc;

    doc["temperature"] =
      temperature;

    doc["humidity"] =
      humidity;

    doc["gas"] =
      gasValue;

    doc["led"] =
      ledState;

    doc["fan"] =
      fanState;

    doc["door"] =
      doorOpen;

    doc["tempThreshold"] =
      tempThreshold;

    doc["humidityThreshold"] =
      humidityThreshold;

    doc["gasThreshold"] =
      gasThreshold;

    char buffer[256];

    serializeJson(
      doc,
      buffer
    );

    client.publish(
      "v1/devices/me/telemetry",
      buffer
    );
  }

  // =====================================================
  // OLED UI
  // =====================================================
  void updateOLED() {

    display.clearDisplay();

    display.setTextSize(1);

    display.setTextColor(WHITE);

    // LOGIN SCREEN
    if (!loggedIn) {

      display.setCursor(0,0);
      display.println("SMART DOOR");

      display.setCursor(0,15);
      display.println("ENTER PASSWORD");

      display.setCursor(0,40);

      for (int i=0;i<inputPassword.length();i++) {

        display.print("*");
      }

      display.display();

      return;
    }

    // WRONG PASSWORD
    if (showWrongPassword) {

      display.setCursor(0,20);
      display.println("WRONG PASSWORD");

      display.display();

      return;
    }

    // ACCESS GRANTED
    if (showAccessGranted) {

      display.setCursor(0,20);
      display.println("ACCESS GRANTED");

      display.display();

      return;
    }

    // SMART HOME
    display.setCursor(0,0);
    display.print("Temp:");
    display.print(temperature);

    display.setCursor(0,15);
    display.print("Hum:");
    display.print(humidity);

    display.setCursor(0,30);
    display.print("Gas:");
    display.print(gasValue);

    display.setCursor(0,45);

    if (doorOpen) {

      display.print("Door:OPEN");

    } else {

      display.print("Door:CLOSE");
    }

    display.display();
  }

  // =====================================================
  // CHECK ALARM
  // =====================================================
  void checkAlarm() {

    bool alarm = false;

    if (temperature > tempThreshold) alarm = true;
    if (humidity > humidityThreshold) alarm = true;
    if (gasValue > gasThreshold) alarm = true;

    if(alarm != lastAlarmState)
{
    if(alarm)
    {
        sendEvent("BUZZER ON (AUTO ALARM)");
        sendEvent("FAN ON (AUTO ALARM)");
    }
    else
    {
       sendEvent("BUZZER OFF (AUTO ALARM)");
        sendEvent("FAN OFF (AUTO ALARM)");
    }

    lastAlarmState = alarm;
}
    if (alarm) {
      digitalWrite(BUZZER_PIN, HIGH);
      autoFan = true;
    } else {
      digitalWrite(BUZZER_PIN, LOW);
      autoFan = false;
    }
    if (autoFan) {

      fanState = true;
      digitalWrite(FAN_PIN, HIGH);
      return;
    }
    if (fanTimer.active) {
      return;
    }
    if (manualFan) {

      fanState = true;
      digitalWrite(FAN_PIN, HIGH);
      return;
    }
    fanState = false;
    digitalWrite(FAN_PIN, LOW);
  }
  // =====================================================
  // HANDLE PASSWORD
  // =====================================================
  void handlePassword() {

    if (loggedIn) return;

    char key = keypad.getKey();

    if (!key) return;

    // ENTER
    if (key == '#') {

      if (inputPassword == password) {

        showAccessGranted = true;

        updateOLED();

        delay(1500);

        showAccessGranted = false;

        loggedIn = true;

        openDoor();

      } else {

        showWrongPassword = true;

        updateOLED();

        digitalWrite(
          BUZZER_PIN,
          HIGH
        );

        delay(1000);

        digitalWrite(
          BUZZER_PIN,
          LOW
        );

        delay(1000);

        showWrongPassword = false;
      }

      inputPassword = "";
    }

    // CLEAR
    else if (key == '*') {

      inputPassword = "";
    }

    // ADD KEY
    else {

      inputPassword += key;
    }
  }

  // =====================================================
  // SETUP
  // =====================================================
  void setup() {

    Serial.begin(115200);

    pinMode(LED_PIN, OUTPUT);
    pinMode(FAN_PIN, OUTPUT);
    pinMode(BUZZER_PIN, OUTPUT);

    pinMode(DOOR_IN1, OUTPUT);
    pinMode(DOOR_IN2, OUTPUT);

    digitalWrite(LED_PIN, LOW);
    digitalWrite(FAN_PIN, LOW);
    digitalWrite(BUZZER_PIN, LOW);

    digitalWrite(DOOR_IN1, LOW);
    digitalWrite(DOOR_IN2, LOW);

    dht.begin();

    Wire.begin(21,22);

    if (
      !display.begin(
        SSD1306_SWITCHCAPVCC,
        0x3C
      )
    ) {

      Serial.println("OLED Failed");

      while (1);
    }

    updateOLED();

    connectWiFi();

    client.setServer(
      MQTT_SERVER,
      MQTT_PORT
    );

    client.setCallback(callback);

    connectMQTT();
  }

  // =====================================================
  // LOOP
  // =====================================================
  unsigned long lastTelemetry = 0;

  unsigned long lastOLED = 0;

  void loop() {
    if (
      WiFi.status()
      != WL_CONNECTED
    ) {

      connectWiFi();
    }
    if (!client.connected()) {

      connectMQTT();
    }

    client.loop();
    handlePassword();
    if (
      millis() - lastTelemetry
      > 2000
    ) {

      lastTelemetry =
        millis();

      readSensors();

      sendTelemetry();

      checkAlarm();
    }
    if (
      millis() - lastOLED
      > 300
    ) {

      lastOLED =
        millis();

      updateOLED();
    }

    // TIMER
    handleDeviceTimer(
      ledTimer
    );

    handleDeviceTimer(
      fanTimer
    );
  }