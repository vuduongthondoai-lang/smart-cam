import cv2
import urllib.request
import numpy as np
import serial
import time
import threading
import queue
from ultralytics import YOLO


# =========================================================
# CAMERA CONFIG
# =========================================================

ESP32_CAM_IP = "192.168.1.8"

STREAM_URL = f"http://{ESP32_CAM_IP}/stream"


# =========================================================
# ESP32 DEVKIT SERIAL
# =========================================================

SERIAL_PORT = "COM9"
BAUDRATE = 115200


# =========================================================
# YOLO CONFIG
# =========================================================

# YOLO chỉ chạy khoảng 7 FPS
# Video vẫn chạy liên tục
YOLO_INTERVAL = 0.14

# COCO class 0 = person
PERSON_CLASS = 0

# Confidence tối thiểu
CONFIDENCE = 0.50


# =========================================================
# SERVO LIMIT
# =========================================================

PAN_MIN = 20
PAN_MAX = 160

TILT_MIN = 20
TILT_MAX = 160


# =========================================================
# HOME POSITION
# =========================================================

HOME_PAN = 90
HOME_TILT = 90


# =========================================================
# TRACKING
# =========================================================

# Vùng chết ở giữa màn hình
# Người nằm trong vùng này -> không quay servo
DEAD_ZONE_X = 35
DEAD_ZONE_Y = 30


# Hệ số điều khiển
PAN_GAIN = 0.025
TILT_GAIN = 0.025


# Servo không được thay đổi quá nhiều
# trong một lần YOLO cập nhật
MAX_STEP = 3


# =========================================================
# SMOOTHING
# =========================================================

# 0.0 -> rất mượt nhưng phản ứng chậm
# 1.0 -> phản ứng nhanh nhưng dễ rung
#
# 0.35 là mức cân bằng tốt
SMOOTH_ALPHA = 0.35


# =========================================================
# SERIAL CONTROL
# =========================================================

# Chỉ gửi lệnh tối đa 20 lần / giây
SERVO_INTERVAL = 0.05

# Góc phải thay đổi ít nhất 1 độ mới gửi
MIN_ANGLE_CHANGE = 1


# =========================================================
# RETURN HOME
# =========================================================

# Không thấy người trong 10 giây
# -> quay về HOME
RETURN_HOME_TIMEOUT = 10.0


# Tốc độ quay về HOME
# 1 độ mỗi lần update
HOME_STEP = 1


# =========================================================
# DETECTION DISPLAY
# =========================================================

# Box YOLO chỉ được giữ trên màn hình trong khoảng thời gian này
DETECTION_DISPLAY_TIMEOUT = 0.5


# =========================================================
# FRAME QUEUE
# =========================================================

# Chỉ giữ 1 frame
#
# Đây là phần rất quan trọng để giảm delay.
#
# Nếu camera tạo frame nhanh hơn YOLO,
# frame cũ sẽ bị bỏ.
frame_queue = queue.Queue(maxsize=1)


running = True


# =========================================================
# CONNECT ESP32 DEVKIT
# =========================================================

print("Connecting ESP32 DevKit...")

try:

    ser = serial.Serial(
        SERIAL_PORT,
        BAUDRATE,
        timeout=0.01,
        write_timeout=0.01
    )

except serial.SerialException as e:

    print()
    print("========================================")
    print("ERROR: Cannot open serial port")
    print("========================================")
    print(f"Port: {SERIAL_PORT}")
    print()
    print("Hay dong Arduino Serial Monitor")
    print("va tat cac chuong trinh dang dung COM nay.")
    print()
    print("Chi tiet:")
    print(e)

    raise SystemExit


time.sleep(2)

print("ESP32 DevKit connected.")


# =========================================================
# LOAD YOLO
# =========================================================

print("Loading YOLO...")

try:

    model = YOLO("yolo11n.pt")

except Exception as e:

    print("Cannot load YOLO:")
    print(e)

    ser.close()

    raise SystemExit


print("YOLO loaded.")


# =========================================================
# CAMERA THREAD
# =========================================================

