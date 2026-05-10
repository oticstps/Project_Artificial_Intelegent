
# halusigenia

import os
import time
import cv2
import math
import sqlite3
import traceback
import subprocess
from datetime import datetime

import numpy as np
import paho.mqtt.client as mqtt
from imutils.video import VideoStream
from ultralytics import YOLO


# =========================================================
# PATH / DATABASE CONFIG
# =========================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "judgment_history.db")
BUTTON_RESET_PATH = os.path.join(SCRIPT_DIR, "button_reset.py")
MAX_HISTORY_DISPLAY = 30
HISTORY_REFRESH_INTERVAL = 2.0


# =========================================================
# MQTT / CAMERA CONFIG
# =========================================================
MQTT_BROKER = "10.42.0.1"
MQTT_PORT = 1883
MQTT_TOPIC_PUB = "11220223_core_nais_result"
MQTT_TOPIC_PUB_INSERT = "11220223_core_nais_insert"
MQTT_TOPIC_SUB = "11220223_core_nais_judg"

USE_USB_CAMERA = False
CAMERA_INDEX = 0

RTSP_BASE_URL = "rtsp://admin:pt_otics1*@192.168.1.108:554"
COMMON_PATHS = ["/cam/realmonitor?channel=1&subtype=0"]

MEDIA_FOLDER = os.path.join(SCRIPT_DIR, "media")
OK_FOLDER = os.path.join(MEDIA_FOLDER, "OK")
NG_FOLDER = os.path.join(MEDIA_FOLDER, "NG")
MODEL_PATH = "/home/otics/on/iaa29.pt"


# =========================================================
# TIMING CONFIG
# =========================================================
NG_SOUND_REPEAT_INTERVAL = 8
MISSING_HLA_SOUND_START_DELAY = 2.5
MISSING_HLA_SOUND_INTERVAL = 8
POST_OK_INTERLOCK_DELAY = 40
DANGAE_SOUND_DELAY = 5
MISMATCH_SOUND_DELAY = 5
MISMATCH_SOUND_REPEAT_INTERVAL = 5


# =========================================================
# NIGHT MODE / REST MODE CONFIG
# =========================================================
# Dahua night mode biasanya membuat frame menjadi hitam-putih / grayscale.
# Saat kondisi ini aktif, sound alarm dimatikan agar YOLO tidak memicu alarm palsu.
ENABLE_NIGHT_MODE_SILENCE = True
SILENCE_ALL_SOUND_IN_NIGHT_MODE = True
SILENCE_MISMATCH_SOUND_IN_NIGHT_MODE = True

# Waktu konfirmasi agar tidak mudah aktif karena flicker sesaat.
NIGHT_MODE_CONFIRM_SECONDS = 2.0
NIGHT_MODE_RELEASE_SECONDS = 3.0

# Tuning threshold. Jika terlalu sensitif, kecilkan nilai saturation/color_diff.
# Jika mode malam belum terdeteksi, naikkan sedikit nilai threshold.
NIGHT_MODE_SATURATION_THRESHOLD = 18.0
NIGHT_MODE_COLOR_DIFF_THRESHOLD = 10.0
NIGHT_MODE_BRIGHTNESS_THRESHOLD = 35.0
NIGHT_MODE_DEBUG_INTERVAL = 5.0


# =========================================================
# MODEL / DETECTION CONFIG
# =========================================================
CLASS_NAMES = [
    'hla',
    'hla_terlentang',
    'hla_terbalik',
    'k_80',
    'k_88',
    'k_108',
    'b_80',
    'b_88',
    'b_108'
]

AREA_PERCENTAGE_HEIGHT = 0.8
AREA_MARGIN_HEIGHT = (1 - AREA_PERCENTAGE_HEIGHT) / 2
AREA_PERCENTAGE_WIDTH = 0.5
AREA_MARGIN_WIDTH = (1 - AREA_PERCENTAGE_WIDTH) / 2


# =========================================================
# MQTT CLIENT
# =========================================================
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()


# =========================================================
# GLOBAL STATE
# =========================================================
total_hla = None
active_part = "None"

condition_button = 0
status_text = "STANDBY"
status_color = (255, 255, 255)
last_status = "READY"

oke_counter = 0
ng_counter = 0
alarm_counter = 0

capture_history = []
last_capture_time = 0
capture_cooldown = 60
last_history_refresh_time = 0

parsed_data = None
current_program_date = None

# Mismatch part-box
mismatch_active = False
mismatch_pending_since = None
last_mismatch_sound_time = 0

# Judgment NG latch -> sound 6 sampai reset
judgment_ng_alarm_active = False
last_judgment_ng_sound_time = 0

# Interlock state
interlock_active = False
interlock_reset_block = False

# Countdown sesudah judgment OK sebelum interlock boleh aktif lagi
post_ok_countdown_active = False
post_ok_countdown_end_time = 0

# Alarm HLA hilang saat sedang interlock -> sound 5 lebih lambat
missing_hla_alarm_active = False
missing_hla_pending_since = None
last_missing_hla_sound_time = 0

# Delay sound perubahan dangae
part_sound_candidate = None
part_sound_candidate_since = 0
last_announced_part = None

# Night mode / silent mode state
night_mode_active = False
night_mode_candidate_since = None
night_mode_clear_since = None
night_mode_reason = ""
night_mode_metrics = {
    "brightness": 0.0,
    "saturation": 0.0,
    "color_diff": 0.0,
    "grayscale_like": False,
    "too_dark": False,
}
last_night_mode_log_time = 0


