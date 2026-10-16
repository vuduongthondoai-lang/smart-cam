# ESP32-CAM Web Dashboard

Flask dashboard for reading event history from SQL Server and playing saved MP4 clips. Its live view shares the exact JPEG frames already received by `tracking.py`, so it does not open a second connection to the ESP32-CAM.

## 1. Files

- `app.py`: Flask server and read-only SQL Server API.
- `templates/index.html`: dashboard HTML.
- `static/style.css`: responsive design.
- `static/app.js`: status polling, event table, optional live stream, and playback.

## 2. Requirements

On Windows, open PowerShell:

```powershell
cd D:\esp32-cam\web_dashboard
python -m pip install -r requirements.txt
```

`pyodbc` needs Microsoft ODBC Driver 17 or 18 for SQL Server installed on Windows. This should be the same Windows environment where SSMS and SQL Server are working.

## 3. Configuration

The defaults follow the current `tracking.py` setup:

- SQL Server: `(local)` using Windows Authentication
- Database: `esp32_surveillance`
- Table: `dbo.person_events`
- Recordings: `D:\esp32-cam\recordings`
- ESP32-CAM upstream: `http://192.168.1.38/stream` (used only by `tracking.py`)
- Shared stream from `tracking.py`: `http://127.0.0.1:8765/stream`

If your working `tracking.py` uses a different SQL Server instance, set `SQLSERVER_SERVER` to the exact same server name before running Flask. Example for PowerShell:

```powershell
$env:SQLSERVER_SERVER = '.\SQLEXPRESS'
python app.py
```

Other optional environment variables:

```powershell
$env:DB_NAME = 'esp32_surveillance'
$env:RECORDING_DIR = 'D:\esp32-cam\recordings'
$env:CAMERA_STREAM_URL = 'http://192.168.1.38/stream'
```

## 4. Run

```powershell
cd D:\esp32-cam\web_dashboard
python app.py
```

Open in a browser on the same PC:

`http://127.0.0.1:5000`

The dashboard reads data only; it does not create/change tables or write rows. It expects the table created by `tracking.py` to include `id`, `event_start`, `last_detected_at`, `clip_saved_at`, `video_filename`, `video_path`, `video_duration_seconds`, `total_frames`, and `detected_frames`.

## 5. Live camera note

Start `tracking.py` first, then start Flask. `tracking.py` opens the one physical ESP32-CAM `/stream` connection and republishes the latest raw JPEG frames through a local MJPEG server at `http://127.0.0.1:8765/stream`. The dashboard route `/camera.mjpeg` only proxies that local relay. It does not transcode frames and does not create a second connection to the ESP32-CAM, allowing YOLO, servo tracking, recording, and web live view to run at the same time. If tracking.py is stopped, the dashboard live view is unavailable until tracking.py is started again.

## 6. Troubleshooting

- **SQL disconnected:** verify the server name matches the successful connection used by `tracking.py`, and that ODBC Driver 17 or 18 is installed.
- **Video unavailable:** verify the `RECORDING_DIR` path and that the file remains in that folder.
- **Camera unavailable in web:** start `tracking.py` first and confirm it prints `[WEB] Luong chia se san sang: http://127.0.0.1:8765/stream`. Open the relay on the same PC at `http://127.0.0.1:8765/stream`. Do not use `http://192.168.1.38/stream` as the dashboard source while tracking.py is running, because that creates a second ESP32-CAM stream connection.
- **Port 5000 in use:** set `$env:PORT = '5001'` before `python app.py`; then open `http://127.0.0.1:5001`.


## 7. Browser video playback

Saved videos written by OpenCV with the `mp4v` codec may not decode in Chrome/Edge. The `/recordings/<filename>` endpoint now creates a one-time cached H.264/yuv420p browser-compatible copy on the first playback request, then serves that copy with HTTP byte-range support. Converted copies are stored in `recordings\_web_compatible`; the original MP4 files remain unchanged. This conversion happens in Flask only when a user requests playback and does not run in tracking.py's camera/YOLO/servo loop.

Install the added dependency after updating the dashboard:

```powershell
python -m pip install -r requirements.txt
```