def camera_thread():

    global running

    print("Connecting camera stream...")

    try:

        stream = urllib.request.urlopen(
            STREAM_URL,
            timeout=10
        )

    except Exception as e:

        print("Cannot connect to ESP32-CAM:")
        print(e)

        running = False

        return


    bytes_data = b""

    print("Camera stream connected.")


    while running:

        try:

            # -------------------------------------------------
            # READ CAMERA DATA
            # -------------------------------------------------

            data = stream.read(8192)

            if not data:

                continue


            bytes_data += data


            # -------------------------------------------------
            # FIND JPEG
            # -------------------------------------------------

            start = bytes_data.find(b'\xff\xd8')

            end = bytes_data.find(b'\xff\xd9')


            if start == -1 or end == -1 or end <= start:

                # tránh buffer phình quá lớn
                if len(bytes_data) > 2_000_000:

                    bytes_data = bytes_data[-100_000:]

                continue


            # -------------------------------------------------
            # EXTRACT JPEG
            # -------------------------------------------------

            jpg = bytes_data[start:end + 2]

            bytes_data = bytes_data[end + 2:]


            # -------------------------------------------------
            # DECODE
            # -------------------------------------------------

            frame = cv2.imdecode(
                np.frombuffer(
                    jpg,
                    dtype=np.uint8
                ),
                cv2.IMREAD_COLOR
            )


            if frame is None:

                continue


            # =================================================
            # LATEST FRAME ONLY
            # =================================================

            # Nếu queue đầy:
            # bỏ frame cũ
            if frame_queue.full():

                try:

                    frame_queue.get_nowait()

                except queue.Empty:

                    pass


            # Đưa frame mới nhất vào
            try:

                frame_queue.put_nowait(frame)

            except queue.Full:

                pass


        except Exception as e:

            print("Camera error:", e)

            break


    try:

        stream.close()

    except:

        pass


# =========================================================
# START CAMERA THREAD
# =========================================================

camera_thread_obj = threading.Thread(
    target=camera_thread,
    daemon=True
)

camera_thread_obj.start()


# =========================================================
# SERVO VARIABLES
# =========================================================

pan_angle = HOME_PAN
tilt_angle = HOME_TILT


last_sent_pan = pan_angle
last_sent_tilt = tilt_angle


last_servo_time = 0


# =========================================================
# DETECTION VARIABLES
# =========================================================

last_yolo_time = 0


# Khởi tạo bằng thời gian hiện tại
# để tránh camera tự HOME ngay lúc khởi động
last_detection_time = time.time()


last_person = None


# =========================================================
# SMOOTH PERSON POSITION
# =========================================================

smooth_person_x = None
smooth_person_y = None


# =========================================================
# SEND SERVO COMMAND
# =========================================================

def send_servo_command():

    global last_sent_pan
    global last_sent_tilt

    command = f"P{pan_angle} T{tilt_angle}\n"


    try:

        ser.write(
            command.encode()
        )

        last_sent_pan = pan_angle
        last_sent_tilt = tilt_angle


    except serial.SerialException as e:

        print("Serial error:", e)


# =========================================================
# TRACKING CONTROL
# =========================================================

def tracking_control(
    person_x,
    person_y,
    frame_width,
    frame_height
):

    global pan_angle
    global tilt_angle


    # -----------------------------------------------------
    # CAMERA CENTER
    # -----------------------------------------------------

    center_x = frame_width // 2
    center_y = frame_height // 2


    # -----------------------------------------------------
    # ERROR
    # -----------------------------------------------------

    error_x = person_x - center_x
    error_y = person_y - center_y


    # =====================================================
    # PAN
    # =====================================================

    if abs(error_x) > DEAD_ZONE_X:

        movement = error_x * PAN_GAIN


        # Giới hạn tốc độ
        movement = max(
            -MAX_STEP,
            min(MAX_STEP, movement)
        )


        step = int(round(movement))


        if step == 0:

            step = 1 if movement > 0 else -1


        pan_angle += step


    # =====================================================
    # TILT
    # =====================================================

    if abs(error_y) > DEAD_ZONE_Y:

        movement = error_y * TILT_GAIN


        # Giới hạn tốc độ
        movement = max(
            -MAX_STEP,
            min(MAX_STEP, movement)
        )


        step = int(round(movement))


        if step == 0:

            step = 1 if movement > 0 else -1


        tilt_angle += step


    # =====================================================
    # LIMIT
    # =====================================================

    pan_angle = max(
        PAN_MIN,
        min(PAN_MAX, pan_angle)
    )


    tilt_angle = max(
        TILT_MIN,
        min(TILT_MAX, tilt_angle)
    )