# =========================================================
# DATABASE FUNCTIONS
# =========================================================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS judgment_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                program_date TEXT NOT NULL,
                hla_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                image_path TEXT,
                active_part TEXT,
                expected_hla INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def insert_history_record(timestamp_text, program_date_text, hla_count, status, image_path, active_part_text, expected_hla):
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO judgment_history (
                timestamp, program_date, hla_count, status, image_path, active_part, expected_hla
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp_text,
                program_date_text,
                int(hla_count),
                status,
                image_path,
                active_part_text,
                expected_hla if expected_hla is not None else 0,
            ),
        )
        conn.commit()


def load_recent_history(limit=MAX_HISTORY_DISPLAY):
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, timestamp, program_date, hla_count, status, image_path, active_part, expected_hla
            FROM judgment_history
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    rows = list(reversed(rows))
    return [
        {
            "ID": row["id"],
            "Timestamp": row["timestamp"],
            "ProgramDate": row["program_date"],
            "Total HLA": row["hla_count"],
            "Status": row["status"],
            "ImagePath": row["image_path"] or "",
            "ActivePart": row["active_part"] or "None",
            "ExpectedHLA": row["expected_hla"],
        }
        for row in rows
    ]


def count_ok_records(program_date_text):
    if not program_date_text:
        return 0
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total_ok FROM judgment_history WHERE program_date = ? AND status = 'OKE'",
            (program_date_text,),
        ).fetchone()
    return int(row["total_ok"]) if row else 0


def get_latest_program_date_from_db():
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT program_date FROM judgment_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row["program_date"] if row else None


def sync_history_from_db(force=False):
    global capture_history, last_history_refresh_time, oke_counter, current_program_date

    now = time.time()
    if (not force) and ((now - last_history_refresh_time) < HISTORY_REFRESH_INTERVAL):
        return

    capture_history = load_recent_history(MAX_HISTORY_DISPLAY)

    if current_program_date:
        oke_counter = count_ok_records(current_program_date)
    else:
        latest_date = get_latest_program_date_from_db()
        if latest_date:
            current_program_date = latest_date
            oke_counter = count_ok_records(current_program_date)
        else:
            oke_counter = 0

    last_history_refresh_time = now


# =========================================================
# HELPER FUNCTIONS
# =========================================================
def play_sound(track_number: int, force: bool = False):
    """Kirim perintah suara ke ESP32 lewat MQTT.

    Jika night mode aktif, sound ditahan supaya alarm palsu tidak berbunyi
    saat CCTV Dahua berubah ke tampilan hitam-putih / mode malam.
    """
    global last_night_mode_log_time

    if ENABLE_NIGHT_MODE_SILENCE and night_mode_active and not force:
        block_sound = SILENCE_ALL_SOUND_IN_NIGHT_MODE or (
            SILENCE_MISMATCH_SOUND_IN_NIGHT_MODE and track_number == 4
        )

        if block_sound:
            now = time.time()
            if (now - last_night_mode_log_time) >= NIGHT_MODE_DEBUG_INTERVAL:
                print(
                    f"[SOUND-SKIP] Night mode aktif -> sound {track_number} diblok. "
                    f"Reason={night_mode_reason}, "
                    f"brightness={night_mode_metrics.get('brightness', 0):.1f}, "
                    f"saturation={night_mode_metrics.get('saturation', 0):.1f}, "
                    f"color_diff={night_mode_metrics.get('color_diff', 0):.1f}"
                )
                last_night_mode_log_time = now
            return False

    try:
        client.publish(MQTT_TOPIC_SUB, f"test_sound,{track_number}")
        print(f"[SOUND] test_sound,{track_number} sent")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send sound command: {e}")
        return False


def parse_message(message: str):
    """Parse data_judg atau data_reset."""
    if message.startswith("data_judg,"):
        data_string = message[len("data_judg,"):].rstrip('#')
        data_values = data_string.split(',')
        return [int(value) for value in data_values if value != ""]

    if message.startswith("data_reset,"):
        data_string = message[len("data_reset,"):].rstrip('#')
        data_values = data_string.split(',')
        return [int(value) for value in data_values if value != ""]

    return None


def get_date_folder_name(current_parsed_data):
    """Folder tanggal format year_month_day dari data program, bukan dari PC."""
    if current_parsed_data and len(current_parsed_data) >= 6:
        year = current_parsed_data[3]
        month = current_parsed_data[4]
        day = current_parsed_data[5]
        return f"{year}_{month:02d}_{day:02d}"

    if current_program_date:
        return current_program_date

    latest_date = get_latest_program_date_from_db()
    return latest_date if latest_date else "NO_PROGRAM_DATE"


def update_program_date_from_parsed(current_parsed_data):
    global current_program_date, oke_counter

    new_program_date = get_date_folder_name(current_parsed_data)
    if new_program_date != current_program_date:
        current_program_date = new_program_date
        oke_counter = count_ok_records(current_program_date)
        print(f"[INFO] Program date updated from parsed data: {current_program_date}")


