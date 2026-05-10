
# ragnir

import os
import time
import math
import cv2
import sqlite3
import threading
import traceback
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
from PIL import Image, ImageTk
import paho.mqtt.client as mqtt
from imutils.video import VideoStream
from ultralytics import YOLO


# =========================================================
# PATH / DATABASE CONFIG
# =========================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "judgment_history.db")
MEDIA_FOLDER = os.path.join(SCRIPT_DIR, "media")
OK_FOLDER = os.path.join(MEDIA_FOLDER, "OK")
NG_FOLDER = os.path.join(MEDIA_FOLDER, "NG")
MODEL_PATH = "/home/otics/on/iaa29.pt"
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


# =========================================================
# TIMING CONFIG
# =========================================================
LOOP_DELAY = 0.08
CAPTURE_COOLDOWN = 60
NG_SOUND_REPEAT_INTERVAL = 8
MISSING_HLA_SOUND_START_DELAY = 4.0
MISSING_HLA_SOUND_INTERVAL = 10
POST_OK_INTERLOCK_DELAY = 10
DANGAE_SOUND_DELAY = 5
MISMATCH_SOUND_DELAY = 5
MISMATCH_SOUND_REPEAT_INTERVAL = 5


# =========================================================
# MODEL / DETECTION CONFIG
# =========================================================
CLASS_NAMES = [
    "hla",
    "hla_terlentang",
    "hla_terbalik",
    "k_80",
    "k_88",
    "k_108",
    "b_80",
    "b_88",
    "b_108",
]

AREA_PERCENTAGE_HEIGHT = 0.8
AREA_MARGIN_HEIGHT = (1 - AREA_PERCENTAGE_HEIGHT) / 2
AREA_PERCENTAGE_WIDTH = 0.5
AREA_MARGIN_WIDTH = (1 - AREA_PERCENTAGE_WIDTH) / 2

DISPLAY_WIDTH = 1395
DISPLAY_HEIGHT = 770
SIDEBAR_WIDTH = 600


# =========================================================
# DATABASE HELPERS
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
                int(expected_hla) if expected_hla is not None else 0,
            ),
        )
        conn.commit()


def update_history_record(record_id, timestamp_text, program_date_text, hla_count, status, image_path, active_part_text, expected_hla):
    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE judgment_history
            SET timestamp = ?,
                program_date = ?,
                hla_count = ?,
                status = ?,
                image_path = ?,
                active_part = ?,
                expected_hla = ?
            WHERE id = ?
            """,
            (
                timestamp_text,
                program_date_text,
                int(hla_count),
                status,
                image_path,
                active_part_text,
                int(expected_hla) if str(expected_hla).strip() != "" else 0,
                int(record_id),
            ),
        )
        conn.commit()


def delete_history_record(record_id):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM judgment_history WHERE id = ?", (int(record_id),))
        conn.commit()


def fetch_history_rows(program_date_filter=""):
    with get_db_connection() as conn:
        if program_date_filter.strip():
            rows = conn.execute(
                """
                SELECT id, timestamp, program_date, hla_count, status, image_path, active_part, expected_hla, created_at
                FROM judgment_history
                WHERE program_date = ?
                ORDER BY id DESC
                """,
                (program_date_filter.strip(),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, timestamp, program_date, hla_count, status, image_path, active_part, expected_hla, created_at
                FROM judgment_history
                ORDER BY id DESC
                """
            ).fetchall()
    return rows


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
            "ExpectedHLA": row["expected_hla"] or 0,
        }
        for row in rows
    ]


def count_ok_records(program_date_text):
    if not str(program_date_text).strip():
        return 0
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total_ok FROM judgment_history WHERE program_date = ? AND status = 'OKE'",
            (program_date_text.strip(),),
        ).fetchone()
    return int(row["total_ok"]) if row else 0


def get_latest_program_date_from_db():
    with get_db_connection() as conn:
        row = conn.execute("SELECT program_date FROM judgment_history ORDER BY id DESC LIMIT 1").fetchone()
    return row["program_date"] if row else None


