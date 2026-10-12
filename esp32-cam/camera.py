
import cv2
import urllib.request
import numpy as np
from ultralytics import YOLO

# ==========================================
# ESP32-CAM
# ==========================================
ESP32_IP = "192.168.1.8"
url = f"http://{ESP32_IP}/stream"

# ==========================================
# YOLO
# ==========================================
print("Dang tai YOLO...")

model = YOLO("yolo11n.pt")

print("YOLO da san sang!")

# ==========================================
# KET NOI ESP32-CAM
# ==========================================
print("Dang ket noi:", url)

stream = urllib.request.urlopen(url, timeout=10)

bytes_data = b""

# ==========================================
# DOC VIDEO
# ==========================================
while True:

    bytes_data += stream.read(4096)

    # Tim dau JPEG
    a = bytes_data.find(b'\xff\xd8')

    # Tim cuoi JPEG
    b = bytes_data.find(b'\xff\xd9')

    if a != -1 and b != -1 and b > a:

        jpg = bytes_data[a:b + 2]
        bytes_data = bytes_data[b + 2:]

        # Giai ma JPEG
        frame = cv2.imdecode(
            np.frombuffer(jpg, dtype=np.uint8),
            cv2.IMREAD_COLOR
        )

        if frame is None:
            continue

        # ==================================
        # YOLO - CHI NHAN DIEN NGUOI
        # ==================================
        annotated_frame = frame

        # ==================================
        # HIEN THI REALTIME
        # ==================================
        cv2.imshow(
            "ESP32-CAM + YOLO",
            annotated_frame
        )

        # Q = thoat
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

# ==========================================
# DONG
# ==========================================
stream.close()
cv2.destroyAllWindows()

