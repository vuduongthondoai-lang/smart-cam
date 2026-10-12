#include <ESP32Servo.h>

Servo panServo;
Servo tiltServo;

const int PAN_PIN = 18;
const int TILT_PIN = 19;

// Giới hạn cơ khí an toàn ban đầu
const int PAN_MIN = 20;
const int PAN_MAX = 160;

const int TILT_MIN = 20;
const int TILT_MAX = 160;

int panAngle = 90;
int tiltAngle = 90;

int targetPan = 90;
int targetTilt = 90;

unsigned long lastMove = 0;

// Khoảng thời gian giữa mỗi bước servo
const int MOVE_INTERVAL = 15;

// Mỗi lần servo di chuyển tối đa bao nhiêu độ
const int STEP = 1;

void setup()
{
    Serial.begin(115200);

    panServo.setPeriodHertz(50);
    tiltServo.setPeriodHertz(50);

    panServo.attach(PAN_PIN, 500, 2400);
    tiltServo.attach(TILT_PIN, 500, 2400);

    panServo.write(panAngle);
    tiltServo.write(tiltAngle);

    delay(500);

    Serial.println();
    Serial.println("==============================");
    Serial.println("ESP32 PAN/TILT SERVO TEST");
    Serial.println("==============================");
    Serial.println("Send command:");
    Serial.println("P90 T90");
    Serial.println("P120 T70");
    Serial.println("==============================");
}

void loop()
{
    readSerial();

    unsigned long now = millis();

    if (now - lastMove >= MOVE_INTERVAL)
    {
        lastMove = now;

        // PAN
        if (panAngle < targetPan)
        {
            panAngle += STEP;

            if (panAngle > targetPan)
                panAngle = targetPan;

            panServo.write(panAngle);
        }
        else if (panAngle > targetPan)
        {
            panAngle -= STEP;

            if (panAngle < targetPan)
                panAngle = targetPan;

            panServo.write(panAngle);
        }

        // TILT
        if (tiltAngle < targetTilt)
        {
            tiltAngle += STEP;

            if (tiltAngle > targetTilt)
                tiltAngle = targetTilt;

            tiltServo.write(tiltAngle);
        }
        else if (tiltAngle > targetTilt)
        {
            tiltAngle -= STEP;

            if (tiltAngle < targetTilt)
                tiltAngle = targetTilt;

            tiltServo.write(tiltAngle);
        }
    }
}

void readSerial()
{
    if (!Serial.available())
        return;

    String command = Serial.readStringUntil('\n');
    command.trim();

    int pIndex = command.indexOf('P');
    int tIndex = command.indexOf('T');

    if (pIndex == -1 || tIndex == -1)
        return;

    int p = command.substring(pIndex + 1, tIndex).toInt();
    int t = command.substring(tIndex + 1).toInt();

    targetPan = constrain(p, PAN_MIN, PAN_MAX);
    targetTilt = constrain(t, TILT_MIN, TILT_MAX);

    Serial.print("Target PAN=");
    Serial.print(targetPan);

    Serial.print("  TILT=");
    Serial.println(targetTilt);
}