# =========================================================
# ENGINE
# =========================================================
class HlaMonitorEngine:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self.camera_stream = None
        self.model = None
        self.mqtt_connected = False

        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            self.client = mqtt.Client()

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        self.reset_runtime_state(full_reset=True)
        self.latest_frame = self._build_placeholder_frame("Monitor belum dimulai")
        self.latest_debug_text = ""
        self.last_history_refresh_time = 0

    # ----------------------------
    # Core state
    # ----------------------------
    def reset_runtime_state(self, full_reset=False):
        with self.lock:
            self.total_hla = None
            self.active_part = "None"
            self.condition_button = 0
            self.status_text = "STANDBY"
            self.status_color = (255, 255, 255)
            self.last_status = "READY"
            self.oke_counter = 0
            self.ng_counter = 0
            self.alarm_counter = 0
            self.capture_history = []
            self.last_capture_time = 0
            self.parsed_data = None
            self.current_program_date = None

            self.mismatch_active = False
            self.mismatch_pending_since = None
            self.last_mismatch_sound_time = 0

            self.judgment_ng_alarm_active = False
            self.last_judgment_ng_sound_time = 0

            self.interlock_active = False
            self.interlock_reset_block = False

            self.post_ok_countdown_active = False
            self.post_ok_countdown_end_time = 0

            self.missing_hla_alarm_active = False
            self.missing_hla_pending_since = None
            self.last_missing_hla_sound_time = 0

            self.part_sound_candidate = None
            self.part_sound_candidate_since = 0
            self.last_announced_part = None

            self.last_hla_count = 0
            self.last_program_message = ""
            self.last_alarm_info = "ALARM: NONE"
            self.last_counts = {name: 0 for name in CLASS_NAMES}
            self.last_detection_area_text = f"{int(AREA_PERCENTAGE_WIDTH * 100)}%"

            if full_reset:
                self.latest_frame = self._build_placeholder_frame("Memuat aplikasi...")
                self.latest_debug_text = ""

    # ----------------------------
    # Database sync
    # ----------------------------
    def sync_history_from_db(self, force=False):
        now = time.time()
        if (not force) and ((now - self.last_history_refresh_time) < HISTORY_REFRESH_INTERVAL):
            return

        history = load_recent_history(MAX_HISTORY_DISPLAY)
        with self.lock:
            self.capture_history = history
            if self.current_program_date:
                self.oke_counter = count_ok_records(self.current_program_date)
            else:
                latest_date = get_latest_program_date_from_db()
                if latest_date:
                    self.current_program_date = latest_date
                    self.oke_counter = count_ok_records(latest_date)
                else:
                    self.oke_counter = 0
        self.last_history_refresh_time = now

    def update_program_date_from_parsed(self, current_parsed_data):
        new_program_date = self.get_date_folder_name(current_parsed_data)
        with self.lock:
            if new_program_date != self.current_program_date:
                self.current_program_date = new_program_date
                self.oke_counter = count_ok_records(new_program_date)
                print(f"[INFO] Program date updated: {new_program_date}")

    def get_date_folder_name(self, current_parsed_data):
        if current_parsed_data and len(current_parsed_data) >= 6:
            year = current_parsed_data[3]
            month = current_parsed_data[4]
            day = current_parsed_data[5]
            return f"{year}_{month:02d}_{day:02d}"

        with self.lock:
            if self.current_program_date:
                return self.current_program_date

        latest_date = get_latest_program_date_from_db()
        return latest_date if latest_date else "NO_PROGRAM_DATE"

    # ----------------------------
    # MQTT helpers
    # ----------------------------
    def connect_mqtt(self):
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.client.loop_start()
        except Exception as exc:
            print(f"[ERROR] MQTT connect failed: {exc}")

    def on_connect(self, client_instance, userdata, flags, rc, properties=None):
        if rc == 0:
            self.mqtt_connected = True
            print("[INFO] Connected to broker")
            client_instance.subscribe(MQTT_TOPIC_SUB)
            print(f"[INFO] Subscribed to {MQTT_TOPIC_SUB}")
        else:
            self.mqtt_connected = False
            print(f"[ERROR] Connection failed with code {rc}")

    def on_message(self, client_instance, userdata, msg):
        try:
            message_content = msg.payload.decode("utf-8")
            parsed = self.parse_message(message_content)
            if parsed is not None:
                with self.lock:
                    self.parsed_data = parsed
                    self.last_program_message = message_content
                if message_content.startswith("data_judg,"):
                    self.update_program_date_from_parsed(parsed)
                elif message_content.startswith("data_reset,"):
                    self.reset_conditions_from_mqtt()
        except Exception as exc:
            print(f"[ERROR] on_message: {exc}")
            traceback.print_exc()

    @staticmethod
    def parse_message(message):
        if message.startswith("data_judg,"):
            values = message[len("data_judg,"):].rstrip("#").split(",")
            return [int(v) for v in values if v != ""]
        if message.startswith("data_reset,"):
            values = message[len("data_reset,"):].rstrip("#").split(",")
            return [int(v) for v in values if v != ""]
        return None

    def publish(self, topic, payload):
        try:
            self.client.publish(topic, payload)
        except Exception as exc:
            print(f"[ERROR] Publish failed: {exc}")

    def play_sound(self, track_number):
        self.publish(MQTT_TOPIC_SUB, f"test_sound,{track_number}")
        print(f"[SOUND] test_sound,{track_number} sent")

    def send_reset_command(self):
        self.publish(MQTT_TOPIC_SUB, "data_reset,1,1,1,1,1,1,1,1,1,1,#")
        self.reset_conditions_from_mqtt()
        print("[INFO] Manual reset command sent")

    def reset_conditions_from_mqtt(self):
        with self.lock:
            self.alarm_counter = 0
            self.parsed_data = None
            self.mismatch_active = False
            self.mismatch_pending_since = None
            self.judgment_ng_alarm_active = False
            self.last_judgment_ng_sound_time = 0
            self.interlock_active = False
            self.missing_hla_alarm_active = False
            self.missing_hla_pending_since = None
            self.last_missing_hla_sound_time = 0
            self.post_ok_countdown_active = False
            self.post_ok_countdown_end_time = 0
            self.part_sound_candidate = None
            self.part_sound_candidate_since = 0
            self.last_announced_part = None
            self.interlock_reset_block = True
            self.condition_button = 0
            self.status_text = "STANDBY"
            self.status_color = (255, 255, 255)
            self.active_part = "None"
            self.total_hla = None
        self.sync_history_from_db(force=True)
        print("[INFO] Conditions reset. Database history retained.")

    # ----------------------------
    # Camera / model helpers
    # ----------------------------
    @staticmethod
    def test_stream(path):
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

    def start_camera(self):
        if USE_USB_CAMERA:
            print(f"[INFO] Starting USB camera index {CAMERA_INDEX}")
            vs = VideoStream(src=CAMERA_INDEX).start()
            time.sleep(2.0)
            frame = vs.read()
            if frame is None:
                raise RuntimeError(f"USB camera index {CAMERA_INDEX} not detected")
            return vs

        rtsp_url = None
        for path in COMMON_PATHS:
            if self.test_stream(path):
                rtsp_url = RTSP_BASE_URL + path
                break

        if rtsp_url is None:
            raise RuntimeError("No valid CCTV stream found")

        vs = VideoStream(rtsp_url).start()
        time.sleep(2.0)
        frame = vs.read()
        if frame is None:
            raise RuntimeError("CCTV stream not detected")
        return vs

    @staticmethod
    def define_detection_area(frame_shape):
        height, width = frame_shape[:2]
        x_margin = int(width * AREA_MARGIN_WIDTH)
        y_margin = int(height * AREA_MARGIN_HEIGHT)
        return x_margin, y_margin, width - x_margin, height - y_margin

    @staticmethod
    def is_in_detection_area(bbox, detection_area):
        x1, y1, x2, y2 = bbox[:4]
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        area_x_start, area_y_start, area_x_end, area_y_end = detection_area
        return area_x_start <= center_x <= area_x_end and area_y_start <= center_y <= area_y_end

    def capture_image(self, original_frame, timestamp_text, result_status, current_parsed_data, detection_results):
        class_colors = {
            "hla": (255, 0, 0),
            "hla_terlentang": (0, 0, 255),
            "hla_terbalik": (0, 0, 200),
            "k_80": (0, 255, 0),
            "k_88": (0, 165, 255),
            "k_108": (128, 0, 128),
            "b_80": (255, 255, 0),
            "b_88": (255, 0, 255),
            "b_108": (192, 192, 192),
        }

        date_folder_name = self.get_date_folder_name(current_parsed_data)
        base_save_folder = OK_FOLDER if result_status == "OK" else NG_FOLDER
        date_save_folder = os.path.join(base_save_folder, date_folder_name)
        os.makedirs(date_save_folder, exist_ok=True)

        image_save_path = os.path.join(date_save_folder, f"hla_capture_{timestamp_text}.jpg")
        frame_to_save = original_frame.copy()

        if detection_results is not None and hasattr(detection_results[0], "boxes"):
            for box in detection_results[0].boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                if conf > 0.5 and cls_id < len(CLASS_NAMES):
                    class_name = CLASS_NAMES[cls_id]
                    color = class_colors.get(class_name, (255, 255, 255))
                    cv2.rectangle(frame_to_save, (x1, y1), (x2, y2), color, 2)

        cv2.imwrite(image_save_path, frame_to_save)
        return image_save_path

    # ----------------------------
    # Lifecycle
    # ----------------------------
    def start(self):
        init_database()
        os.makedirs(OK_FOLDER, exist_ok=True)
        os.makedirs(NG_FOLDER, exist_ok=True)
        self.sync_history_from_db(force=True)
        self.connect_mqtt()

        try:
            self.model = YOLO(MODEL_PATH)
            print("[INFO] YOLO model loaded")
        except Exception as exc:
            raise RuntimeError(f"Failed to load YOLO model: {exc}")

        self.camera_stream = self.start_camera()
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()
        print("[INFO] Integrated monitor started")

    def stop(self):
        self.stop_event.set()
        try:
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=2)
        except Exception:
            pass

        try:
            if self.camera_stream is not None:
                self.camera_stream.stop()
        except Exception as exc:
            print(f"[ERROR] Stop camera: {exc}")

        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception as exc:
            print(f"[ERROR] Stop MQTT: {exc}")

    # ----------------------------
    # Snapshot for UI
    # ----------------------------
    def get_snapshot(self):
        with self.lock:
            frame = self.latest_frame.copy() if self.latest_frame is not None else self._build_placeholder_frame("No frame")
            history = list(self.capture_history)
            status = {
                "status_text": self.status_text,
                "active_part": self.active_part,
                "total_hla": self.total_hla,
                "oke_counter": self.oke_counter,
                "ng_counter": self.ng_counter,
                "program_date": self.current_program_date or "NO_PROGRAM_DATE",
                "last_hla_count": self.last_hla_count,
                "interlock_active": self.interlock_active,
                "interlock_reset_block": self.interlock_reset_block,
                "judgment_ng_alarm_active": self.judgment_ng_alarm_active,
                "missing_hla_alarm_active": self.missing_hla_alarm_active,
                "mismatch_active": self.mismatch_active,
                "post_ok_countdown_active": self.post_ok_countdown_active,
                "post_ok_countdown_end_time": self.post_ok_countdown_end_time,
                "detection_area_text": self.last_detection_area_text,
                "alarm_info": self.last_alarm_info,
                "debug_text": self.latest_debug_text,
                "mqtt_connected": self.mqtt_connected,
            }
        return frame, history, status

    # ----------------------------
    # Monitor loop
    # ----------------------------
    def monitor_loop(self):
        while not self.stop_event.is_set():
            try:
                self.sync_history_from_db(force=False)
                current_time = time.time()
                frame = self.camera_stream.read()
                if frame is None:
                    with self.lock:
                        self.latest_frame = self._build_placeholder_frame("Frame kamera kosong")
                        self.latest_debug_text = "[WARNING] Frame is None"
                    time.sleep(0.2)
                    continue

                original_frame = frame.copy()
                detection_area = self.define_detection_area(frame.shape)
                results = self.model(frame, conf=0.5, verbose=False)
                detected_objects = results[0].boxes.data.cpu().numpy()

                class_counts = {class_name: 0 for class_name in CLASS_NAMES}
                for obj in detected_objects:
                    cls_id = int(obj[5])
                    if cls_id < len(CLASS_NAMES):
                        class_name = CLASS_NAMES[cls_id]
                        if class_name == "hla":
                            if self.is_in_detection_area(obj, detection_area):
                                class_counts[class_name] += 1
                        else:
                            class_counts[class_name] += 1

                hla_count = class_counts["hla"]
                hla_terlentang_count = class_counts["hla_terlentang"]
                hla_terbalik_count = class_counts["hla_terbalik"]
                k_80_count = class_counts["k_80"]
                k_88_count = class_counts["k_88"]
                k_108_count = class_counts["k_108"]
                b_80_count = class_counts["b_80"]
                b_88_count = class_counts["b_88"]
                b_108_count = class_counts["b_108"]

                with self.lock:
                    if hla_count != 44:
                        self.interlock_reset_block = False

                    if self.post_ok_countdown_active and current_time >= self.post_ok_countdown_end_time:
                        self.post_ok_countdown_active = False
                        print("[INFO] Post-OK countdown finished -> interlock can arm again")

                new_active_part = "None"
                new_total_hla = None
                if k_108_count > 0:
                    new_active_part = "ADM Export"
                    new_total_hla = 108
                elif k_88_count > 0:
                    new_active_part = "tmmin-1L"
                    new_total_hla = 88
                elif k_80_count > 0:
                    new_active_part = "tmmin-1E"
                    new_total_hla = 80

                with self.lock:
                    if new_active_part != self.part_sound_candidate:
                        self.part_sound_candidate = new_active_part
                        self.part_sound_candidate_since = current_time
                    elif (
                        new_active_part != "None"
                        and new_active_part != self.last_announced_part
                        and (current_time - self.part_sound_candidate_since) >= DANGAE_SOUND_DELAY
                    ):
                        if new_active_part == "tmmin-1E":
                            self.play_sound(7)
                        elif new_active_part == "tmmin-1L":
                            self.play_sound(8)
                        elif new_active_part == "ADM Export":
                            self.play_sound(9)
                        self.last_announced_part = new_active_part
                        print(f"[INFO] Dangae sound confirmed after {DANGAE_SOUND_DELAY}s: {new_active_part}")
                    elif new_active_part == "None":
                        self.last_announced_part = None

                    self.active_part = new_active_part
                    self.total_hla = new_total_hla

                mismatch_now = False
                mismatch_notification = ""
                if hla_count >= 1:
                    if (k_80_count > 0 and b_80_count == 0) or (k_88_count > 0 and b_88_count == 0) or (k_108_count > 0 and b_108_count == 0):
                        mismatch_notification = "Dangae Tidak Sesuai!"
                        mismatch_now = True
                    elif (b_80_count > 0 and k_80_count == 0) or (b_88_count > 0 and k_88_count == 0) or (b_108_count > 0 and k_108_count == 0):
                        mismatch_notification = "Dangae Tidak Sesuai!"
                        mismatch_now = True

                with self.lock:
                    if mismatch_now:
                        if self.mismatch_pending_since is None:
                            self.mismatch_pending_since = current_time
                        mismatch_duration = current_time - self.mismatch_pending_since
                        if mismatch_duration >= MISMATCH_SOUND_DELAY:
                            if not self.mismatch_active:
                                self.play_sound(4)
                                self.last_mismatch_sound_time = current_time
                                self.mismatch_active = True
                                print("[INFO] Mismatch persisted 5s -> sound 4 ON")
                            elif (current_time - self.last_mismatch_sound_time) >= MISMATCH_SOUND_REPEAT_INTERVAL:
                                self.play_sound(4)
                                self.last_mismatch_sound_time = current_time
                        else:
                            self.mismatch_active = False
                    else:
                        if self.mismatch_active:
                            print("[INFO] Mismatch cleared -> sound 4 OFF")
                        self.mismatch_active = False
                        self.mismatch_pending_since = None

                    if (
                        (not self.judgment_ng_alarm_active)
                        and (not self.interlock_active)
                        and (not self.interlock_reset_block)
                        and (not self.post_ok_countdown_active)
                        and hla_count == 44
                    ):
                        self.interlock_active = True
                        self.missing_hla_alarm_active = False
                        self.missing_hla_pending_since = None
                        self.condition_button = 1
                        self.status_text = "JUDGMENT: INTERLOCK"
                        self.status_color = (0, 255, 255)
                        print("[INFO] Interlock activated")

                    if self.interlock_active and (not self.judgment_ng_alarm_active):
                        if hla_count == 0:
                            self.condition_button = 1
                            self.status_text = "PROSES BELUM SELESAI"
                            self.status_color = (0, 255, 255)
                            if self.missing_hla_pending_since is None:
                                self.missing_hla_pending_since = current_time
                            if not self.missing_hla_alarm_active:
                                if (current_time - self.missing_hla_pending_since) >= MISSING_HLA_SOUND_START_DELAY:
                                    self.play_sound(5)
                                    self.last_missing_hla_sound_time = current_time
                                    self.missing_hla_alarm_active = True
                                    print("[INFO] HLA lost during interlock -> sound 5 ON")
                            else:
                                if (current_time - self.last_missing_hla_sound_time) >= MISSING_HLA_SOUND_INTERVAL:
                                    self.play_sound(5)
                                    self.last_missing_hla_sound_time = current_time
                        else:
                            if self.missing_hla_alarm_active:
                                print("[INFO] HLA detected again -> sound 5 OFF")
                            self.missing_hla_alarm_active = False
                            self.missing_hla_pending_since = None

                with self.lock:
                    parsed_data_local = list(self.parsed_data) if self.parsed_data is not None else None
                    total_hla_local = self.total_hla
                    active_part_local = self.active_part

                if total_hla_local is not None and parsed_data_local is not None and len(parsed_data_local) > 1 and parsed_data_local[1] == 1:
                    self.update_program_date_from_parsed(parsed_data_local)
                    program_date_text = self.get_date_folder_name(parsed_data_local)
                    timestamp_text = (
                        f"{parsed_data_local[3]:04d}{parsed_data_local[4]:02d}{parsed_data_local[5]:02d}_"
                        f"{parsed_data_local[6]:02d}{parsed_data_local[7]:02d}{parsed_data_local[8]:02d}"
                    )

                    if hla_terlentang_count > 0 or hla_terbalik_count > 0:
                        self.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,#")

                    if hla_count == total_hla_local:
                        self.publish(MQTT_TOPIC_PUB, "data_result,1,1,1,1,1,1,1,1,1,#")
                        self.play_sound(1)

                        with self.lock:
                            self.interlock_active = False
                            self.missing_hla_alarm_active = False
                            self.missing_hla_pending_since = None
                            self.post_ok_countdown_active = True
                            self.post_ok_countdown_end_time = current_time + POST_OK_INTERLOCK_DELAY
                            self.interlock_reset_block = False
                            self.condition_button = 0
                            self.status_text = "STANDBY"
                            self.status_color = (255, 255, 255)

                        if (time.time() - self.last_capture_time) >= CAPTURE_COOLDOWN:
                            image_path = self.capture_image(original_frame, timestamp_text, "OK", parsed_data_local, results)
                            insert_history_record(
                                timestamp_text=timestamp_text,
                                program_date_text=program_date_text,
                                hla_count=hla_count,
                                status="OKE",
                                image_path=image_path,
                                active_part_text=active_part_local,
                                expected_hla=total_hla_local,
                            )
                            self.sync_history_from_db(force=True)
                            self.publish(MQTT_TOPIC_PUB_INSERT, f"data_oke,1,1,1,{count_ok_records(program_date_text)},#")
                            self.last_capture_time = time.time()

                        time.sleep(1)
                    else:
                        self.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,#")
                        with self.lock:
                            self.alarm_counter = 1
                            self.ng_counter += 1
                            if not self.judgment_ng_alarm_active:
                                self.play_sound(6)
                                self.last_judgment_ng_sound_time = current_time
                            self.judgment_ng_alarm_active = True
                            self.interlock_active = False
                            self.missing_hla_alarm_active = False
                            self.missing_hla_pending_since = None
                            self.condition_button = 0
                            self.status_text = "JUDGMENT: NG COUNT"
                            self.status_color = (0, 0, 255)

                        image_path = self.capture_image(original_frame, timestamp_text, "NG", parsed_data_local, results)
                        insert_history_record(
                            timestamp_text=timestamp_text,
                            program_date_text=program_date_text,
                            hla_count=hla_count,
                            status="NG",
                            image_path=image_path,
                            active_part_text=active_part_local,
                            expected_hla=total_hla_local,
                        )
                        self.sync_history_from_db(force=True)
                        time.sleep(1)

                    with self.lock:
                        if self.parsed_data is not None and len(self.parsed_data) > 1:
                            self.parsed_data[1] = 0

                with self.lock:
                    if self.judgment_ng_alarm_active:
                        self.status_text = "JUDGMENT: NG COUNT"
                        self.status_color = (0, 0, 255)
                        if (current_time - self.last_judgment_ng_sound_time) >= NG_SOUND_REPEAT_INTERVAL:
                            self.play_sound(6)
                            self.last_judgment_ng_sound_time = current_time
                    elif self.missing_hla_alarm_active:
                        self.status_text = "PROSES BELUM SELESAI"
                        self.status_color = (0, 255, 255)
                        self.condition_button = 1
                    elif self.interlock_active:
                        self.status_text = "JUDGMENT: INTERLOCK"
                        self.status_color = (0, 255, 255)
                        self.condition_button = 1
                    elif self.post_ok_countdown_active:
                        remaining = max(0, math.ceil(self.post_ok_countdown_end_time - current_time))
                        self.status_text = f"COUNTDOWN OK: {remaining} DETIK"
                        self.status_color = (255, 255, 255)
                    else:
                        if not self.judgment_ng_alarm_active:
                            self.condition_button = 0

                    if self.judgment_ng_alarm_active:
                        self.last_alarm_info = "ALARM: SOUND 6"
                    elif self.missing_hla_alarm_active:
                        self.last_alarm_info = "ALARM: SOUND 5"
                    elif self.mismatch_active:
                        self.last_alarm_info = "ALARM: SOUND 4"
                    elif self.interlock_active:
                        self.last_alarm_info = "ALARM: INTERLOCK ON"
                    elif self.post_ok_countdown_active:
                        self.last_alarm_info = "ALARM: COUNTDOWN OK"
                    else:
                        self.last_alarm_info = "ALARM: NONE"

                    self.last_hla_count = hla_count
                    self.last_counts = class_counts
                    self.last_detection_area_text = f"{int(AREA_PERCENTAGE_WIDTH * 100)}%"

                composed_frame = self.compose_monitor_frame(
                    frame=frame,
                    results=results,
                    detection_area=detection_area,
                    mismatch_notification=mismatch_notification,
                    current_time=current_time,
                )

                debug_text = self.build_debug_text(class_counts)
                with self.lock:
                    self.latest_frame = composed_frame
                    self.latest_debug_text = debug_text

                time.sleep(LOOP_DELAY)

            except Exception as exc:
                err_text = f"[ERROR] Error in main loop: {exc}\n{traceback.format_exc()}"
                print(err_text)
                with self.lock:
                    self.latest_frame = self._build_placeholder_frame("Error pada monitor realtime")
                    self.latest_debug_text = err_text
                time.sleep(1)

    def build_debug_text(self, class_counts):
        with self.lock:
            countdown_text = "-"
            if self.post_ok_countdown_active:
                countdown_text = str(max(0, math.ceil(self.post_ok_countdown_end_time - time.time())))
            parsed_preview = self.parsed_data
            return (
                f"HLA                 : {class_counts['hla']}\n"
                f"HLA Terlentang      : {class_counts['hla_terlentang']}\n"
                f"HLA Terbalik        : {class_counts['hla_terbalik']}\n"
                f"k_80 / k_88 / k_108 : {class_counts['k_80']} / {class_counts['k_88']} / {class_counts['k_108']}\n"
                f"b_80 / b_88 / b_108 : {class_counts['b_80']} / {class_counts['b_88']} / {class_counts['b_108']}\n"
                f"Active Part         : {self.active_part}\n"
                f"Total HLA           : {self.total_hla}\n"
                f"Program Date        : {self.current_program_date}\n"
                f"Condition Button    : {self.condition_button}\n"
                f"Alarm Counter       : {self.alarm_counter}\n"
                f"Status Text         : {self.status_text}\n"
                f"Parsed Data         : {parsed_preview}\n"
                f"OKE Counter         : {self.oke_counter}\n"
                f"NG Counter          : {self.ng_counter}\n"
                f"Mismatch Active     : {self.mismatch_active}\n"
                f"NG Alarm Active     : {self.judgment_ng_alarm_active}\n"
                f"Interlock Active    : {self.interlock_active}\n"
                f"Interlock Block     : {self.interlock_reset_block}\n"
                f"Countdown Remaining : {countdown_text}\n"
            )

    def compose_monitor_frame(self, frame, results, detection_area, mismatch_notification, current_time):
        with self.lock:
            history = list(self.capture_history)
            status_text = self.status_text
            oke_counter = self.oke_counter
            current_program_date = self.current_program_date or "NO_PROGRAM_DATE"
            total_hla = self.total_hla
            interlock_reset_block = self.interlock_reset_block
            post_ok_countdown_active = self.post_ok_countdown_active
            post_ok_countdown_end_time = self.post_ok_countdown_end_time
            judgment_ng_alarm_active = self.judgment_ng_alarm_active
            missing_hla_alarm_active = self.missing_hla_alarm_active
            mismatch_active = self.mismatch_active
            interlock_active = self.interlock_active
            missing_hla_pending_since = self.missing_hla_pending_since
            last_hla_count = self.last_hla_count

        annotated_frame = results[0].plot(line_width=1, labels=True, conf=True)
        x_start, y_start, x_end, y_end = detection_area
        cv2.rectangle(annotated_frame, (x_start, y_start), (x_end, y_end), (0, 255, 255), 3)
        cv2.putText(annotated_frame, "DETECTION AREA", (x_start + 10, y_start + 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
        cv2.rectangle(annotated_frame, (0, 0), (annotated_frame.shape[1] - 1, annotated_frame.shape[0] - 1), (184, 132, 0), 20)

        if mismatch_notification and missing_hla_pending_since is not None:
            pass

        with self.lock:
            if self.mismatch_pending_since is not None and (current_time - self.mismatch_pending_since) >= MISMATCH_SOUND_DELAY:
                font = cv2.FONT_HERSHEY_SIMPLEX
                text_size = cv2.getTextSize(mismatch_notification, font, 2, 5)[0]
                text_x = annotated_frame.shape[1] // 2 - text_size[0] // 2
                text_y = 150
                cv2.rectangle(annotated_frame, (text_x - 20, text_y - text_size[1] - 20), (text_x + text_size[0] + 20, text_y + 20), (0, 0, 0), -1)
                cv2.putText(annotated_frame, mismatch_notification, (text_x, text_y), font, 2, (0, 0, 255), 5)

        height, width = annotated_frame.shape[:2]
        canvas = np.zeros((height, width + SIDEBAR_WIDTH, 3), dtype=np.uint8)
        canvas[:, :SIDEBAR_WIDTH] = (142, 112, 0)
        canvas[:, SIDEBAR_WIDTH:SIDEBAR_WIDTH + width] = annotated_frame

        font = cv2.FONT_HERSHEY_SIMPLEX
        white_text = (255, 255, 255)
        cv2.rectangle(canvas, (20, 25), (SIDEBAR_WIDTH - 20, 105), (0, 0, 255), -1)
        cv2.putText(canvas, f"Total Tray: {oke_counter}", (30, 70), font, 1.25, white_text, 4)
        cv2.putText(canvas, f"Date: {current_program_date}", (30, 98), font, 0.65, white_text, 2)

        cv2.rectangle(canvas, (20, 120), (SIDEBAR_WIDTH - 20, 190), (0, 120, 0), -1)
        cv2.putText(canvas, status_text, (30, 165), font, 0.9, white_text, 2)

        cv2.putText(canvas, f"Detection Area: {int(AREA_PERCENTAGE_WIDTH * 100)}%", (30, 220), font, 0.7, white_text, 2)

        alarm_info = "ALARM: NONE"
        if judgment_ng_alarm_active:
            alarm_info = "ALARM: SOUND 6"
        elif missing_hla_alarm_active:
            alarm_info = "ALARM: SOUND 5"
        elif mismatch_active:
            alarm_info = "ALARM: SOUND 4"
        elif interlock_active:
            alarm_info = "ALARM: INTERLOCK ON"
        elif post_ok_countdown_active:
            alarm_info = "ALARM: COUNTDOWN OK"

        cv2.putText(canvas, alarm_info, (30, 255), font, 0.8, white_text, 2)
        cv2.putText(canvas, f"INTERLOCK BLOCK: {interlock_reset_block}", (30, 285), font, 0.7, white_text, 2)

        if post_ok_countdown_active:
            remaining = max(0, math.ceil(post_ok_countdown_end_time - current_time))
            cv2.putText(canvas, f"COUNTDOWN OK: {remaining} DETIK", (30, 315), font, 0.7, white_text, 2)

        if self.missing_hla_pending_since is not None and not missing_hla_alarm_active:
            pending_left = max(0.0, MISSING_HLA_SOUND_START_DELAY - (current_time - self.missing_hla_pending_since))
            cv2.putText(canvas, f"SOUND 5 DELAY: {pending_left:.1f}s", (30, 345), font, 0.7, white_text, 2)

        history_start_y = 380
        for idx, record in enumerate(history):
            ts = record["Timestamp"]
            count = record["Total HLA"]
            status = record["Status"]
            history_text = f"{idx + 1}: {ts} | HLA: {count} | {status}"
            text_position = (30, history_start_y + (idx * 30))
            (text_width, text_height), _ = cv2.getTextSize(history_text, font, 0.6, 2)
            if status == "NG":
                cv2.rectangle(canvas, (text_position[0] - 5, text_position[1] - text_height - 5), (text_position[0] + text_width + 5, text_position[1] + 5), (0, 0, 139), -1)
            cv2.putText(canvas, history_text, text_position, font, 0.6, white_text, 2)

        sidebar_bottom_y = height - 100
        cv2.rectangle(canvas, (20, sidebar_bottom_y - 50), (SIDEBAR_WIDTH - 20, sidebar_bottom_y), (122, 52, 0), -1)
        cv2.putText(canvas, f"TRAY: {last_hla_count} PCS", (30, sidebar_bottom_y - 10), font, 1.5, white_text, 5)
        cv2.putText(canvas, f"Part Dangae: {total_hla if total_hla is not None else 'None'}", (30, sidebar_bottom_y + 40), font, 1.0, white_text, 2)

        h_canvas, w_canvas = canvas.shape[:2]
        scale = min(DISPLAY_WIDTH / w_canvas, DISPLAY_HEIGHT / h_canvas)
        new_w = int(w_canvas * scale)
        new_h = int(h_canvas * scale)
        resized_canvas = cv2.resize(canvas, (new_w, new_h))

        display = np.zeros((DISPLAY_HEIGHT, DISPLAY_WIDTH, 3), dtype=np.uint8)
        x_offset = (DISPLAY_WIDTH - new_w) // 2
        y_offset = (DISPLAY_HEIGHT - new_h) // 2
        display[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized_canvas
        return display

    @staticmethod
    def _build_placeholder_frame(text):
        canvas = np.zeros((DISPLAY_HEIGHT, DISPLAY_WIDTH, 3), dtype=np.uint8)
        canvas[:] = (35, 35, 35)
        cv2.putText(canvas, text, (70, DISPLAY_HEIGHT // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
        return canvas


# =========================================================
# TKINTER APP
# =========================================================
class IntegratedApp:
    def __init__(self, root):
        self.root = root
        self.root.title("HLA Monitor + Setting Integrated")
        self.root.geometry("1600x980")
        self.root.configure(bg="#e5e5e5")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.engine = HlaMonitorEngine()
        self.current_photo = None

        self._build_style()
        self._build_ui()
        self._load_initial_data()

        try:
            self.engine.start()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

        self.update_monitor_ui()
        self.refresh_setting_table()

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook.Tab", font=("Arial", 12, "bold"), padding=(18, 8))
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"))
        style.configure("Treeview", rowheight=24)

    def _build_ui(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.monitor_tab = tk.Frame(self.notebook, bg="#dcdcdc")
        self.setting_tab = tk.Frame(self.notebook, bg="#efefef")
        self.notebook.add(self.monitor_tab, text="Monitor")
        self.notebook.add(self.setting_tab, text="Setting")

        self._build_monitor_tab()
        self._build_setting_tab()

    def _build_monitor_tab(self):
        top_bar = tk.Frame(self.monitor_tab, bg="#dcdcdc")
        top_bar.pack(fill="x", padx=10, pady=(10, 5))

        self.monitor_status_var = tk.StringVar(value="Status aplikasi: memuat...")
        tk.Label(top_bar, textvariable=self.monitor_status_var, font=("Arial", 12, "bold"), bg="#dcdcdc").pack(side="left")
        tk.Button(top_bar, text="Reset Sistem", command=self.reset_system, font=("Arial", 11, "bold"), bg="#87CEFA", width=16).pack(side="right", padx=5)
        tk.Button(top_bar, text="Refresh History", command=self.manual_refresh, font=("Arial", 11), width=16).pack(side="right", padx=5)

        body = tk.Frame(self.monitor_tab, bg="#dcdcdc")
        body.pack(fill="both", expand=True, padx=10, pady=5)

        left_panel = tk.Frame(body, bg="#f3f3f3", bd=2, relief="groove")
        left_panel.pack(side="left", fill="y", padx=(0, 8))
        right_panel = tk.Frame(body, bg="#111111", bd=2, relief="groove")
        right_panel.pack(side="left", fill="both", expand=True)

        tk.Label(left_panel, text="STATUS MONITOR", font=("Arial", 14, "bold"), bg="#f3f3f3").pack(anchor="w", padx=10, pady=(10, 5))

        self.lbl_program_date = self._make_status_label(left_panel, "Program Date")
        self.lbl_total_tray = self._make_status_label(left_panel, "Total Tray OKE")
        self.lbl_tray_count = self._make_status_label(left_panel, "Tray Saat Ini")
        self.lbl_status = self._make_status_label(left_panel, "Status")
        self.lbl_alarm = self._make_status_label(left_panel, "Alarm")
        self.lbl_part = self._make_status_label(left_panel, "Active Part")
        self.lbl_expected = self._make_status_label(left_panel, "Expected HLA")
        self.lbl_interlock = self._make_status_label(left_panel, "Interlock")
        self.lbl_mqtt = self._make_status_label(left_panel, "MQTT")

        tk.Label(left_panel, text="History Judgment (SQLite)", font=("Arial", 12, "bold"), bg="#f3f3f3").pack(anchor="w", padx=10, pady=(14, 4))
        history_frame = tk.Frame(left_panel, bg="#f3f3f3")
        history_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.monitor_history_tree = ttk.Treeview(history_frame, columns=("timestamp", "hla", "status"), show="headings", height=18)
        self.monitor_history_tree.heading("timestamp", text="Timestamp")
        self.monitor_history_tree.heading("hla", text="HLA")
        self.monitor_history_tree.heading("status", text="Status")
        self.monitor_history_tree.column("timestamp", width=180, anchor="w")
        self.monitor_history_tree.column("hla", width=70, anchor="center")
        self.monitor_history_tree.column("status", width=80, anchor="center")
        self.monitor_history_tree.pack(side="left", fill="both", expand=True)

        history_scroll = ttk.Scrollbar(history_frame, orient="vertical", command=self.monitor_history_tree.yview)
        history_scroll.pack(side="right", fill="y")
        self.monitor_history_tree.configure(yscrollcommand=history_scroll.set)

        self.video_label = tk.Label(right_panel, bg="#111111")
        self.video_label.pack(fill="both", expand=True, padx=8, pady=8)

        debug_frame = tk.Frame(self.monitor_tab, bg="#dcdcdc")
        debug_frame.pack(fill="both", expand=False, padx=10, pady=(0, 10))
        tk.Label(debug_frame, text="Debug Log", font=("Arial", 12, "bold"), bg="#dcdcdc").pack(anchor="w")
        self.debug_text = tk.Text(debug_frame, height=10, wrap="none", font=("Consolas", 10))
        self.debug_text.pack(fill="both", expand=False)
        self.debug_text.configure(state="disabled")

    def _make_status_label(self, parent, title):
        var = tk.StringVar(value=f"{title}: -")
        lbl = tk.Label(parent, textvariable=var, font=("Arial", 11), bg="#f3f3f3", anchor="w", justify="left")
        lbl.var = var
        lbl.pack(fill="x", padx=10, pady=2)
        return lbl

    def _build_setting_tab(self):
        outer = tk.Frame(self.setting_tab, bg="#efefef")
        outer.pack(fill="both", expand=True, padx=10, pady=10)

        top_area = tk.Frame(outer, bg="#efefef")
        top_area.pack(fill="x", pady=(0, 8))

        control_frame = tk.LabelFrame(top_area, text="Control Sistem", font=("Arial", 12, "bold"), bg="#efefef")
        control_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))

        tk.Label(control_frame, text="Apakah ada kondisi NG? Silahkan reset sistem kamera.", font=("Arial", 13), bg="#efefef").pack(anchor="w", padx=10, pady=(10, 8))
        tk.Button(control_frame, text="BUTTON RESET SISTEM KAMERA", command=self.reset_system, width=34, height=2, font=("Arial", 16, "bold"), bg="#87CEFA").pack(padx=10, pady=(0, 12), anchor="w")

        sound_frame = tk.LabelFrame(top_area, text="Uji Manual Semua Suara", font=("Arial", 12, "bold"), bg="#efefef")
        sound_frame.pack(side="left", fill="both", expand=True)

        sound_buttons = [
            ("1. Oke selesai", 1),
            ("2. Terimakasih", 2),
            ("3. Alarm", 3),
            ("4. Box tidak terdeteksi", 4),
            ("5. Proses belum selesai", 5),
            ("6. Jumlah part tidak sesuai", 6),
            ("7. Dangae 80 pcs", 7),
            ("8. Dangae 88 pcs", 8),
            ("9. Dangae 108 pcs", 9),
            ("10. Reset berhasil", 10),
        ]

        grid = tk.Frame(sound_frame, bg="#efefef")
        grid.pack(fill="both", expand=True, padx=10, pady=10)
        row = 0
        col = 0
        for text, track in sound_buttons:
            tk.Button(grid, text=text, command=lambda t=track: self.engine.play_sound(t), width=22, height=2, font=("Arial", 11), bg="#FFFFFF").grid(row=row, column=col, padx=6, pady=6, sticky="ew")
            col += 1
            if col > 2:
                col = 0
                row += 1
        for i in range(3):
            grid.grid_columnconfigure(i, weight=1)

        crud_frame = tk.LabelFrame(outer, text="CRUD SQLite Judgment History", font=("Arial", 12, "bold"), bg="#efefef")
        crud_frame.pack(fill="both", expand=True)

        form_frame = tk.Frame(crud_frame, bg="#efefef")
        form_frame.pack(fill="x", padx=10, pady=10)

        self.entry_id_var = tk.StringVar()
        self.entry_timestamp_var = tk.StringVar()
        self.entry_program_date_var = tk.StringVar()
        self.entry_hla_count_var = tk.StringVar(value="0")
        self.combo_status_var = tk.StringVar(value="OKE")
        self.entry_active_part_var = tk.StringVar(value="None")
        self.entry_expected_hla_var = tk.StringVar(value="0")
        self.entry_image_path_var = tk.StringVar()
        self.filter_program_date_var = tk.StringVar()
        self.summary_var = tk.StringVar(value="Total data tampil: 0")

        fields = [
            ("ID", self.entry_id_var),
            ("Timestamp", self.entry_timestamp_var),
            ("Program Date", self.entry_program_date_var),
            ("HLA Count", self.entry_hla_count_var),
            ("Active Part", self.entry_active_part_var),
            ("Expected HLA", self.entry_expected_hla_var),
            ("Image Path", self.entry_image_path_var),
        ]

        for idx, (label_text, variable) in enumerate(fields):
            tk.Label(form_frame, text=label_text, bg="#efefef", font=("Arial", 10, "bold")).grid(row=idx, column=0, sticky="w", padx=5, pady=3)
            tk.Entry(form_frame, textvariable=variable, width=45).grid(row=idx, column=1, sticky="ew", padx=5, pady=3)

        tk.Label(form_frame, text="Status", bg="#efefef", font=("Arial", 10, "bold")).grid(row=len(fields), column=0, sticky="w", padx=5, pady=3)
        ttk.Combobox(form_frame, textvariable=self.combo_status_var, values=["OKE", "NG"], state="readonly", width=42).grid(row=len(fields), column=1, sticky="ew", padx=5, pady=3)

        form_frame.grid_columnconfigure(1, weight=1)

        button_row = tk.Frame(form_frame, bg="#efefef")
        button_row.grid(row=0, column=2, rowspan=8, sticky="ns", padx=(20, 0))
        tk.Button(button_row, text="Tambah", command=self.add_record_ui, width=14, bg="#c4f0c5").pack(pady=4)
        tk.Button(button_row, text="Update", command=self.update_record_ui, width=14, bg="#ffe8a3").pack(pady=4)
        tk.Button(button_row, text="Hapus", command=self.delete_record_ui, width=14, bg="#f7b0b0").pack(pady=4)
        tk.Button(button_row, text="Clear Form", command=self.clear_form, width=14).pack(pady=4)
        tk.Button(button_row, text="Refresh", command=self.refresh_setting_table, width=14).pack(pady=4)

        filter_frame = tk.Frame(crud_frame, bg="#efefef")
        filter_frame.pack(fill="x", padx=10, pady=(0, 8))
        tk.Label(filter_frame, text="Filter Program Date", bg="#efefef", font=("Arial", 10, "bold")).pack(side="left")
        tk.Entry(filter_frame, textvariable=self.filter_program_date_var, width=20).pack(side="left", padx=6)
        tk.Button(filter_frame, text="Apply", command=self.refresh_setting_table).pack(side="left", padx=4)
        tk.Button(filter_frame, text="Clear Filter", command=self.clear_filter).pack(side="left", padx=4)
        tk.Label(filter_frame, textvariable=self.summary_var, bg="#efefef", font=("Arial", 10, "bold"), fg="#003366").pack(side="right")

        table_frame = tk.Frame(crud_frame, bg="#efefef")
        table_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        cols = ("id", "timestamp", "program_date", "hla_count", "status", "active_part", "expected_hla", "image_path", "created_at")
        self.setting_tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        headings = {
            "id": "ID",
            "timestamp": "Timestamp",
            "program_date": "Program Date",
            "hla_count": "HLA Count",
            "status": "Status",
            "active_part": "Active Part",
            "expected_hla": "Expected HLA",
            "image_path": "Image Path",
            "created_at": "Created At",
        }
        widths = {
            "id": 60,
            "timestamp": 170,
            "program_date": 120,
            "hla_count": 90,
            "status": 80,
            "active_part": 120,
            "expected_hla": 100,
            "image_path": 320,
            "created_at": 150,
        }
        for col in cols:
            self.setting_tree.heading(col, text=headings[col])
            self.setting_tree.column(col, width=widths[col], anchor="center" if col in {"id", "hla_count", "status", "expected_hla"} else "w")
        self.setting_tree.pack(side="left", fill="both", expand=True)
        self.setting_tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.setting_tree.yview)
        y_scroll.pack(side="right", fill="y")
        self.setting_tree.configure(yscrollcommand=y_scroll.set)

    def _load_initial_data(self):
        init_database()
        self.clear_form()

    # ----------------------------
    # Monitor UI refresh
    # ----------------------------
    def update_monitor_ui(self):
        try:
            frame, history, status = self.engine.get_snapshot()
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            self.current_photo = ImageTk.PhotoImage(image=img)
            self.video_label.configure(image=self.current_photo)

            self.lbl_program_date.var.set(f"Program Date: {status['program_date']}")
            self.lbl_total_tray.var.set(f"Total Tray OKE: {status['oke_counter']}")
            self.lbl_tray_count.var.set(f"Tray Saat Ini: {status['last_hla_count']} PCS")
            self.lbl_status.var.set(f"Status: {status['status_text']}")
            self.lbl_alarm.var.set(f"Alarm: {status['alarm_info']}")
            self.lbl_part.var.set(f"Active Part: {status['active_part']}")
            self.lbl_expected.var.set(f"Expected HLA: {status['total_hla'] if status['total_hla'] is not None else 'None'}")
            self.lbl_interlock.var.set(
                f"Interlock: {'ON' if status['interlock_active'] else 'OFF'} | Block: {status['interlock_reset_block']}"
            )
            self.lbl_mqtt.var.set(f"MQTT: {'CONNECTED' if status['mqtt_connected'] else 'DISCONNECTED'}")

            self.monitor_status_var.set(f"Status aplikasi: realtime aktif | Tab Monitor | Date {status['program_date']}")

            for item in self.monitor_history_tree.get_children():
                self.monitor_history_tree.delete(item)
            for row in history:
                self.monitor_history_tree.insert("", "end", values=(row["Timestamp"], row["Total HLA"], row["Status"]))

            self.debug_text.configure(state="normal")
            self.debug_text.delete("1.0", "end")
            self.debug_text.insert("1.0", status["debug_text"])
            self.debug_text.configure(state="disabled")
        except Exception as exc:
            self.monitor_status_var.set(f"Status aplikasi: error UI monitor - {exc}")

        self.root.after(150, self.update_monitor_ui)

    # ----------------------------
    # Setting CRUD
    # ----------------------------
    def clear_form(self):
        self.entry_id_var.set("")
        self.entry_timestamp_var.set("")
        self.entry_program_date_var.set("")
        self.entry_hla_count_var.set("0")
        self.combo_status_var.set("OKE")
        self.entry_active_part_var.set("None")
        self.entry_expected_hla_var.set("0")
        self.entry_image_path_var.set("")
        if hasattr(self, "setting_tree"):
            self.setting_tree.selection_remove(self.setting_tree.selection())

    def clear_filter(self):
        self.filter_program_date_var.set("")
        self.refresh_setting_table()

    def validate_form(self):
        if not self.entry_timestamp_var.get().strip():
            raise ValueError("Timestamp wajib diisi.")
        if not self.entry_program_date_var.get().strip():
            raise ValueError("Program Date wajib diisi. Contoh: 2026_04_14")
        if self.combo_status_var.get().strip() not in {"OKE", "NG"}:
            raise ValueError("Status harus OKE atau NG.")
        int(self.entry_hla_count_var.get().strip())
        if self.entry_expected_hla_var.get().strip() != "":
            int(self.entry_expected_hla_var.get().strip())

    def refresh_setting_table(self):
        for item in self.setting_tree.get_children():
            self.setting_tree.delete(item)

        rows = fetch_history_rows(self.filter_program_date_var.get())
        for row in rows:
            self.setting_tree.insert(
                "",
                "end",
                values=(
                    row["id"],
                    row["timestamp"],
                    row["program_date"],
                    row["hla_count"],
                    row["status"],
                    row["active_part"] or "",
                    row["expected_hla"] or 0,
                    row["image_path"] or "",
                    row["created_at"] or "",
                ),
            )

        summary_date = self.filter_program_date_var.get().strip()
        if summary_date:
            self.summary_var.set(f"Total OKE pada {summary_date}: {count_ok_records(summary_date)}")
        else:
            self.summary_var.set(f"Total data tampil: {len(rows)}")

        self.engine.sync_history_from_db(force=True)

    def on_tree_select(self, event=None):
        selected = self.setting_tree.selection()
        if not selected:
            return
        values = self.setting_tree.item(selected[0], "values")
        self.entry_id_var.set(values[0])
        self.entry_timestamp_var.set(values[1])
        self.entry_program_date_var.set(values[2])
        self.entry_hla_count_var.set(values[3])
        self.combo_status_var.set(values[4])
        self.entry_active_part_var.set(values[5])
        self.entry_expected_hla_var.set(values[6])
        self.entry_image_path_var.set(values[7])

    def add_record_ui(self):
        try:
            self.validate_form()
            insert_history_record(
                timestamp_text=self.entry_timestamp_var.get().strip(),
                program_date_text=self.entry_program_date_var.get().strip(),
                hla_count=self.entry_hla_count_var.get().strip(),
                status=self.combo_status_var.get().strip(),
                image_path=self.entry_image_path_var.get().strip(),
                active_part_text=self.entry_active_part_var.get().strip(),
                expected_hla=self.entry_expected_hla_var.get().strip(),
            )
            self.refresh_setting_table()
            self.clear_form()
            messagebox.showinfo("Sukses", "Data berhasil ditambahkan.")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def update_record_ui(self):
        try:
            if not self.entry_id_var.get().strip():
                raise ValueError("Pilih data yang akan diupdate.")
            self.validate_form()
            update_history_record(
                record_id=self.entry_id_var.get().strip(),
                timestamp_text=self.entry_timestamp_var.get().strip(),
                program_date_text=self.entry_program_date_var.get().strip(),
                hla_count=self.entry_hla_count_var.get().strip(),
                status=self.combo_status_var.get().strip(),
                image_path=self.entry_image_path_var.get().strip(),
                active_part_text=self.entry_active_part_var.get().strip(),
                expected_hla=self.entry_expected_hla_var.get().strip(),
            )
            self.refresh_setting_table()
            messagebox.showinfo("Sukses", "Data berhasil diupdate.")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def delete_record_ui(self):
        try:
            if not self.entry_id_var.get().strip():
                raise ValueError("Pilih data yang akan dihapus.")
            if not messagebox.askyesno("Konfirmasi", "Hapus data terpilih?"):
                return
            delete_history_record(self.entry_id_var.get().strip())
            self.refresh_setting_table()
            self.clear_form()
            messagebox.showinfo("Sukses", "Data berhasil dihapus.")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    # ----------------------------
    # Actions
    # ----------------------------
    def reset_system(self):
        self.engine.send_reset_command()
        self.refresh_setting_table()
        messagebox.showinfo("Info", "Perintah reset berhasil dikirim.")

    def manual_refresh(self):
        self.engine.sync_history_from_db(force=True)
        self.refresh_setting_table()

    def on_close(self):
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            self.engine.stop()
            self.root.destroy()


# =========================================================
# ENTRY POINT
# =========================================================
def main():
    init_database()
    root = tk.Tk()
    app = IntegratedApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