# =========================================================
# RETURN HOME
# =========================================================

def return_home():

    global pan_angle
    global tilt_angle


    # -----------------------------------------------------
    # PAN
    # -----------------------------------------------------

    if pan_angle < HOME_PAN:

        pan_angle += HOME_STEP

    elif pan_angle > HOME_PAN:

        pan_angle -= HOME_STEP


    # -----------------------------------------------------
    # TILT
    # -----------------------------------------------------

    if tilt_angle < HOME_TILT:

        tilt_angle += HOME_STEP

    elif tilt_angle > HOME_TILT:

        tilt_angle -= HOME_STEP


    # -----------------------------------------------------
    # LIMIT
    # -----------------------------------------------------

    pan_angle = max(
        PAN_MIN,
        min(PAN_MAX, pan_angle)
    )


    tilt_angle = max(
        TILT_MIN,
        min(TILT_MAX, tilt_angle)
    )


# =========================================================
# MAIN LOOP
# =========================================================

print()
print("========================================")
print("ESP32-CAM PERSON TRACKING")
print("========================================")
print(f"Camera: {ESP32_CAM_IP}")
print(f"Serial: {SERIAL_PORT}")
print(f"YOLO interval: {YOLO_INTERVAL}s")
print("Return HOME: 10 seconds")
print("HOME PAN : 90")
print("HOME TILT: 90")
print("Press Q to quit.")
print("========================================")
print()


