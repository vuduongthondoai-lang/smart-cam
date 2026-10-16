"""Flask dashboard for event recordings and SQL Server history.

The optional live view reads a local MJPEG relay produced by tracking.py. This ensures
there is only one client connected to ESP32-CAM: tracking.py. The dashboard never opens
its own connection to the physical camera.
"""

from __future__ import annotations

import os
import ntpath
import shutil
import subprocess
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, abort, jsonify, render_template, request, send_file, stream_with_context, url_for
import urllib.error
import urllib.request

try:
    import pyodbc
except ImportError:  # API returns an actionable error; the whole app can still start.
    pyodbc = None

BASE_DIR = Path(__file__).resolve().parent

# Keep these aligned with the successful connection configuration in tracking.py.
SQLSERVER_SERVER = os.getenv("SQLSERVER_SERVER", r"(local)")
DB_NAME = os.getenv("DB_NAME", "esp32_surveillance")
DB_SCHEMA = os.getenv("DB_SCHEMA", "dbo")
DB_TABLE = os.getenv("DB_TABLE", "person_events")

RECORDING_DIR = Path(os.getenv("RECORDING_DIR", r"D:\esp32-cam\recordings"))
CAMERA_STREAM_URL = os.getenv("CAMERA_STREAM_URL", "http://192.168.1.38/stream")
TRACKING_RELAY_URL = os.getenv("TRACKING_RELAY_URL", "http://127.0.0.1:8765/stream")
PORT = int(os.getenv("PORT", "5000"))
WEB_CACHE_DIR = RECORDING_DIR / "_web_compatible"
_TRANSCODE_LOCK = threading.Lock()

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