def reset_conditions():
    """Reset kondisi sistem. History database tidak dihapus."""
    global alarm_counter, parsed_data
    global mismatch_active, mismatch_pending_since
    global judgment_ng_alarm_active, last_judgment_ng_sound_time
    global interlock_active, interlock_reset_block
    global missing_hla_alarm_active, missing_hla_pending_since, last_missing_hla_sound_time
    global post_ok_countdown_active, post_ok_countdown_end_time
    global part_sound_candidate, part_sound_candidate_since, last_announced_part
    global condition_button, status_text, status_color
    global active_part, total_hla
    global night_mode_candidate_since, night_mode_clear_since, night_mode_reason, last_night_mode_log_time

    alarm_counter = 0
    parsed_data = None

    mismatch_active = False
    mismatch_pending_since = None

    judgment_ng_alarm_active = False
    last_judgment_ng_sound_time = 0

    interlock_active = False
    missing_hla_alarm_active = False
    missing_hla_pending_since = None
    last_missing_hla_sound_time = 0

    post_ok_countdown_active = False
    post_ok_countdown_end_time = 0

    part_sound_candidate = None
    part_sound_candidate_since = 0
    last_announced_part = None

    night_mode_candidate_since = None
    night_mode_clear_since = None
    night_mode_reason = ""
    last_night_mode_log_time = 0

    interlock_reset_block = True

    condition_button = 0
    status_text = "STANDBY"
    status_color = (255, 255, 255)

    active_part = "None"
    total_hla = None

    sync_history_from_db(force=True)
    print("[INFO] Conditions reset. Database history retained.")


def define_detection_area(frame_shape):
    """Area deteksi di tengah frame."""
    height, width = frame_shape[:2]

    x_margin = int(width * AREA_MARGIN_WIDTH)
    y_margin = int(height * AREA_MARGIN_HEIGHT)

    x_start = x_margin
    y_start = y_margin
    x_end = width - x_margin
    y_end = height - y_margin

    return (x_start, y_start, x_end, y_end)


def is_in_detection_area(bbox, detection_area):
    """Cek center bbox ada di area deteksi."""
    x1, y1, x2, y2 = bbox[:4]

    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2

    area_x_start, area_y_start, area_x_end, area_y_end = detection_area

    return (
        area_x_start <= center_x <= area_x_end and
        area_y_start <= center_y <= area_y_end
    )