while running:

    # =====================================================
    # GET LATEST FRAME
    # =====================================================

    try:

        frame = frame_queue.get(
            timeout=1
        )

    except queue.Empty:

        continue


    current_time = time.time()


    # =====================================================
    # YOLO
    # =====================================================

    if (
        current_time - last_yolo_time
        >= YOLO_INTERVAL
    ):

        last_yolo_time = current_time


        # -------------------------------------------------
        # YOLO DETECTION
        # -------------------------------------------------

        results = model(
            frame,
            verbose=False,
            classes=[PERSON_CLASS],
            conf=CONFIDENCE
        )


        persons = []


        # -------------------------------------------------
        # READ DETECTIONS
        # -------------------------------------------------

        for result in results:

            if result.boxes is None:

                continue


            for box in result.boxes:

                x1, y1, x2, y2 = map(
                    int,
                    box.xyxy[0]
                )


                confidence = float(
                    box.conf[0]
                )


                width = x2 - x1
                height = y2 - y1


                area = width * height


                persons.append(
                    (
                        area,
                        x1,
                        y1,
                        x2,
                        y2,
                        confidence
                    )
                )


        # =================================================
        # PERSON FOUND
        # =================================================

        if persons:

            # -------------------------------------------------
            # CHOOSE LARGEST PERSON
            # -------------------------------------------------

            persons.sort(
                key=lambda x: x[0],
                reverse=True
            )


            (
                area,
                x1,
                y1,
                x2,
                y2,
                confidence
            ) = persons[0]


            # -------------------------------------------------
            # PERSON CENTER
            # -------------------------------------------------

            person_x = (x1 + x2) // 2

            person_y = (y1 + y2) // 2


            # =================================================
            # SMOOTH PERSON POSITION
            # =================================================

            if smooth_person_x is None:

                smooth_person_x = float(person_x)
                smooth_person_y = float(person_y)

            else:

                smooth_person_x = (
                    SMOOTH_ALPHA * person_x
                    +
                    (1 - SMOOTH_ALPHA)
                    * smooth_person_x
                )


                smooth_person_y = (
                    SMOOTH_ALPHA * person_y
                    +
                    (1 - SMOOTH_ALPHA)
                    * smooth_person_y
                )


            # Chuyển về int
            tracking_x = int(
                smooth_person_x
            )

            tracking_y = int(
                smooth_person_y
            )


            # -------------------------------------------------
            # UPDATE DETECTION TIME
            # -------------------------------------------------

            last_detection_time = current_time


            # -------------------------------------------------
            # SAVE DETECTION
            # -------------------------------------------------

            last_person = (
                x1,
                y1,
                x2,
                y2,
                confidence,
                tracking_x,
                tracking_y
            )


            # =================================================
            # TRACK SERVO
            # =================================================

            tracking_control(
                tracking_x,
                tracking_y,
                frame.shape[1],
                frame.shape[0]
            )


            # =================================================
            # SEND SERVO
            # =================================================

            if (
                current_time - last_servo_time
                >= SERVO_INTERVAL
            ):

                if (
                    abs(
                        pan_angle
                        -
                        last_sent_pan
                    )
                    >= MIN_ANGLE_CHANGE

                    or

                    abs(
                        tilt_angle
                        -
                        last_sent_tilt
                    )
                    >= MIN_ANGLE_CHANGE
                ):

                    send_servo_command()

                    last_servo_time = current_time


        # =================================================
        # NO PERSON
        # =================================================

        else:

            # -------------------------------------------------
            # WAIT 10 SECONDS
            # -------------------------------------------------

            if (
                current_time
                -
                last_detection_time
                >= RETURN_HOME_TIMEOUT
            ):

                # Xóa vị trí người cũ
                last_person = None


                # -------------------------------------------------
                # RETURN HOME
                # -------------------------------------------------

                return_home()


                # -------------------------------------------------
                # SEND HOME COMMAND
                # -------------------------------------------------

                if (
                    current_time
                    -
                    last_servo_time
                    >= SERVO_INTERVAL
                ):

                    if (
                        abs(
                            pan_angle
                            -
                            last_sent_pan
                        )
                        >= MIN_ANGLE_CHANGE

                        or

                        abs(
                            tilt_angle
                            -
                            last_sent_tilt
                        )
                        >= MIN_ANGLE_CHANGE
                    ):

                        send_servo_command()

                        last_servo_time = current_time


    # =====================================================
    # DISPLAY
    # =====================================================

    # Copy frame hiện tại
    display = frame.copy()


    # =====================================================
    # DRAW PERSON
    # =====================================================

    if (
        last_person is not None

        and

        current_time
        -
        last_detection_time
        <
        DETECTION_DISPLAY_TIMEOUT
    ):

        (
            x1,
            y1,
            x2,
            y2,
            confidence,
            person_x,
            person_y
        ) = last_person


        # -------------------------------------------------
        # PERSON BOX
        # -------------------------------------------------

        cv2.rectangle(
            display,
            (x1, y1),
            (x2, y2),
            (0, 255, 0),
            2
        )


        # -------------------------------------------------
        # PERSON CENTER
        # -------------------------------------------------

        cv2.circle(
            display,
            (person_x, person_y),
            5,
            (0, 0, 255),
            -1
        )


        # -------------------------------------------------
        # LABEL
        # -------------------------------------------------

        cv2.putText(
            display,
            f"Person {confidence:.2f}",
            (x1, max(20, y1 - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2
        )


    # =====================================================
    # CENTER CROSS
    # =====================================================

    h, w = display.shape[:2]


    center_x = w // 2
    center_y = h // 2


    cv2.line(
        display,
        (center_x, 0),
        (center_x, h),
        (255, 0, 0),
        1
    )


    cv2.line(
        display,
        (0, center_y),
        (w, center_y),
        (255, 0, 0),
        1
    )


    # =====================================================
    # STATUS
    # =====================================================

    cv2.putText(
        display,
        f"PAN: {pan_angle}",
        (10, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2
    )


    cv2.putText(
        display,
        f"TILT: {tilt_angle}",
        (10, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2
    )


    # =====================================================
    # SHOW
    # =====================================================

    cv2.imshow(
        "ESP32-CAM Tracking",
        display
    )


    # =====================================================
    # QUIT
    # =====================================================

    key = cv2.waitKey(1) & 0xFF


    if key == ord('q'):

        running = False

        break


# =========================================================
# CLEANUP
# =========================================================

running = False


try:

    ser.close()

except:

    pass


cv2.destroyAllWindows()


print()
print("========================================")
print("Program stopped.")
print("========================================")