def sql_connection():
    """Open a short-lived Windows-authenticated SQL Server connection."""
    if pyodbc is None:
        raise RuntimeError(
            "Thiếu pyodbc. Hãy cài bằng: python -m pip install pyodbc"
        )

    drivers = pyodbc.drivers()
    driver = next(
        (name for name in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server") if name in drivers),
        None,
    )
    if not driver:
        raise RuntimeError(
            "Không tìm thấy Microsoft ODBC Driver 18/17 for SQL Server. "
            f"Driver hiện có: {drivers}"
        )

    connection_string = (
        f"DRIVER={{{driver}}};"
        f"SERVER={SQLSERVER_SERVER};"
        f"DATABASE={DB_NAME};"
        "Trusted_Connection=yes;"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
        "Connection Timeout=3;"
    )
    return pyodbc.connect(connection_string, timeout=3)


def json_value(value: Any) -> Any:
    """Convert SQL/pyodbc values into JSON-safe values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


@app.get("/")
def index():
    return render_template(
        "index.html",
        camera_stream_url=CAMERA_STREAM_URL,
        server_name=SQLSERVER_SERVER,
        database_name=DB_NAME,
    )


@app.get("/camera.mjpeg")
def camera_proxy():
    """Proxy the tracker-owned local relay, never the physical ESP32-CAM stream.

    tracking.py is the sole camera client and forwards its already-received JPEG frames
    to localhost:8765. Flask only relays those bytes to the browser.
    """
    try:
        upstream = urllib.request.urlopen(TRACKING_RELAY_URL, timeout=5)
    except Exception as exc:
        app.logger.warning("Cannot open tracking relay %s: %s", TRACKING_RELAY_URL, exc)
        return jsonify({"ok": False, "error": f"Không mở được luồng chia sẻ từ tracking.py ({TRACKING_RELAY_URL}): {exc}. Hãy chạy tracking.py trước."}), 502

    upstream_content_type = upstream.headers.get(
        "Content-Type", "multipart/x-mixed-replace; boundary=frame"
    )

    def relay():
        try:
            while True:
                chunk = upstream.read(4096)
                if not chunk:
                    break
                yield chunk
        except GeneratorExit:
            raise
        except Exception as exc:
            app.logger.info("ESP32-CAM stream ended: %s", exc)
        finally:
            upstream.close()

    response = Response(
        stream_with_context(relay()),
        status=200,
        headers={
            "Content-Type": upstream_content_type,
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
        direct_passthrough=True,
    )
    return response


@app.get("/api/status")
def api_status():
    result: dict[str, Any] = {
        "sql_connected": False,
        "sql_error": None,
        "server": SQLSERVER_SERVER,
        "database": DB_NAME,
        "recording_dir": str(RECORDING_DIR),
        "recording_dir_exists": RECORDING_DIR.is_dir(),
        "camera_stream_url": CAMERA_STREAM_URL,
        "tracking_relay_url": TRACKING_RELAY_URL,
    }
    conn = None
    try:
        conn = sql_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        result["sql_connected"] = True
        cur.close()
    except Exception as exc:
        result["sql_error"] = str(exc)
    finally:
        if conn is not None:
            conn.close()
    return jsonify(result)


@app.get("/api/events")
def api_events():
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100
    limit = max(1, min(limit, 200))

    conn = None
    try:
        conn = sql_connection()
        cur = conn.cursor()
        # Table/column names match the table created by tracking.py. Limit is clamped
        # to a small integer above; no user value is interpolated into SQL identifiers.
        cur.execute(
            f"""
            SELECT TOP ({limit})
                id, event_start, last_detected_at, clip_saved_at,
                video_filename, video_path, video_duration_seconds,
                total_frames, detected_frames
            FROM [{DB_SCHEMA}].[{DB_TABLE}]
            ORDER BY id DESC
            """
        )
        columns = [column[0] for column in cur.description]
        events = []
        for row in cur.fetchall():
            item = {key: json_value(value) for key, value in zip(columns, row)}
            # DB values may be a basename or a Windows absolute path. Normalize both
            # slash styles, but only serve a basename from RECORDING_DIR.
            raw_filename = str(item.get("video_filename") or "").strip()
            raw_path = str(item.get("video_path") or "").strip()
            filename = ntpath.basename(raw_filename.replace("/", "\\")) or ntpath.basename(raw_path.replace("/", "\\"))
            filename = Path(filename).name
            local_file = RECORDING_DIR / filename if filename else None
            item["video_filename"] = filename or raw_filename or raw_path
            item["video_url"] = url_for("recording_file", filename=filename) if filename else None
            item["video_exists"] = bool(local_file and local_file.is_file())
            item["video_size_bytes"] = local_file.stat().st_size if local_file and local_file.is_file() else 0
            events.append(item)

        cur.execute(f"SELECT COUNT_BIG(*) FROM [{DB_SCHEMA}].[{DB_TABLE}]")
        total = int(cur.fetchone()[0])
        cur.close()
        return jsonify({"ok": True, "total": total, "events": events})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "events": [], "total": 0}), 503
    finally:
        if conn is not None:
            conn.close()


def _ffmpeg_executable() -> str | None:
    """Prefer imageio-ffmpeg's bundled executable; fall back to system FFmpeg."""
    try:
        import imageio_ffmpeg
        executable = imageio_ffmpeg.get_ffmpeg_exe()
        if executable and Path(executable).is_file():
            return executable
    except Exception:
        pass
    return shutil.which("ffmpeg")


def _browser_compatible_copy(source: Path) -> Path:
    """Create a cached H.264/yuv420p copy suitable for HTML5 video browsers.

    OpenCV's common `mp4v` recordings can play in desktop media players but may not
    decode in Chrome/Edge. Conversion happens only when the user requests playback,
    never in tracking.py's camera/YOLO/recording loop.
    """
    WEB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = WEB_CACHE_DIR / f"{source.stem}_web.mp4"
    try:
        if cached.is_file() and cached.stat().st_size > 0 and cached.stat().st_mtime >= source.stat().st_mtime:
            return cached
    except OSError:
        pass

    with _TRANSCODE_LOCK:
        try:
            if cached.is_file() and cached.stat().st_size > 0 and cached.stat().st_mtime >= source.stat().st_mtime:
                return cached
        except OSError:
            pass

        ffmpeg = _ffmpeg_executable()
        if not ffmpeg:
            raise RuntimeError(
                "Không tìm thấy FFmpeg. Hãy cài thư viện bằng: "
                "python -m pip install -r requirements.txt"
            )

        temporary = WEB_CACHE_DIR / f"{source.stem}_web.tmp.mp4"
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass

        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-map", "0:v:0", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temporary),
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=900,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError("Chuyển đổi video quá thời gian chờ (15 phút).") from exc

        if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            detail = (result.stderr or "FFmpeg không tạo được file MP4 tương thích.").strip()
            raise RuntimeError(detail[-1200:])

        os.replace(temporary, cached)
        return cached


@app.get("/recordings/<path:filename>")
def recording_file(filename: str):
    # Never allow directory traversal. Only serve MP4 files inside RECORDING_DIR.
    safe_name = ntpath.basename(filename.replace("/", "\\"))
    if not safe_name or Path(safe_name).suffix.lower() != ".mp4":
        abort(404)
    source = RECORDING_DIR / safe_name
    if not source.is_file():
        abort(404, description=f"Không tìm thấy video: {safe_name}")

    try:
        # First playback may create one compatible cached copy. This work is in the
        # Flask request, separate from the camera tracking process.
        playable = _browser_compatible_copy(source)
    except Exception as exc:
        app.logger.exception("Cannot prepare browser-compatible video %s", source)
        return Response(
            "Không thể chuẩn bị video để phát trên web. " + str(exc),
            status=500,
            mimetype="text/plain; charset=utf-8",
        )

    response = send_file(
        playable, mimetype="video/mp4", as_attachment=False,
        download_name=safe_name, conditional=True, etag=True,
        last_modified=playable.stat().st_mtime,
    )
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


if __name__ == "__main__":
    print("=" * 56, flush=True)
    print("ESP32-CAM WEB DASHBOARD", flush=True)
    print(f"SQL Server : {SQLSERVER_SERVER}/{DB_NAME}", flush=True)
    print(f"Recordings : {RECORDING_DIR}", flush=True)
    print(f"Camera URL : {CAMERA_STREAM_URL}", flush=True)
    print(f"Tracker relay: {TRACKING_RELAY_URL}", flush=True)
    print("Open       : http://127.0.0.1:5000", flush=True)
    print("Live proxy : http://127.0.0.1:5000/camera.mjpeg", flush=True)
    print("Note       : Run tracking.py first. Dashboard shares its frames; no second ESP32-CAM stream.", flush=True)
    print("=" * 56, flush=True)
    # Debug off; threaded supports requests for the dashboard and MP4 playback.
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