def analyze_night_mode_frame(frame):
    """Deteksi mode malam dari karakter frame CCTV.

    Logika utama:
    1. Frame hitam-putih / grayscale memiliki saturasi rendah.
    2. Selisih antar channel BGR kecil karena warna hampir sama.
    3. Frame yang sangat gelap juga dianggap mode malam / istirahat.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    saturation_mean = float(np.mean(hsv[:, :, 1]))
    brightness_mean = float(np.mean(hsv[:, :, 2]))

    b, g, r = cv2.split(frame)
    b = b.astype(np.int16)
    g = g.astype(np.int16)
    r = r.astype(np.int16)

    color_diff_mean = float(
        np.mean(
            (np.abs(b - g) + np.abs(g - r) + np.abs(b - r)) / 3.0
        )
    )

    grayscale_like = (
        saturation_mean <= NIGHT_MODE_SATURATION_THRESHOLD
        and color_diff_mean <= NIGHT_MODE_COLOR_DIFF_THRESHOLD
    )
    too_dark = brightness_mean <= NIGHT_MODE_BRIGHTNESS_THRESHOLD

    is_night_raw = grayscale_like or too_dark

    if grayscale_like and too_dark:
        reason = "grayscale_and_dark"
    elif grayscale_like:
        reason = "grayscale_like"
    elif too_dark:
        reason = "too_dark"
    else:
        reason = "normal_color"

    metrics = {
        "brightness": brightness_mean,
        "saturation": saturation_mean,
        "color_diff": color_diff_mean,
        "grayscale_like": grayscale_like,
        "too_dark": too_dark,
    }

    return is_night_raw, reason, metrics


def update_night_mode_state(frame, current_time):
    """Aktifkan silent mode jika frame konsisten menunjukkan mode malam."""
    global night_mode_active, night_mode_candidate_since, night_mode_clear_since
    global night_mode_reason, night_mode_metrics
    global mismatch_active, mismatch_pending_since, last_mismatch_sound_time
    global missing_hla_alarm_active, missing_hla_pending_since, last_missing_hla_sound_time
    global part_sound_candidate, part_sound_candidate_since, last_announced_part

    is_night_raw, reason, metrics = analyze_night_mode_frame(frame)
    night_mode_reason = reason
    night_mode_metrics = metrics

    if is_night_raw:
        night_mode_clear_since = None

        if night_mode_candidate_since is None:
            night_mode_candidate_since = current_time

        if (
            not night_mode_active
            and (current_time - night_mode_candidate_since) >= NIGHT_MODE_CONFIRM_SECONDS
        ):
            night_mode_active = True

            # Reset alarm yang rentan false positive saat mode malam.
            mismatch_active = False
            mismatch_pending_since = None
            last_mismatch_sound_time = 0

            missing_hla_alarm_active = False
            missing_hla_pending_since = None
            last_missing_hla_sound_time = 0

            part_sound_candidate = None
            part_sound_candidate_since = 0
            last_announced_part = None

            print(
                f"[INFO] Night mode aktif -> sound dimatikan. "
                f"Reason={reason}, brightness={metrics['brightness']:.1f}, "
                f"saturation={metrics['saturation']:.1f}, color_diff={metrics['color_diff']:.1f}"
            )
    else:
        night_mode_candidate_since = None

        if night_mode_active:
            if night_mode_clear_since is None:
                night_mode_clear_since = current_time

            if (current_time - night_mode_clear_since) >= NIGHT_MODE_RELEASE_SECONDS:
                night_mode_active = False
                night_mode_clear_since = None
                part_sound_candidate = None
                part_sound_candidate_since = current_time
                last_announced_part = None

                print(
                    f"[INFO] Night mode nonaktif -> sound normal. "
                    f"brightness={metrics['brightness']:.1f}, "
                    f"saturation={metrics['saturation']:.1f}, color_diff={metrics['color_diff']:.1f}"
                )
        else:
            night_mode_clear_since = None

    return night_mode_active


def on_connect(client_instance, userdata, flags, rc, properties=None):
    if rc == 0:
        print("[INFO] Connected to broker")
        client_instance.subscribe(MQTT_TOPIC_SUB)
        print(f"[INFO] Subscribed to {MQTT_TOPIC_SUB}")
    else:
        print(f"[ERROR] Connection failed with code {rc}")


def on_message(client_instance, userdata, msg):
    global parsed_data

    try:
        message_content = msg.payload.decode('utf-8')
        print(f"[MQTT] Received: {message_content}")

        parsed = parse_message(message_content)
        if parsed is not None:
            parsed_data = parsed
            print("[MQTT] Parsed Data:", parsed_data)

            if message_content.startswith("data_judg,"):
                update_program_date_from_parsed(parsed_data)

            if message_content.startswith("data_reset,"):
                reset_conditions()

    except Exception as e:
        print(f"[ERROR] on_message: {e}")
        traceback.print_exc()


def test_stream(path):
    """Test CCTV stream jika USE_USB_CAMERA=False."""
    rtsp_url = RTSP_BASE_URL + path
    vs = None
    try:
        vs = VideoStream(rtsp_url).start()
        time.sleep(2.0)
        frame = vs.read()
        return frame is not None
    except Exception:
        return False
    finally:
        try:
            if vs is not None:
                vs.stop()
        except Exception:
            pass


def capture_image(original_frame, timestamp_text, result_status, current_parsed_data, detection_results):
    """Simpan gambar capture dengan bounding box."""
    class_colors = {
        'hla': (255, 0, 0),
        'hla_terlentang': (0, 0, 255),
        'hla_terbalik': (0, 0, 200),
        'k_80': (0, 255, 0),
        'k_88': (0, 165, 255),
        'k_108': (128, 0, 128),
        'b_80': (255, 255, 0),
        'b_88': (255, 0, 255),
        'b_108': (192, 192, 192)
    }

    date_folder_name = get_date_folder_name(current_parsed_data)
    base_save_folder = OK_FOLDER if result_status == "OK" else NG_FOLDER
    date_save_folder = os.path.join(base_save_folder, date_folder_name)
    os.makedirs(date_save_folder, exist_ok=True)

    image_save_path = os.path.join(date_save_folder, f"hla_capture_{timestamp_text}.jpg")
    print(f"[INFO] Capturing image: {image_save_path}")

    frame_to_save = original_frame.copy()

    if detection_results is not None and hasattr(detection_results[0], 'boxes'):
        boxes = detection_results[0].boxes
        for box in boxes:
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])

            if conf > 0.5 and cls_id < len(CLASS_NAMES):
                class_name = CLASS_NAMES[cls_id]
                color = class_colors.get(class_name, (255, 255, 255))
                cv2.rectangle(frame_to_save, (x1, y1), (x2, y2), color, 2)

    cv2.imwrite(image_save_path, frame_to_save)
    print(f"[INFO] Image saved: {image_save_path}")
    return image_save_path


def save_and_refresh_history(hla_count, timestamp_text, program_date_text, status, image_path, active_part_text, expected_hla):
    insert_history_record(
        timestamp_text=timestamp_text,
        program_date_text=program_date_text,
        hla_count=hla_count,
        status=status,
        image_path=image_path,
        active_part_text=active_part_text,
        expected_hla=expected_hla,
    )
    sync_history_from_db(force=True)


def start_camera():
    """Start camera sesuai config."""
    if USE_USB_CAMERA:
        print(f"[INFO] Starting USB camera index {CAMERA_INDEX}")
        vs = VideoStream(src=CAMERA_INDEX).start()
        time.sleep(2.0)

        test_frame = vs.read()
        if test_frame is None:
            raise RuntimeError(f"USB camera index {CAMERA_INDEX} not detected")

        return vs

    rtsp_url = None
    for path in COMMON_PATHS:
        if test_stream(path):
            rtsp_url = RTSP_BASE_URL + path
            print(f"[INFO] Valid CCTV stream found: {rtsp_url}")
            break

    if rtsp_url is None:
        raise RuntimeError("No valid CCTV stream found")

    vs = VideoStream(rtsp_url).start()
    time.sleep(2.0)

    test_frame = vs.read()
    if test_frame is None:
        raise RuntimeError("CCTV stream not detected")

    return vs


# =========================================================
# MAIN
# =========================================================
def main():
    global total_hla, active_part
    global condition_button, status_text, status_color, last_status
    global oke_counter, ng_counter, alarm_counter
    global last_capture_time
    global mismatch_active, mismatch_pending_since, last_mismatch_sound_time
    global parsed_data
    global judgment_ng_alarm_active, last_judgment_ng_sound_time
    global interlock_active, interlock_reset_block
    global missing_hla_alarm_active, missing_hla_pending_since, last_missing_hla_sound_time
    global post_ok_countdown_active, post_ok_countdown_end_time
    global part_sound_candidate, part_sound_candidate_since, last_announced_part
    global current_program_date
    global night_mode_active, night_mode_reason, night_mode_metrics

    camera_stream = None

    try:
        init_database()
        sync_history_from_db(force=True)

        # Start helper UI reset jika ada
        try:
            if os.path.exists(BUTTON_RESET_PATH):
                subprocess.Popen(["python3", BUTTON_RESET_PATH])
                print(f"[INFO] button_reset.py started: {BUTTON_RESET_PATH}")
            else:
                print(f"[WARNING] button_reset.py not found: {BUTTON_RESET_PATH}")
        except Exception as e:
            print(f"[WARNING] button_reset.py failed to start: {e}")

        # MQTT setup
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()

        # Load model
        model = YOLO(MODEL_PATH)
        print("[INFO] YOLO model loaded")

        # Folder setup
        os.makedirs(OK_FOLDER, exist_ok=True)
        os.makedirs(NG_FOLDER, exist_ok=True)

        # Camera setup
        camera_stream = start_camera()

        print("[INFO] Main loop started")

        while True:
            time.sleep(0.1)
            current_time = time.time()
            sync_history_from_db(force=False)

            frame = camera_stream.read()
            if frame is None:
                print("[WARNING] Frame is None")
                continue

            original_frame = frame.copy()
            night_mode_now = update_night_mode_state(original_frame, current_time)
            detection_area = define_detection_area(frame.shape)

            try:
                results = model(frame, conf=0.5, verbose=False)
                detected_objects = results[0].boxes.data.cpu().numpy()

                class_counts = {class_name: 0 for class_name in CLASS_NAMES}

                for obj in detected_objects:
                    cls_id = int(obj[5])
                    if cls_id < len(CLASS_NAMES):
                        class_name = CLASS_NAMES[cls_id]
                        if class_name == 'hla':
                            if is_in_detection_area(obj, detection_area):
                                class_counts[class_name] += 1
                        else:
                            class_counts[class_name] += 1

                hla_count = class_counts['hla']
                hla_terlentang_count = class_counts['hla_terlentang']
                hla_terbalik_count = class_counts['hla_terbalik']
                k_80_count = class_counts['k_80']
                k_88_count = class_counts['k_88']
                k_108_count = class_counts['k_108']
                b_80_count = class_counts['b_80']
                b_88_count = class_counts['b_88']
                b_108_count = class_counts['b_108']

                # Rearm interlock hanya jika count sudah keluar dari 44
                if hla_count != 44:
                    interlock_reset_block = False

                # Countdown sesudah judgment OK
                if post_ok_countdown_active and current_time >= post_ok_countdown_end_time:
                    post_ok_countdown_active = False
                    print("[INFO] Post-OK countdown finished -> interlock can arm again")

                # Tentukan active part
                new_active_part = "None"
                new_total_hla = None

                if night_mode_active:
                    # Saat CCTV mode malam, hasil YOLO tidak dipakai untuk memilih part.
                    # Ini mencegah trigger Dangae palsu saat frame hitam-putih.
                    new_active_part = "None"
                    new_total_hla = None
                elif k_108_count > 0:
                    new_active_part = "ADM Export"
                    new_total_hla = 108
                elif k_88_count > 0:
                    new_active_part = "tmmin-1L"
                    new_total_hla = 88
                elif k_80_count > 0:
                    new_active_part = "tmmin-1E"
                    new_total_hla = 80

                # Delay sound perubahan dangae selama 5 detik
                if night_mode_active:
                    part_sound_candidate = None
                    part_sound_candidate_since = current_time
                    last_announced_part = None
                elif new_active_part != part_sound_candidate:
                    part_sound_candidate = new_active_part
                    part_sound_candidate_since = current_time
                elif (
                    new_active_part != "None" and
                    new_active_part != last_announced_part and
                    (current_time - part_sound_candidate_since) >= DANGAE_SOUND_DELAY
                ):
                    if new_active_part == "tmmin-1E":
                        play_sound(7)
                    elif new_active_part == "tmmin-1L":
                        play_sound(8)
                    elif new_active_part == "ADM Export":
                        play_sound(9)

                    last_announced_part = new_active_part
                    print(f"[INFO] Dangae sound confirmed after {DANGAE_SOUND_DELAY}s: {new_active_part}")
                elif new_active_part == "None":
                    last_announced_part = None

                active_part = new_active_part
                total_hla = new_total_hla

                # Mismatch part-box
                mismatch_now = False
                mismatch_notification = ""

                if night_mode_active:
                    mismatch_now = False
                    mismatch_notification = ""
                    mismatch_active = False
                    mismatch_pending_since = None
                elif hla_count >= 1:
                    if (k_80_count > 0 and b_80_count == 0) or \
                       (k_88_count > 0 and b_88_count == 0) or \
                       (k_108_count > 0 and b_108_count == 0):
                        mismatch_notification = "Dangae Tidak Sesuai!"
                        mismatch_now = True
                    elif (b_80_count > 0 and k_80_count == 0) or \
                         (b_88_count > 0 and k_88_count == 0) or \
                         (b_108_count > 0 and k_108_count == 0):
                        mismatch_notification = "Dangae Tidak Sesuai!"
                        mismatch_now = True

                if mismatch_now:
                    if mismatch_pending_since is None:
                        mismatch_pending_since = current_time

                    mismatch_duration = current_time - mismatch_pending_since
                    if mismatch_duration >= MISMATCH_SOUND_DELAY:
                        if not mismatch_active:
                            play_sound(4)
                            last_mismatch_sound_time = current_time
                            mismatch_active = True
                            print("[INFO] Mismatch persisted 5s -> sound 4 ON")
                        elif (current_time - last_mismatch_sound_time) >= MISMATCH_SOUND_REPEAT_INTERVAL:
                            play_sound(4)
                            last_mismatch_sound_time = current_time
                    else:
                        mismatch_active = False
                else:
                    if mismatch_active:
                        print("[INFO] Mismatch cleared -> sound 4 OFF")
                    mismatch_active = False
                    mismatch_pending_since = None

                # Trigger interlock saat qty HLA = 44
                if (
                    (not judgment_ng_alarm_active)
                    and (not interlock_active)
                    and (not interlock_reset_block)
                    and (not post_ok_countdown_active)
                    and hla_count == 44
                ):
                    interlock_active = True
                    missing_hla_alarm_active = False
                    missing_hla_pending_since = None
                    condition_button = 1
                    status_text = "JUDGMENT: INTERLOCK"
                    status_color = (0, 255, 255)
                    print("[INFO] Interlock activated")

                # Saat interlock dan HLA hilang, sound 0005 lebih lambat
                if interlock_active and (not judgment_ng_alarm_active):
                    if hla_count == 0:
                        condition_button = 1
                        status_text = "PROSES BELUM SELESAI"
                        status_color = (0, 255, 255)

                        if missing_hla_pending_since is None:
                            missing_hla_pending_since = current_time

                        if not missing_hla_alarm_active:
                            if (current_time - missing_hla_pending_since) >= MISSING_HLA_SOUND_START_DELAY:
                                play_sound(5)
                                last_missing_hla_sound_time = current_time
                                missing_hla_alarm_active = True
                                print("[INFO] HLA lost during interlock -> sound 5 ON")
                        else:
                            if (current_time - last_missing_hla_sound_time) >= MISSING_HLA_SOUND_INTERVAL:
                                play_sound(5)
                                last_missing_hla_sound_time = current_time
                    else:
                        if missing_hla_alarm_active:
                            print("[INFO] HLA detected again -> sound 5 OFF")
                        missing_hla_alarm_active = False
                        missing_hla_pending_since = None

                # Judgment process
                if total_hla is not None and parsed_data is not None and len(parsed_data) > 1 and parsed_data[1] == 1:
                    update_program_date_from_parsed(parsed_data)
                    program_date_text = get_date_folder_name(parsed_data)
                    timestamp_text = (
                        f"{parsed_data[3]:04d}{parsed_data[4]:02d}{parsed_data[5]:02d}_"
                        f"{parsed_data[6]:02d}{parsed_data[7]:02d}{parsed_data[8]:02d}"
                    )

                    if hla_terlentang_count > 0 or hla_terbalik_count > 0:
                        client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,#")

                    # OK
                    if hla_count == total_hla:
                        client.publish(MQTT_TOPIC_PUB, "data_result,1,1,1,1,1,1,1,1,1,#")
                        play_sound(1)

                        interlock_active = False
                        missing_hla_alarm_active = False
                        missing_hla_pending_since = None
                        post_ok_countdown_active = True
                        post_ok_countdown_end_time = current_time + POST_OK_INTERLOCK_DELAY
                        interlock_reset_block = False
                        condition_button = 0
                        status_text = "STANDBY"
                        status_color = (255, 255, 255)

                        if (time.time() - last_capture_time) >= capture_cooldown:
                            status = "OKE"
                            client.publish(MQTT_TOPIC_PUB_INSERT, f"data_oke,1,1,1,{oke_counter + 1},#")

                            image_path = capture_image(original_frame, timestamp_text, "OK", parsed_data, results)
                            save_and_refresh_history(hla_count, timestamp_text, program_date_text, status, image_path, active_part, total_hla)
                            last_capture_time = time.time()

                        time.sleep(1)

                    # NG
                    else:
                        client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,#")

                        alarm_counter = 1
                        status = "NG"
                        ng_counter += 1

                        if not judgment_ng_alarm_active:
                            play_sound(6)
                            last_judgment_ng_sound_time = current_time

                        judgment_ng_alarm_active = True
                        interlock_active = False
                        missing_hla_alarm_active = False
                        missing_hla_pending_since = None
                        condition_button = 0
                        status_text = "JUDGMENT: NG COUNT"
                        status_color = (0, 0, 255)

                        image_path = capture_image(original_frame, timestamp_text, "NG", parsed_data, results)
                        save_and_refresh_history(hla_count, timestamp_text, program_date_text, status, image_path, active_part, total_hla)
                        time.sleep(1)

                    parsed_data[1] = 0

                # Latched sound handler
                if judgment_ng_alarm_active:
                    status_text = "JUDGMENT: NG COUNT"
                    status_color = (0, 0, 255)
                    if (current_time - last_judgment_ng_sound_time) >= NG_SOUND_REPEAT_INTERVAL:
                        play_sound(6)
                        last_judgment_ng_sound_time = current_time

                elif missing_hla_alarm_active:
                    status_text = "PROSES BELUM SELESAI"
                    status_color = (0, 255, 255)
                    condition_button = 1

                elif interlock_active:
                    status_text = "JUDGMENT: INTERLOCK"
                    status_color = (0, 255, 255)
                    condition_button = 1

                if interlock_active and hla_count == 0:
                    client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,#")
                    indicator_text = "PROSES BELUM SELESAI"
                    indicator_color = (0, 255, 255)
                    cv2.rectangle(frame, (frame.shape[1] - 520, 20), (frame.shape[1] - 20, 90), indicator_color, -1)
                    cv2.putText(frame, indicator_text, (frame.shape[1] - 510, 80),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 4)

                if alarm_counter == 1:
                    client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,#")
                    time.sleep(1)

                # Display
                annotated_frame = results[0].plot(line_width=1, labels=True, conf=True)

                x_start, y_start, x_end, y_end = detection_area
                cv2.rectangle(annotated_frame, (x_start, y_start), (x_end, y_end), (0, 255, 255), 3)
                cv2.putText(annotated_frame, "DETECTION AREA", (x_start + 10, y_start + 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

                cv2.rectangle(
                    annotated_frame,
                    (0, 0),
                    (annotated_frame.shape[1] - 1, annotated_frame.shape[0] - 1),
                    (184, 132, 0),
                    20,
                )

                if night_mode_active:
                    cv2.rectangle(annotated_frame, (30, 30), (680, 105), (0, 0, 0), -1)
                    cv2.putText(
                        annotated_frame,
                        "NIGHT MODE / SOUND OFF",
                        (45, 82),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.4,
                        (0, 255, 255),
                        4,
                    )

                if mismatch_notification and mismatch_pending_since is not None and (current_time - mismatch_pending_since) >= MISMATCH_SOUND_DELAY:
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    text_size = cv2.getTextSize(mismatch_notification, font, 2, 5)[0]
                    text_x = annotated_frame.shape[1] // 2 - text_size[0] // 2
                    text_y = 150
                    cv2.rectangle(
                        annotated_frame,
                        (text_x - 20, text_y - text_size[1] - 20),
                        (text_x + text_size[0] + 20, text_y + 20),
                        (0, 0, 0),
                        -1,
                    )
                    cv2.putText(annotated_frame, mismatch_notification, (text_x, text_y),
                                font, 2, (0, 0, 255), 5)

                height, width = annotated_frame.shape[:2]
                sidebar_width = 600
                sidebar_color = (142, 112, 0)

                canvas = np.zeros((height, width + sidebar_width, 3), dtype=np.uint8)
                canvas[:, :sidebar_width] = sidebar_color
                canvas[:, sidebar_width:sidebar_width + width] = annotated_frame

                font = cv2.FONT_HERSHEY_SIMPLEX
                white_text_color = (255, 255, 255)
                red_bg_color = (0, 0, 255)
                blue_bg_color_1 = (122, 52, 0)
                green_bg_color = (0, 120, 0)

                countdown_remaining = 0
                if post_ok_countdown_active:
                    countdown_remaining = max(0, math.ceil(post_ok_countdown_end_time - current_time))

                program_date_display = current_program_date if current_program_date else "NO_PROGRAM_DATE"

                cv2.rectangle(canvas, (20, 25), (sidebar_width - 20, 105), red_bg_color, -1)
                cv2.putText(canvas, f"Total Tray: {oke_counter}", (30, 70), font, 1.25, white_text_color, 4)
                cv2.putText(canvas, f"Date: {program_date_display}", (30, 98), font, 0.65, white_text_color, 2)

                cv2.rectangle(canvas, (20, 120), (sidebar_width - 20, 190), green_bg_color, -1)
                cv2.putText(canvas, status_text, (30, 165), font, 0.9, white_text_color, 2)

                cv2.putText(canvas, f"Detection Area: {int(AREA_PERCENTAGE_WIDTH * 100)}%", (30, 220), font, 0.7, white_text_color, 2)

                alarm_info = "ALARM: NONE"
                if night_mode_active:
                    alarm_info = "NIGHT MODE: SOUND OFF"
                elif judgment_ng_alarm_active:
                    alarm_info = "ALARM: SOUND 6"
                elif missing_hla_alarm_active:
                    alarm_info = "ALARM: SOUND 5"
                elif mismatch_active:
                    alarm_info = "ALARM: SOUND 4"
                elif interlock_active:
                    alarm_info = "ALARM: INTERLOCK ON"
                elif post_ok_countdown_active:
                    alarm_info = "ALARM: COUNTDOWN OK"

                cv2.putText(canvas, alarm_info, (30, 255), font, 0.8, white_text_color, 2)
                night_metric_text = (
                    f"NIGHT: {'ON' if night_mode_active else 'OFF'} | "
                    f"V:{night_mode_metrics.get('brightness', 0):.0f} "
                    f"S:{night_mode_metrics.get('saturation', 0):.0f} "
                    f"C:{night_mode_metrics.get('color_diff', 0):.0f}"
                )
                cv2.putText(canvas, night_metric_text, (30, 285), font, 0.65, white_text_color, 2)
                cv2.putText(canvas, f"INTERLOCK BLOCK: {interlock_reset_block}", (30, 315), font, 0.7, white_text_color, 2)
                if post_ok_countdown_active:
                    cv2.putText(canvas, f"COUNTDOWN OK: {countdown_remaining} DETIK", (30, 345), font, 0.7, white_text_color, 2)
                if missing_hla_pending_since is not None and not missing_hla_alarm_active:
                    pending_left = max(0.0, MISSING_HLA_SOUND_START_DELAY - (current_time - missing_hla_pending_since))
                    cv2.putText(canvas, f"SOUND 5 DELAY: {pending_left:.1f}s", (30, 375), font, 0.7, white_text_color, 2)

                history_start_y = 410
                for idx, record in enumerate(capture_history):
                    ts = record["Timestamp"]
                    count = record["Total HLA"]
                    status = record["Status"]
                    last_status = status

                    history_text = f"{idx + 1}: {ts} | HLA: {count} | {status}"
                    text_position = (30, history_start_y + (idx * 30))
                    (text_width, text_height), _ = cv2.getTextSize(history_text, font, 0.6, 2)

                    if status == "NG":
                        cv2.rectangle(
                            canvas,
                            (text_position[0] - 5, text_position[1] - text_height - 5),
                            (text_position[0] + text_width + 5, text_position[1] + 5),
                            (0, 0, 139),
                            -1,
                        )

                    cv2.putText(canvas, history_text, text_position, font, 0.6, white_text_color, 2)

                sidebar_bottom_y = height - 100
                cv2.rectangle(canvas, (20, sidebar_bottom_y - 50), (sidebar_width - 20, sidebar_bottom_y), blue_bg_color_1, -1)
                cv2.putText(canvas, f"TRAY: {hla_count} PCS", (30, sidebar_bottom_y - 10), font, 1.5, white_text_color, 5)

                part_dangae_y = sidebar_bottom_y + 40
                part_dangae_text = f"Part Dangae: {total_hla if total_hla is not None else 'None'}"
                cv2.putText(canvas, part_dangae_text, (30, part_dangae_y), font, 1.0, white_text_color, 2)

                display_width = 1395
                display_height = 770
                h_canvas, w_canvas = canvas.shape[:2]
                scale = min(display_width / w_canvas, display_height / h_canvas)
                new_w = int(w_canvas * scale)
                new_h = int(h_canvas * scale)
                resized_canvas = cv2.resize(canvas, (new_w, new_h))

                display = np.zeros((display_height, display_width, 3), dtype=np.uint8)
                x_offset = (display_width - new_w) // 2
                y_offset = (display_height - new_h) // 2
                display[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized_canvas

                cv2.imshow("Deteksi Part HLA - Main Program", display)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("[INFO] q pressed, exit program")
                    break

                print("===================================================")
                print(f"HLA                 : {hla_count}")
                print(f"HLA Terlentang      : {hla_terlentang_count}")
                print(f"HLA Terbalik        : {hla_terbalik_count}")
                print(f"k_80 / k_88 / k_108 : {k_80_count} / {k_88_count} / {k_108_count}")
                print(f"b_80 / b_88 / b_108 : {b_80_count} / {b_88_count} / {b_108_count}")
                print(f"Active Part         : {active_part}")
                print(f"Total HLA           : {total_hla}")
                print(f"Program Date        : {current_program_date}")
                print(f"Condition Button    : {condition_button}")
                print(f"Alarm Counter       : {alarm_counter}")
                print(f"Status Text         : {status_text}")
                print(f"Parsed Data         : {parsed_data}")
                print(f"Oke Counter         : {oke_counter}")
                print(f"NG Counter          : {ng_counter}")
                print(f"Mismatch Active     : {mismatch_active}")
                print(f"Mismatch Pending    : {mismatch_pending_since}")
                print(f"NG Alarm Active     : {judgment_ng_alarm_active}")
                print(f"Interlock Active    : {interlock_active}")
                print(f"Missing HLA Alarm   : {missing_hla_alarm_active}")
                print(f"Post OK Countdown   : {post_ok_countdown_active}")
                print(f"Countdown Remaining : {countdown_remaining}")
                print(f"Last Announced Part : {last_announced_part}")
                print(f"Interlock Block     : {interlock_reset_block}")
                print(f"Night Mode Active   : {night_mode_active}")
                print(f"Night Mode Reason   : {night_mode_reason}")
                print(
                    f"Night Metrics       : "
                    f"V={night_mode_metrics.get('brightness', 0):.1f}, "
                    f"S={night_mode_metrics.get('saturation', 0):.1f}, "
                    f"C={night_mode_metrics.get('color_diff', 0):.1f}"
                )

            except Exception as e:
                print(f"[ERROR] Error in main loop: {e}")
                traceback.print_exc()
                continue

    except Exception as e:
        print(f"[ERROR] Fatal error: {e}")
        traceback.print_exc()

    finally:
        try:
            if camera_stream is not None:
                camera_stream.stop()
        except Exception as e:
            print(f"[ERROR] Stop camera: {e}")

        try:
            cv2.destroyAllWindows()
        except Exception as e:
            print(f"[ERROR] destroyAllWindows: {e}")

        try:
            client.loop_stop()
            client.disconnect()
        except Exception as e:
            print(f"[ERROR] Stop MQTT: {e}")

        print("[INFO] Program ended")


if __name__ == "__main__":
    main()
