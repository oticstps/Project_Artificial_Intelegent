import paho.mqtt.client as mqtt
from imutils.video import VideoStream
from ultralytics import YOLO
import cv2
import time
import os
import subprocess
import traceback
from datetime import datetime
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import threading
from queue import Queue

# Constants
MQTT_BROKER = "10.42.0.1"
MQTT_PORT = 1883
MQTT_TOPIC_PUB = "11220223_core_nais_result"
MQTT_TOPIC_PUB_INSERT = "11220223_core_nais_insert"
MQTT_TOPIC_SUB = "11220223_core_nais_judg"
RTSP_BASE_URL = "rtsp://admin:pt_otics1*@192.168.1.108:554"
COMMON_PATHS = ["/cam/realmonitor?channel=1&subtype=0"]
MEDIA_FOLDER = "media"
OK_FOLDER = os.path.join(MEDIA_FOLDER, "OK")
NG_FOLDER = os.path.join(MEDIA_FOLDER, "NG")
MODEL_PATH = "/home/otics/on/best.pt"
CLASS_NAMES = ['hla', 'off', 'altar', 'box_after', '108_pcs_hla', '80_pcs_hla', '88_pcs_hla', 'hla_terlentang', 'hla_terbalik', 'tray']

# Area Detection Configuration
AREA_PERCENTAGE = 0.6
AREA_MARGIN = (1 - AREA_PERCENTAGE) / 2

