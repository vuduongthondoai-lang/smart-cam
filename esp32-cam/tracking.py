print("[START] tracking.py dang khoi dong", flush=True)

import cv2
import urllib.request
import numpy as np
import serial
import time
import threading
import queue
import os
from datetime import datetime
from ultralytics import YOLO


# =========================================================
# CAMERA CONFIG
# =========================================================

ESP32_CAM_IP = "192.168.1.38"

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

# Ha nguong confidence de tang kha nang phat hien nguoi; khong tang kich thuoc anh de giu toc do
CONFIDENCE = 0.35
YOLO_IMGSZ = 640


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
# EVENT RECORDING (BACKGROUND THREAD)
# =========================================================

# Khi khong con thay nguoi, ghi them 3 giay canh trong roi dong clip.
RECORDING_STOP_DELAY = 3.0
RECORDING_DIR = r"D:\esp32-cam\recordings"
RECORDING_FPS = 15.0
RECORDING_CODEC = "mp4v"

os.makedirs(RECORDING_DIR, exist_ok=True)

# Hang doi rieng, gioi han de khong tich luy RAM; luong camera/display khong cho ghi file.
# Khi day, bo frame cu thay vi block live view.
record_queue = queue.Queue(maxsize=30)

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


def recording_thread():
    """Ghi frame co nguoi va ghi tiep toi da 3 giay canh trong sau lan cuoi.

    Moi hang doi gom (frame goc, timestamp monotonic, YOLO co phat hien nguoi).
    Frame trong chi duoc ghi neu clip da mo; no khong the tu mo mot clip moi.
    """
    writer = None
    current_path = None
    last_detection_time = None

    def close_writer():
        nonlocal writer, current_path, last_detection_time
        if writer is not None:
            writer.release()
            print("[REC] Da luu video:", current_path, flush=True)
        writer = None
        current_path = None
        last_detection_time = None

    def open_writer(frame):
        nonlocal writer, current_path
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        current_path = os.path.join(RECORDING_DIR, f"person_{stamp}.mp4")
        height, width = frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*RECORDING_CODEC)
        writer = cv2.VideoWriter(
            current_path, fourcc, RECORDING_FPS, (width, height)
        )
        if not writer.isOpened():
            print("[REC] Khong mo duoc file video:", current_path, flush=True)
            writer.release()
            writer = None
            current_path = None
            return False
        print("[REC] Bat dau ghi:", current_path, flush=True)
        return True

    while running or not record_queue.empty():
        try:
            frame, captured_at, person_detected = record_queue.get(timeout=0.1)
        except queue.Empty:
            # Khi het cua so 3 giay tinh tu frame co nguoi cuoi cung, dong file.
            if (writer is not None and last_detection_time is not None
                    and time.monotonic() - last_detection_time >= RECORDING_STOP_DELAY):
                close_writer()
            continue

        try:
            # Neu nguoi quay lai sau >= 3 giay vang, dong clip cu truoc.
            # Frame co nguoi se mo clip moi; frame trong sau han bi bo qua.
            if (writer is not None and last_detection_time is not None
                    and captured_at - last_detection_time >= RECORDING_STOP_DELAY):
                close_writer()

            # Khong mo file neu frame nay khong co nguoi va chua co clip.
            if writer is None:
                if not person_detected:
                    continue
                if not open_writer(frame):
                    continue

            # Moc thoi gian chi duoc lam moi khi YOLO dang bao co nguoi.
            if person_detected:
                last_detection_time = captured_at
            elif (last_detection_time is None
                  or captured_at - last_detection_time >= RECORDING_STOP_DELAY):
                close_writer()
                continue

            # Ghi frame camera goc, khong co box/chu/crosshair.
            writer.write(frame)
        except Exception as exc:
            print("[REC] Loi ghi video:", exc, flush=True)
            close_writer()
        finally:
            record_queue.task_done()

    close_writer()


# =========================================================
# CONNECT ESP32 DEVKIT
# =========================================================

print("Connecting ESP32 DevKit...", flush=True)

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

print("Loading YOLO...", flush=True)

try:

    model = YOLO("yolo11n.pt")

except Exception as e:

    print("Cannot load YOLO:")
    print(e)

    ser.close()

    raise SystemExit


print("YOLO loaded.", flush=True)


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

recording_thread_obj = threading.Thread(
    target=recording_thread,
    daemon=True
)
recording_thread_obj.start()


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
# Trang thai ket qua YOLO gan nhat va moc thoi gian frame co nguoi gan nhat.
person_detected_now = False
last_person_detected_mono = None
last_recording_frame_time = 0.0


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
print(f"YOLO confidence: {CONFIDENCE}")
print(f"Recording folder: {RECORDING_DIR}")
print(f"Recording: person detected + {RECORDING_STOP_DELAY}s final empty scene.")
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

        results = model.predict(
            source=frame,
            imgsz=YOLO_IMGSZ,
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


        # Trang thai phat hien chi cap nhat moi moi lan YOLO chay.
        # Khi YOLO khong tim thay nguoi, khong gui frame vang nguoi vao recorder.
        person_detected_now = bool(persons)

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
    # RECORD: DETECTED PERSON + 3 SECONDS OF EMPTY SCENE
    # =====================================================

    # Lay mau toi da 15 FPS. Khi YOLO thay nguoi, cap nhat moc thoi gian.
    # Khi YOLO khong thay nguoi, van gui frame trong toi da 3 giay de ghi vao
    # phan cuoi clip. Het 3 giay thi ngung gui frame; recorder dong file MP4.
    captured_at = time.monotonic()
    if person_detected_now:
        last_person_detected_mono = captured_at

    within_recording_window = (
        person_detected_now
        or (
            last_person_detected_mono is not None
            and captured_at - last_person_detected_mono < RECORDING_STOP_DELAY
        )
    )

    if within_recording_window and (
        captured_at - last_recording_frame_time >= 1.0 / RECORDING_FPS
    ):
        record_item = (frame.copy(), captured_at, bool(person_detected_now))

        if record_queue.full():
            try:
                record_queue.get_nowait()
                record_queue.task_done()
            except queue.Empty:
                pass

        try:
            record_queue.put_nowait(record_item)
            last_recording_frame_time = captured_at
        except queue.Full:
            # Khong block live view neu recorder khong theo kip.
            last_recording_frame_time = captured_at


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

# Cho luong ghi xu ly het frame dang cho roi dong file MP4.
running = False
try:
    recording_thread_obj.join(timeout=5.0)
except Exception:
    pass

# Cho writer ket thuc dong file MP4 truoc khi thoat.
recording_thread_obj.join()


try:

    ser.close()

except:

    pass


cv2.destroyAllWindows()


print()
print("========================================")
print("Program stopped.")
print("========================================")