class HLA_Detector_GUI:
    def __init__(self, root):
        self.root = root
        self.root.title("SISTEM DETEKSI HLA - CCTV MONITORING")
        self.root.geometry("1600x900")
        self.root.configure(bg="#e5e5e5")
        
        # Initialize variables
        self.total_hla = None
        self.active_part = "None"
        self.total_hla_count = 0
        self.previous_hla_count = 0
        self.condition_button = 0
        self.status_text = "STANDBY"
        self.last_status = "READY"
        self.oke_counter = 0
        self.ng_counter = 0
        self.alarm_counter = 0
        self.capture_history = []
        self.last_capture_time = 0
        self.capture_cooldown = 60
        self.parsed_data = None
        self.judgment_cooldown = 60
        self.last_judgment = 0
        self.time_condition_met_0710 = False
        self.time_condition_met_1950 = False
        
        # Video stream
        self.camera_stream = None
        self.model = None
        self.detection_area = None
        self.frame_queue = Queue(maxsize=1)
        self.running = True
        
        # MQTT Client
        self.client = mqtt.Client()
        
        # Initialize GUI
        self.setup_gui()
        
        # Start system
        self.start_system()
        
        # Center window
        self.center_window()
        
    def center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        
    def setup_gui(self):
        # Header Frame
        header_frame = tk.Frame(self.root, bg="#5379ec", height=80)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)
        
        title_label = tk.Label(header_frame, text="SISTEM DETEKSI HLA - CCTV MONITORING", 
                              font=("Times New Roman", 24, "bold"), fg="white", bg="#5379ec")
        title_label.pack(side=tk.LEFT, padx=20)
        
        # Time label
        self.time_label = tk.Label(header_frame, font=("Arial", 14), fg="white", bg="#5379ec")
        self.time_label.pack(side=tk.RIGHT, padx=20)
        self.update_time()
        
        # Main Content Frame
        main_frame = tk.Frame(self.root, bg="#e5e5e5")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Left Frame - Sidebar (30%)
        left_sidebar = tk.Frame(main_frame, bg="#e5e5e5", width=400, bd=2, relief='solid')
        left_sidebar.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 10))
        
        # Sidebar Header
        sidebar_header = tk.Label(left_sidebar, text="CONTROL SISTEM KAMERA", 
                                 font=("Times New Roman", 26, "bold"), 
                                 fg="#000000", bg="#e5e5e5")
        sidebar_header.pack(pady=20)
        
        # Reset Button Frame
        reset_frame = tk.Frame(left_sidebar, bg="#5379ec", bd=2, relief='solid')
        reset_frame.pack(pady=20, padx=20, fill=tk.X)
        
        reset_label1 = tk.Label(reset_frame, text="APAKAH ADA KONDISI NG ?", 
                               font=("Arial", 16), fg="white", bg="#5379ec")
        reset_label1.pack(pady=(10, 5))
        
        reset_label2 = tk.Label(reset_frame, text="SILAHKAN RESET SISTEM KAMERA", 
                               font=("Arial", 16), fg="white", bg="#5379ec")
        reset_label2.pack(pady=(5, 10))
        
        # Reset Button
        reset_button_frame = tk.Frame(left_sidebar, bg="#e5e5e5")
        reset_button_frame.pack(pady=10)
        
        self.reset_button = tk.Button(reset_button_frame, 
                                     text='BUTTON RESET SISTEM KAMERA', 
                                     command=self.on_reset_button_click,
                                     width=35, height=2, 
                                     font=("Arial", 18), 
                                     bg="#87CEFA", fg="black", 
                                     activebackground="#00BFFF", bd=2)
        self.reset_button.pack(pady=10)
        
        # Status Indicators
        status_frame = tk.LabelFrame(left_sidebar, text="STATUS SISTEM", 
                                    font=("Arial", 14, "bold"),
                                    bg="#e5e5e5", fg="#000000", padx=10, pady=10)
        status_frame.pack(fill=tk.X, padx=20, pady=10)
        
        # System Status
        sys_status_frame = tk.Frame(status_frame, bg="#e5e5e5")
        sys_status_frame.pack(fill=tk.X, pady=5)
        tk.Label(sys_status_frame, text="Status Sistem:", 
                font=("Arial", 12), fg="#000000", bg="#e5e5e5").pack(side=tk.LEFT)
        self.system_status_label = tk.Label(sys_status_frame, text="STANDBY", 
                                          font=("Arial", 12, "bold"), 
                                          fg="yellow", bg="#e5e5e5")
        self.system_status_label.pack(side=tk.RIGHT)
        
        # MQTT Status
        mqtt_frame = tk.Frame(status_frame, bg="#e5e5e5")
        mqtt_frame.pack(fill=tk.X, pady=5)
        tk.Label(mqtt_frame, text="MQTT:", 
                font=("Arial", 12), fg="#000000", bg="#e5e5e5").pack(side=tk.LEFT)
        self.mqtt_status_label = tk.Label(mqtt_frame, text="Disconnected", 
                                        font=("Arial", 12, "bold"), 
                                        fg="#e74c3c", bg="#e5e5e5")
        self.mqtt_status_label.pack(side=tk.RIGHT)
        
        # Camera Status
        cam_frame = tk.Frame(status_frame, bg="#e5e5e5")
        cam_frame.pack(fill=tk.X, pady=5)
        tk.Label(cam_frame, text="Kamera:", 
                font=("Arial", 12), fg="#000000", bg="#e5e5e5").pack(side=tk.LEFT)
        self.camera_status_label = tk.Label(cam_frame, text="Tidak Terhubung", 
                                          font=("Arial", 12, "bold"), 
                                          fg="#e74c3c", bg="#e5e5e5")
        self.camera_status_label.pack(side=tk.RIGHT)
        
        # Statistics Frame
        stats_frame = tk.LabelFrame(left_sidebar, text="STATISTIK DETEKSI", 
                                   font=("Arial", 14, "bold"),
                                   bg="#e5e5e5", fg="#000000", padx=10, pady=10)
        stats_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # OK Counter
        ok_frame = tk.Frame(stats_frame, bg="#e5e5e5")
        ok_frame.pack(fill=tk.X, pady=10)
        tk.Label(ok_frame, text="OK Counter:", 
                font=("Arial", 12), fg="#000000", bg="#e5e5e5").pack(side=tk.LEFT)
        self.ok_counter_label = tk.Label(ok_frame, text="0", 
                                        font=("Arial", 16, "bold"), 
                                        fg="#2ecc71", bg="#e5e5e5")
        self.ok_counter_label.pack(side=tk.RIGHT)
        
        # NG Counter
        ng_frame = tk.Frame(stats_frame, bg="#e5e5e5")
        ng_frame.pack(fill=tk.X, pady=10)
        tk.Label(ng_frame, text="NG Counter:", 
                font=("Arial", 12), fg="#000000", bg="#e5e5e5").pack(side=tk.LEFT)
        self.ng_counter_label = tk.Label(ng_frame, text="0", 
                                        font=("Arial", 16, "bold"), 
                                        fg="#e74c3c", bg="#e5e5e5")
        self.ng_counter_label.pack(side=tk.RIGHT)
        
        # HLA Detected
        hla_frame = tk.Frame(stats_frame, bg="#e5e5e5")
        hla_frame.pack(fill=tk.X, pady=10)
        tk.Label(hla_frame, text="HLA Terdeteksi:", 
                font=("Arial", 12), fg="#000000", bg="#e5e5e5").pack(side=tk.LEFT)
        self.hla_count_label = tk.Label(hla_frame, text="0", 
                                       font=("Arial", 16, "bold"), 
                                       fg="#3498db", bg="#e5e5e5")
        self.hla_count_label.pack(side=tk.RIGHT)
        
        # Alarm Status
        alarm_frame = tk.Frame(stats_frame, bg="#e5e5e5")
        alarm_frame.pack(fill=tk.X, pady=10)
        tk.Label(alarm_frame, text="Status Alarm:", 
                font=("Arial", 12), fg="#000000", bg="#e5e5e5").pack(side=tk.LEFT)
        self.alarm_label = tk.Label(alarm_frame, text="INACTIVE", 
                                   font=("Arial", 12, "bold"), 
                                   fg="#2ecc71", bg="#e5e5e5")
        self.alarm_label.pack(side=tk.RIGHT)
        
        # Time Condition Frame
        time_frame = tk.LabelFrame(left_sidebar, text="KONDISI WAKTU", 
                                  font=("Arial", 14, "bold"),
                                  bg="#e5e5e5", fg="#000000", padx=10, pady=10)
        time_frame.pack(fill=tk.X, padx=20, pady=10)
        
        time_0710_frame = tk.Frame(time_frame, bg="#e5e5e5")
        time_0710_frame.pack(fill=tk.X, pady=5)
        tk.Label(time_0710_frame, text="> 07:10:", 
                font=("Arial", 12), fg="#000000", bg="#e5e5e5").pack(side=tk.LEFT)
        self.time_0710_label = tk.Label(time_0710_frame, text="BELUM", 
                                       font=("Arial", 12), 
                                       fg="#e74c3c", bg="#e5e5e5")
        self.time_0710_label.pack(side=tk.RIGHT)
        
        time_1950_frame = tk.Frame(time_frame, bg="#e5e5e5")
        time_1950_frame.pack(fill=tk.X, pady=5)
        tk.Label(time_1950_frame, text="> 19:50:", 
                font=("Arial", 12), fg="#000000", bg="#e5e5e5").pack(side=tk.LEFT)
        self.time_1950_label = tk.Label(time_1950_frame, text="BELUM", 
                                       font=("Arial", 12), 
                                       fg="#e74c3c", bg="#e5e5e5")
        self.time_1950_label.pack(side=tk.RIGHT)
        
        # Right Frame - Video Display (70%)
        right_frame = tk.Frame(main_frame, bg="#34495e")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Video Label
        self.video_label = tk.Label(right_frame, bg="black", text="Loading video...", 
                                   font=("Arial", 16), fg="white")
        self.video_label.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Video Controls
        controls_frame = tk.Frame(right_frame, bg="#34495e")
        controls_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        tk.Button(controls_frame, text="CAPTURE MANUAL", command=self.manual_capture,
                 bg="#3498db", fg="white", font=("Arial", 10, "bold"), width=15).pack(side=tk.RIGHT, padx=5)
        tk.Button(controls_frame, text="OPEN MEDIA FOLDER", command=self.open_media_folder,
                 bg="#9b59b6", fg="white", font=("Arial", 10, "bold"), width=15).pack(side=tk.RIGHT, padx=5)
        
        # History Frame
        history_frame = tk.LabelFrame(right_frame, text="RIWAYAT CAPTURE", 
                                     font=("Arial", 12, "bold"),
                                     bg="#34495e", fg="white", padx=10, pady=10)
        history_frame.pack(fill=tk.BOTH, padx=10, pady=(0, 10))
        
        # Scrollable history
        history_canvas = tk.Canvas(history_frame, bg="#2c3e50", height=150, highlightthickness=0)
        scrollbar = ttk.Scrollbar(history_frame, orient="vertical", command=history_canvas.yview)
        self.history_scroll_frame = tk.Frame(history_canvas, bg="#2c3e50")
        
        history_canvas.configure(yscrollcommand=scrollbar.set)
        history_canvas.create_window((0, 0), window=self.history_scroll_frame, anchor="nw")
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        history_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.history_scroll_frame.bind("<Configure>", 
            lambda e: history_canvas.configure(scrollregion=history_canvas.bbox("all")))
        
        # Footer
        footer_frame = tk.Frame(self.root, bg="#5379ec", height=40)
        footer_frame.pack(fill=tk.X, side=tk.BOTTOM)
        footer_frame.pack_propagate(False)
        
        tk.Label(footer_frame, text="SISTEM DETEKSI HLA v1.0 | © 2024 PT. OTICS", 
                font=("Arial", 10), fg="white", bg="#5379ec").pack(side=tk.LEFT, padx=20)
        
        self.detection_info_label = tk.Label(footer_frame, text="Part: None | Total Required: 0", 
                                            font=("Arial", 10), fg="white", bg="#5379ec")
        self.detection_info_label.pack(side=tk.RIGHT, padx=20)
        
    def update_time(self):
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.time_label.config(text=current_time)
        self.root.after(1000, self.update_time)
        
    def update_gui_stats(self):
        # Update counters
        self.ok_counter_label.config(text=str(self.oke_counter))
        self.ng_counter_label.config(text=str(self.ng_counter))
        self.hla_count_label.config(text=str(self.total_hla_count))
        
        # Update alarm status
        if self.alarm_counter == 1:
            self.alarm_label.config(text="ACTIVE", fg="#e74c3c")
        else:
            self.alarm_label.config(text="INACTIVE", fg="#2ecc71")
        
        # Update system status
        self.system_status_label.config(text=self.status_text)
        if "OK" in self.status_text or "SUCCESS" in self.status_text:
            self.system_status_label.config(fg="#2ecc71")
        elif "NG" in self.status_text or "FAIL" in self.status_text:
            self.system_status_label.config(fg="#e74c3c")
        else:
            self.system_status_label.config(fg="yellow")
        
        # Update time conditions
        if self.time_condition_met_0710:
            self.time_0710_label.config(text="TERPENUHI", fg="#2ecc71")
        else:
            self.time_0710_label.config(text="BELUM", fg="#e74c3c")
            
        if self.time_condition_met_1950:
            self.time_1950_label.config(text="TERPENUHI", fg="#2ecc71")
        else:
            self.time_1950_label.config(text="BELUM", fg="#e74c3c")
        
        # Update detection info
        part_info = f"Part: {self.active_part} | Total Required: {self.total_hla if self.total_hla else 0}"
        self.detection_info_label.config(text=part_info)
        
        self.root.after(100, self.update_gui_stats)
        
    def update_history_display(self):
        # Clear current history display
        for widget in self.history_scroll_frame.winfo_children():
            widget.destroy()
        
        # Display last 8 captures (reverse order - newest first)
        for idx, record in enumerate(reversed(self.capture_history[-8:])):
            frame = tk.Frame(self.history_scroll_frame, bg="#34495e", padx=10, pady=5)
            frame.pack(fill=tk.X, padx=5, pady=2)
            
            timestamp = record["Timestamp"]
            count = record["Total HLA"]
            status = record["Status"]
            
            # Format timestamp for display
            display_time = f"{timestamp[8:10]}:{timestamp[10:12]}:{timestamp[12:14]}"
            
            color = "#2ecc71" if status == "OK" else "#e74c3c"
            
            tk.Label(frame, text=f"{display_time}", 
                    font=("Arial", 9), fg="white", bg="#34495e", width=10).pack(side=tk.LEFT)
            tk.Label(frame, text=f"HLA: {count}", 
                    font=("Arial", 9, "bold"), fg="#3498db", bg="#34495e", width=8).pack(side=tk.LEFT, padx=10)
            tk.Label(frame, text=status, 
                    font=("Arial", 9, "bold"), fg=color, bg="#34495e", width=8).pack(side=tk.RIGHT)
            
    def update_video_frame(self):
        try:
            if not self.frame_queue.empty():
                frame = self.frame_queue.get_nowait()
                
                # Convert frame to PhotoImage
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame_pil = Image.fromarray(frame_rgb)
                
                # Resize to fit label
                label_width = self.video_label.winfo_width()
                label_height = self.video_label.winfo_height()
                if label_width > 1 and label_height > 1:
                    frame_pil = frame_pil.resize((label_width, label_height), Image.Resampling.LANCZOS)
                
                frame_tk = ImageTk.PhotoImage(frame_pil)
                
                # Update video label
                self.video_label.config(image=frame_tk, text="")
                self.video_label.image = frame_tk
        except:
            pass
        
        self.root.after(30, self.update_video_frame)
        
    def on_reset_button_click(self):
        """Handle reset button click - sends reset command via MQTT"""
        data = "data_reset,1,1,1,1,1,1,1,1,1,1,#"
        try:
            self.client.publish(MQTT_TOPIC_SUB, data)
            print(f"Data '{data}' sent to topic '{MQTT_TOPIC_SUB}'")
            
            # Also reset conditions locally
            self.reset_conditions()
            
            messagebox.showinfo("Reset Berhasil", "Sistem kamera berhasil direset!")
        except Exception as e:
            print(f"Error sending reset command: {e}")
            messagebox.showerror("Error", f"Gagal mengirim reset command: {e}")
        
    def reset_conditions(self):
        """Reset kondisi tanpa mengubah oke_counter"""
        # Kirim data reset ke MQTT
        self.client.publish(MQTT_TOPIC_PUB, "data_result,1,1,1,1,1,1,1,1,1,1,#")
        
        # Reset variabel kondisi
        self.alarm_counter = 0
        self.total_hla_count = 0
        self.previous_hla_count = 0
        self.last_capture_time = 0
        self.parsed_data = None
        self.time_condition_met_0710 = False
        self.time_condition_met_1950 = False
        
        self.status_text = "SYSTEM RESET"
        
        print("[INFO] Conditions reset (except oke_counter)")
        print(f"[INFO] oke_counter tetap: {self.oke_counter}")
        
    def start_system(self):
        # Start MQTT
        self.setup_mqtt()
        
        # Load YOLO model
        try:
            self.model = YOLO(MODEL_PATH)
            print("[INFO] YOLO model loaded successfully")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load YOLO model: {e}")
            return
            
        # Start video stream
        self.start_video_stream()
        
        # Start GUI updates
        self.update_gui_stats()
        self.update_video_frame()
        
        # Start detection thread
        detection_thread = threading.Thread(target=self.detection_loop, daemon=True)
        detection_thread.start()
        
    def setup_mqtt(self):
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.client.loop_start()
            self.mqtt_status_label.config(text="Connected", fg="#2ecc71")
        except Exception as e:
            print(f"[ERROR] MQTT Connection failed: {e}")
            self.mqtt_status_label.config(text=f"Error: {str(e)[:20]}", fg="#e74c3c")
            
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT broker")
            client.subscribe(MQTT_TOPIC_SUB)
            self.mqtt_status_label.config(text="Connected", fg="#2ecc71")
        else:
            print(f"Connection failed with code {rc}")
            self.mqtt_status_label.config(text="Failed", fg="#e74c3c")
            
    def on_message(self, client, userdata, msg):
        self.parsed_data = self.parse_message(msg.payload.decode('utf-8'))
        if self.parsed_data is not None:
            print("Parsed Data:", self.parsed_data)
            
            # Check time conditions
            self.check_and_reset_time_conditions()
            
            # Handle reset message
            if msg.payload.decode('utf-8').startswith("data_reset,"):
                self.reset_conditions()
                
    def parse_message(self, message):
        if message.startswith("data_judg,"):
            data_string = message[len("data_judg,"):].rstrip('#')
            data_values = data_string.split(',')
            parsed_data = []
            for value in data_values:
                if value:
                    parsed_data.append(int(value))
            return parsed_data
        elif message.startswith("data_reset,"):
            data_string = message[len("data_reset,"):].rstrip('#')
            data_values = data_string.split(',')
            parsed_data = []
            for value in data_values:
                if value:
                    parsed_data.append(int(value))
            return parsed_data
        else:
            print("Invalid message format.")
            return None
            
    def check_and_reset_time_conditions(self):
        if self.parsed_data and len(self.parsed_data) >= 9:
            hour = self.parsed_data[6]
            minute = self.parsed_data[7]
            
            total_minutes = hour * 60 + minute
            
            # Check condition for > 07:10
            if total_minutes > (7 * 60 + 10):
                if not self.time_condition_met_0710:
                    print(f"[TIME CONDITION] Time > 07:10 detected ({hour:02d}:{minute:02d}). Setting oke_counter to 1")
                    self.oke_counter = 1
                    self.time_condition_met_0710 = True
                    self.time_condition_met_1950 = False
                    
            # Check condition for > 19:50
            elif total_minutes > (19 * 60 + 50):
                if not self.time_condition_met_1950:
                    print(f"[TIME CONDITION] Time > 19:50 detected ({hour:02d}:{minute:02d}). Setting oke_counter to 1")
                    self.oke_counter = 1
                    self.time_condition_met_1950 = True
                    self.time_condition_met_0710 = False
                    
            elif total_minutes <= (7 * 60 + 10):
                self.time_condition_met_0710 = False
                self.time_condition_met_1950 = False
                
            elif total_minutes <= (19 * 60 + 50):
                self.time_condition_met_1950 = False
                
    def start_video_stream(self):
        rtsp_url = None
        for path in COMMON_PATHS:
            if self.test_stream(path):
                print(f"[INFO] Stream path found: {path}")
                rtsp_url = RTSP_BASE_URL + path
                break
                
        if rtsp_url:
            self.camera_stream = VideoStream(rtsp_url).start()
            time.sleep(2.0)
            print("[INFO] Video stream started")
            self.camera_status_label.config(text="Connected", fg="#2ecc71")
        else:
            messagebox.showerror("Error", "No valid stream path found")
            self.camera_status_label.config(text="Not Connected", fg="#e74c3c")
            
    def test_stream(self, path):
        rtsp_url = RTSP_BASE_URL + path
        vs = VideoStream(rtsp_url).start()
        time.sleep(2.0)
        frame = vs.read()
        vs.stop()
        return frame is not None
        
    def define_detection_area(self, frame_shape):
        height, width = frame_shape[:2]
        x_margin = int(width * AREA_MARGIN)
        y_margin = int(height * AREA_MARGIN)
        x_start = x_margin
        y_start = y_margin
        x_end = width - x_margin
        y_end = height - y_margin
        return (x_start, y_start, x_end, y_end)
        
    def is_in_detection_area(self, bbox, detection_area):
        x1, y1, x2, y2 = bbox[:4]
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        area_x_start, area_y_start, area_x_end, area_y_end = detection_area
        return (area_x_start <= center_x <= area_x_end and 
                area_y_start <= center_y <= area_y_end)
                
    def detection_loop(self):
        while self.running and self.camera_stream:
            frame = self.camera_stream.read()
            if frame is None:
                time.sleep(0.1)
                continue
                
            # Store original frame
            original_frame = frame.copy()
            
            # Define detection area
            self.detection_area = self.define_detection_area(frame.shape)
            
            try:
                results = self.model(frame, conf=0.5)
                detected_objects = results[0].boxes.data.cpu().numpy()
                
                class_counts = {class_name: 0 for class_name in CLASS_NAMES}
                
                for obj in detected_objects:
                    if int(obj[5]) < len(CLASS_NAMES):
                        class_name = CLASS_NAMES[int(obj[5])]
                        
                        if class_name == 'hla':
                            if self.is_in_detection_area(obj, self.detection_area):
                                class_counts[class_name] += 1
                        else:
                            class_counts[class_name] += 1
                            
                self.total_hla_count = class_counts['hla']
                off_count = class_counts['off']
                adm_export_count = class_counts['108_pcs_hla']
                tmmin1l_count = class_counts['80_pcs_hla']
                tmmin1e_count = class_counts['88_pcs_hla']
                hla_terlentang_count = class_counts['hla_terlentang']
                hla_terbalik_count = class_counts['hla_terbalik']
                
                if adm_export_count > 0:
                    self.active_part, self.total_hla = "ADM Export", 108
                elif tmmin1l_count > 0:
                    self.active_part, self.total_hla = "tmmin-1L", 80
                elif tmmin1e_count > 0:
                    self.active_part, self.total_hla = "tmmin-1E", 88
                elif off_count > 0:
                    self.active_part = "OFF"
                    print("MESIN DIMATIKAN")
                else:
                    self.active_part = "None"
                    self.total_hla = None
                    
                # Process judgment logic
                self.process_judgment_logic(original_frame, class_counts)
                
                # Create annotated frame for display
                annotated_frame = results[0].plot(line_width=1, labels=True, conf=True)
                
                # Draw detection area
                if self.detection_area:
                    x_start, y_start, x_end, y_end = self.detection_area
                    cv2.rectangle(annotated_frame, (x_start, y_start), (x_end, y_end), (0, 255, 255), 3)
                    cv2.putText(annotated_frame, "AREA DETEKSI", (x_start + 10, y_start + 30), 
                               cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
                    
                # Add status text
                status_color = (0, 255, 0) if "OK" in self.status_text else (0, 0, 255) if "NG" in self.status_text else (0, 255, 255)
                cv2.putText(annotated_frame, f"Status: {self.status_text}", (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, status_color, 2)
                cv2.putText(annotated_frame, f"HLA: {self.total_hla_count}", (10, 70), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
                           
                # Put frame in queue for GUI update
                try:
                    self.frame_queue.put_nowait(annotated_frame)
                except:
                    pass
                    
            except Exception as e:
                print(f"[ERROR] Detection error: {e}")
                
            time.sleep(0.1)
            
    def process_judgment_logic(self, original_frame, class_counts):
        if self.total_hla is not None and self.parsed_data is not None and self.parsed_data[1] == 1:
            timestamp = f"{self.parsed_data[3]:04d}{self.parsed_data[4]:02d}{self.parsed_data[5]:02d}_{self.parsed_data[6]:02d}{self.parsed_data[7]:02d}{self.parsed_data[8]:02d}"
            
            hla_terlentang_count = class_counts['hla_terlentang']
            hla_terbalik_count = class_counts['hla_terbalik']
            
            if hla_terlentang_count > 0 or hla_terbalik_count > 0:
                self.client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,0,#")
                self.status_text = "NG - HLA Terbalik/Terlentang"
                
            if self.total_hla_count == self.total_hla:
                self.client.publish(MQTT_TOPIC_PUB, "data_result,1,1,1,1,1,1,1,1,1,1,#")
                self.status_text = "JUDGMENT: OK"
                
                if (time.time() - self.last_capture_time) >= self.capture_cooldown:
                    self.oke_counter += 1
                    self.capture_image(original_frame, timestamp, "OK")
                    self.last_capture_time = time.time()
                    self.update_history_display()
                    
            elif self.total_hla_count != self.total_hla:
                self.client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,0,#")
                self.alarm_counter = 1
                self.status_text = "JUDGMENT: NG"
                self.ng_counter += 1
                self.capture_image(original_frame, timestamp, "NG")
                self.update_history_display()
                
            self.parsed_data[1] = 0
            
    def capture_image(self, frame, timestamp, result_status):
        # Create folders if they don't exist
        os.makedirs(OK_FOLDER, exist_ok=True)
        os.makedirs(NG_FOLDER, exist_ok=True)
        
        # Get date folder name
        if self.parsed_data and len(self.parsed_data) >= 6:
            year = self.parsed_data[3]
            month = self.parsed_data[4]
            day = self.parsed_data[5]
            date_folder = f"{year}_{month:02d}_{day:02d}"
        else:
            date_folder = datetime.now().strftime("%Y_%m_%d")
            
        # Create save path
        base_folder = OK_FOLDER if result_status == "OK" else NG_FOLDER
        date_folder_path = os.path.join(base_folder, date_folder)
        os.makedirs(date_folder_path, exist_ok=True)
        
        image_path = os.path.join(date_folder_path, f"hla_capture_{timestamp}.jpg")
        cv2.imwrite(image_path, frame)
        
        # Add to history
        self.capture_history.append({
            "Timestamp": timestamp,
            "Total HLA": self.total_hla_count,
            "Status": result_status,
            "ImagePath": image_path
        })
        
        if len(self.capture_history) > 30:
            self.capture_history.pop(0)
            
        print(f"[INFO] Image captured: {image_path}")
        
    def manual_capture(self):
        if self.camera_stream:
            frame = self.camera_stream.read()
            if frame is not None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                self.capture_image(frame, timestamp, "MANUAL")
                messagebox.showinfo("Capture Berhasil", f"Gambar berhasil disimpan: {timestamp}")
                
    def open_media_folder(self):
        if os.path.exists(MEDIA_FOLDER):
            try:
                if os.name == 'nt':  # Windows
                    os.startfile(MEDIA_FOLDER)
                elif os.name == 'posix':  # Linux, macOS
                    os.system(f'xdg-open "{MEDIA_FOLDER}"')
            except:
                messagebox.showinfo("Folder Media", f"Lokasi folder: {os.path.abspath(MEDIA_FOLDER)}")
        else:
            messagebox.showinfo("Folder Media", "Folder media belum dibuat. Sistem akan membuatnya saat capture pertama.")
            os.makedirs(MEDIA_FOLDER, exist_ok=True)
                
    def on_closing(self):
        if messagebox.askokcancel("Keluar", "Apakah Anda yakin ingin keluar dari aplikasi?"):
            self.running = False
            if self.camera_stream:
                self.camera_stream.stop()
            if self.client:
                self.client.loop_stop()
            self.root.destroy()

def main():
    # Create media folders
    os.makedirs(OK_FOLDER, exist_ok=True)
    os.makedirs(NG_FOLDER, exist_ok=True)
    
    root = tk.Tk()
    app = HLA_Detector_GUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()