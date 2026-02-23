# OTICS_INDONESIA
#wanda
#IAA29


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



# Menggunakan 60% dari tengah frame (30% dari setiap sisi)
AREA_PERCENTAGE_HEIGHT = 0.8
AREA_MARGIN_HEIGHT = (1 - AREA_PERCENTAGE_HEIGHT) / 2


AREA_PERCENTAGE_WIDTH = 0.5
AREA_MARGIN_WIDTH = (1 - AREA_PERCENTAGE_WIDTH) / 2



# Initialize MQTT Client
client = mqtt.Client()

# Global Variables
total_hla = None
active_part = "None"
total_hla_count = 0
previous_hla_count = 0
condition_button = 0
status_text = "Stanby"
status_color = (255, 255, 255)
last_status = "READY"
oke_counter = 0
ng_counter = 0
alarm_counter = 0
capture_history = []
last_capture_time = 0
capture_cooldown = 60
parsed_data = None
judgment_cooldown = 60
last_judgment = 0

# Time condition flags
time_condition_met_0710 = False
time_condition_met_1950 = False

def parse_message(message):
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

def reset_conditions():
    """Reset kondisi tanpa mengubah oke_counter"""
    global total_hla_count, previous_hla_count, alarm_counter, last_capture_time, parsed_data
    global time_condition_met_0710, time_condition_met_1950
    
    # Kirim data reset ke MQTT
    client.publish(MQTT_TOPIC_PUB, "data_result,1,1,1,1,1,1,1,1,1,1,#")
    
    # Reset variabel kondisi
    alarm_counter = 0
    total_hla_count = 0
    previous_hla_count = 0
    last_capture_time = 0
    parsed_data = None
    
    # Reset time condition flags
    time_condition_met_0710 = False
    time_condition_met_1950 = False
    
    print("[INFO] Conditions reset (except oke_counter)")
    print(f"[INFO] oke_counter tetap: {oke_counter}")

def check_and_reset_time_conditions(parsed_data):
    """Check if time is > 07:10 or > 19:50 and reset oke_counter to 1 if condition is met"""
    global oke_counter, time_condition_met_0710, time_condition_met_1950
    
    if parsed_data and len(parsed_data) >= 9:
        hour = parsed_data[6]
        minute = parsed_data[7]
        
        # Convert to total minutes for comparison
        total_minutes = hour * 60 + minute
        
        # Check condition for > 07:10
        if total_minutes > (7 * 60 + 10):
            if not time_condition_met_0710:
                print(f"[TIME CONDITION] Time > 07:10 detected ({hour:02d}:{minute:02d}). Setting oke_counter to 1")
                oke_counter = 0
                time_condition_met_0710 = True
                # Reset 19:50 flag for next cycle
                time_condition_met_1950 = False
        
        # Check condition for > 19:50
        elif total_minutes > (19 * 60 + 50):
            if not time_condition_met_1950:
                print(f"[TIME CONDITION] Time > 19:50 detected ({hour:02d}:{minute:02d}). Setting oke_counter to 1")
                oke_counter = 0
                time_condition_met_1950 = True
                # Reset 07:10 flag for next cycle
                time_condition_met_0710 = False
        
        # If time is between 00:00 and 07:10, reset flags for next cycle
        elif total_minutes <= (7 * 60 + 10):
            time_condition_met_0710 = False
            time_condition_met_1950 = False
        
        # If time is between 07:10 and 19:50, ensure 07:10 flag is set
        elif total_minutes <= (19 * 60 + 50):
            time_condition_met_1950 = False

def get_date_folder_name(parsed_data):
    """Create folder name based on date in format year_month_day"""
    if parsed_data and len(parsed_data) >= 6:
        year = parsed_data[3]
        month = parsed_data[4]
        day = parsed_data[5]
        return f"{year}_{month:02d}_{day:02d}"
    return datetime.now().strftime("%Y_%m_%d")

def define_detection_area(frame_shape):
    """Define the central detection area based on frame dimensions"""
    height, width = frame_shape[:2]
    
    # Calculate margins
    x_margin = int(width * AREA_MARGIN_WIDTH)
    y_margin = int(height * AREA_MARGIN_HEIGHT)
    
    # Define area coordinates
    x_start = x_margin
    y_start = y_margin
    x_end = width - x_margin
    y_end = height - y_margin
    
    return (x_start, y_start, x_end, y_end)

def is_in_detection_area(bbox, detection_area):
    """Check if bounding box center is within the detection area"""
    x1, y1, x2, y2 = bbox[:4]
    
    # Calculate center of bounding box
    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2
    
    # Get detection area boundaries
    area_x_start, area_y_start, area_x_end, area_y_end = detection_area
    
    # Check if center is within detection area
    return (area_x_start <= center_x <= area_x_end and 
            area_y_start <= center_y <= area_y_end)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to broker")
        client.subscribe(MQTT_TOPIC_SUB)
    else:
        print("Connection failed with code", rc)

def on_message(client, userdata, msg):
    global parsed_data
    message_content = msg.payload.decode('utf-8')
    parsed_data = parse_message(message_content)
    
    if parsed_data is not None:
        print("Parsed Data:", parsed_data)
        
        # Check and reset time conditions when new data arrives
        check_and_reset_time_conditions(parsed_data)
        
        # Hanya panggil reset_conditions jika itu adalah data reset
        if message_content.startswith("data_reset,"):
            reset_conditions()

def test_stream(path):
    rtsp_url = RTSP_BASE_URL + path
    vs = VideoStream(rtsp_url).start()
    time.sleep(2.0)
    frame = vs.read()
    vs.stop()
    return frame is not None

def capture_image(original_frame, timestamp, result_status, parsed_data, detection_results):
    """Capture image with detection boxes (without labels) and save in date-based folder"""
    # Define colors for each class (BGR format)
    CLASS_COLORS = {
        'hla': (255, 0, 0),           # Blue
        'off': (0, 255, 255),         # Yellow
        'altar': (255, 255, 0),       # Cyan
        'box_after': (255, 0, 255),   # Magenta
        '108_pcs_hla': (0, 165, 255), # Orange
        '80_pcs_hla': (0, 255, 0),    # Green (biar tidak bentrok)
        '88_pcs_hla': (128, 0, 128),  # Purple
        'hla_terlentang': (0, 0, 255),# Red
        'hla_terbalik': (0, 0, 200),  # Dark Red
        'tray': (192, 192, 192)       # Silver
    }

    
    # Get date-based folder name
    date_folder_name = get_date_folder_name(parsed_data)
    
    # Create the appropriate save folder path
    base_save_folder = OK_FOLDER if result_status == "OK" else NG_FOLDER
    
    # Create date-based subfolder
    date_save_folder = os.path.join(base_save_folder, date_folder_name)
    
    # Ensure the date folder exists
    os.makedirs(date_save_folder, exist_ok=True)
    
    # Create image save path
    image_save_path = os.path.join(date_save_folder, f"hla_capture_{timestamp}.jpg")
    
    print(f"[INFO] Capturing image with detection boxes: {image_save_path}")
    
    # Create a copy of the original frame
    frame_to_save = original_frame.copy()
    
    # Draw detection boxes without labels
    if detection_results is not None and hasattr(detection_results[0], 'boxes'):
        boxes = detection_results[0].boxes
        
        for box in boxes:
            # Get box coordinates (x1, y1, x2, y2)
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
            
            # Get confidence score
            conf = float(box.conf[0])
            
            # Get class ID
            cls_id = int(box.cls[0])
            
            # Only draw boxes for objects with confidence > 0.5
            if conf > 0.5 and cls_id < len(CLASS_NAMES):
                class_name = CLASS_NAMES[cls_id]
                
                # Get color for this class, default to white if not found
                color = CLASS_COLORS.get(class_name, (255, 255, 255))
                
                # Draw rectangle (thickness of 2)
                cv2.rectangle(frame_to_save, (x1, y1), (x2, y2), color, 2)
                
                # Optional: Draw class name without confidence
                # cv2.putText(frame_to_save, class_name, (x1, y1-10), 
                #            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    
    # Save the frame with detection boxes
    cv2.imwrite(image_save_path, frame_to_save)
    print(f"[INFO] Image with detection boxes saved to {image_save_path}")
    
    return image_save_path




def update_capture_history(hla_count, timestamp, status, image_path):
    """Update capture history with image path"""
    capture_history.append({
        "Timestamp": timestamp, 
        "Total HLA": hla_count, 
        "Status": status,
        "ImagePath": image_path
    })
    if len(capture_history) > 30:
        capture_history.pop(0)

# Setup
try:
    subprocess.Popen(["python3", "/home/otics/on/button_reset.py"])
except Exception as e:
    print(f"[ERROR] Failed to start button_reset.py: {e}")
    traceback.print_exc()

client.on_connect = on_connect
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_start()

try:
    model = YOLO(MODEL_PATH)
except Exception as e:
    print(f"[ERROR] Error loading YOLO model: {e}")
    exit()

# Create base folders (date subfolders will be created dynamically)
os.makedirs(OK_FOLDER, exist_ok=True)
os.makedirs(NG_FOLDER, exist_ok=True)

rtsp_url = None
for path in COMMON_PATHS:
    if test_stream(path):
        print(f"[INFO] Stream path found: {path}")
        rtsp_url = RTSP_BASE_URL + path
        break
else:
    print("[ERROR] No valid stream path found")
    exit()

print("[INFO] Starting video stream...")
camera_stream = VideoStream(rtsp_url).start()

# Main Loop
try:
    while True:
        time.sleep(0.1)
        frame = camera_stream.read()
        if frame is None:
            break
        
        # Store original frame for clean capture
        original_frame = frame.copy()
        
        # Define detection area for this frame
        detection_area = define_detection_area(frame.shape)
        
        try:
            results = model(frame, conf=0.5)
            detected_objects = results[0].boxes.data.cpu().numpy()
            
            # Initialize counters
            class_counts = {class_name: 0 for class_name in CLASS_NAMES}
            
            # Count detected objects
            for obj in detected_objects:
                if int(obj[5]) < len(CLASS_NAMES):
                    class_name = CLASS_NAMES[int(obj[5])]
                    
                    # Special handling for HLA: only count if in detection area
                    if class_name == 'hla':
                        if is_in_detection_area(obj, detection_area):
                            class_counts[class_name] += 1
                        else:
                            # HLA detected but outside detection area
                            pass
                    else:
                        # For other classes, count all detections
                        class_counts[class_name] += 1

            hla_count = class_counts['hla']
            off_count = class_counts['off']
            altar_count = class_counts['altar']
            box_after_count = class_counts['box_after']
            adm_export_count = class_counts['108_pcs_hla']
            tmmin1l_count = class_counts['80_pcs_hla']
            tmmin1e_count = class_counts['88_pcs_hla']
            hla_terlentang_count = class_counts['hla_terlentang']
            hla_terbalik_count = class_counts['hla_terbalik']

            if adm_export_count > 0:
                active_part, total_hla = "ADM Export", 108
            elif tmmin1l_count > 0:
                active_part, total_hla = "tmmin-1L", 80
            elif tmmin1e_count > 0:
                active_part, total_hla = "tmmin-1E", 88
            elif off_count > 0:
                print("OFF -------------- MESIN DIMATIKAN..............")
            else:
                active_part = "None"

            print(f"Detected HLA: {hla_count}, OFF: {off_count}, Altar: {altar_count}, Box After: {box_after_count}")
            print(f"ADM Export: {adm_export_count}, tmmin-1l: {tmmin1l_count}, tmmin-1e: {tmmin1e_count}")
            print(f"HLA Terlentang: {hla_terlentang_count}, HLA Terbalik: {hla_terbalik_count}")
            print(f"Total HLA for judgment: {total_hla}")
            print(f"Condition_button: {condition_button}")
            print(f"Alarm Counter: {alarm_counter}")
            print(f"Last Status: {last_status}")
            print(f"Parsed Data: {parsed_data}")
            print(f"Oke Counter: {oke_counter}")
            print(f"Time Condition 07:10: {time_condition_met_0710}")
            print(f"Time Condition 19:50: {time_condition_met_1950}")
            print(f"Detection Area: {detection_area}")

            if total_hla is not None and parsed_data is not None and parsed_data[1] == 1:
                timestamp = f"{parsed_data[3]:04d}{parsed_data[4]:02d}{parsed_data[5]:02d}_{parsed_data[6]:02d}{parsed_data[7]:02d}{parsed_data[8]:02d}"
                
                # Check time conditions when judgment is received
                check_and_reset_time_conditions(parsed_data)
                
                if hla_terlentang_count > 0 or hla_terbalik_count > 0:
                    client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,0,#")
                    
                if hla_count == total_hla:
                    client.publish(MQTT_TOPIC_PUB, "data_result,1,1,1,1,1,1,1,1,1,1,#")
                    status_text, status_color, condition_button = "JUDGMENT: OFFLINE", (0, 0, 255), 0
                    
                    if (time.time() - last_capture_time) >= capture_cooldown:
                        status = "OKE"
                        
                        # Increment oke_counter for each successful judgment
                        oke_counter += 1
                        
                        # Send the current oke_counter value
                        client.publish(MQTT_TOPIC_PUB_INSERT, f"data_oke,1,1,1,{oke_counter},#")
                        
                        # Capture clean image and get the path
                        image_path = capture_image(original_frame, timestamp, "OK", parsed_data, results)
                        update_capture_history(hla_count, timestamp, status, image_path)
                        last_capture_time = time.time()
                    time.sleep(1)
                    
                elif hla_count != total_hla:
                    client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,0,#")
                    alarm_counter = 1
                    status = "NG"
                    ng_counter += 1
                    
                    # Capture clean image and get the path
                    image_path = capture_image(original_frame, timestamp, "NG", parsed_data, results)
                    update_capture_history(hla_count, timestamp, status, image_path)
                    time.sleep(1)
                
                parsed_data[1] = 0
                
            # Judgment Cooldown Logic
            if (time.time() - last_judgment) >= judgment_cooldown:
                if hla_count == 44:
                    status_text = "JUDGMENT: INTERLOCK"
                    status_color = (0, 255, 0)
                    condition_button = 1
                    print(f"Condition_button: {condition_button}")
                    last_judgment = time.time()
                    
            if hla_count == 0 and condition_button == 1:
                client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,0,#")
                status = "NG"
                time.sleep(1)
                
                # Add success/failure indicator at the top right corner
                indicator_text = "FAILURE"
                indicator_color = (0, 0, 255)
                cv2.rectangle(frame, (frame.shape[1] - 360, 20), (frame.shape[1] - 20, 90), indicator_color, -1)
                cv2.putText(frame, indicator_text, (frame.shape[1] - 350, 80), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 6)

                # Add new indicator with "NG PROSES!" text below the existing indicator
                ng_proses_text = "NG PROSES!"
                ng_proses_color = (0, 0, 255)
                ng_proses_y = 90 + 90
                cv2.rectangle(frame, (frame.shape[1] - 360, ng_proses_y), (frame.shape[1] - 20, ng_proses_y + 70), ng_proses_color, -1)
                cv2.putText(frame, ng_proses_text, (frame.shape[1] - 350, ng_proses_y + 50), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 6)
            
            if alarm_counter == 1:
                client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,0,#")
                time.sleep(1)
                
            # Create annotated frame for display only
            annotated_frame = results[0].plot(line_width=1, labels=True, conf=True)
            
            # Draw detection area on annotated frame
            x_start, y_start, x_end, y_end = detection_area
            cv2.rectangle(annotated_frame, (x_start, y_start), (x_end, y_end), (0, 255, 255), 3)
            cv2.putText(annotated_frame, "DETECTION AREA", (x_start + 10, y_start + 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
            
            sidebar_width = 600
            sidebar_color = (142, 112, 0)
            cv2.rectangle(annotated_frame, (0, 0), (sidebar_width, annotated_frame.shape[0]), sidebar_color, -1)
            red_bg_color = (0, 0, 255)
            white_text_color = (255, 255, 255)
            black_text_color = (0, 0, 0)
            font = cv2.FONT_HERSHEY_SIMPLEX
            
            # Display current oke_counter value
            cv2.rectangle(annotated_frame, (20, 30), (sidebar_width - 20, 100), red_bg_color, -1)
            cv2.putText(annotated_frame, f"Total Tray: {oke_counter}", (30, 80), font, 1.5, white_text_color, 5)
            
            # Display detection area info
            area_info_y = 120
            cv2.putText(annotated_frame, f"Detection Area: {int(AREA_PERCENTAGE_WIDTH*100)}%", 
                       (30, area_info_y), font, 0.7, white_text_color, 2)

            status_y = 90 + 15 + 50
            status_bg_color = (50, 50, 50)
            cv2.rectangle(annotated_frame, (annotated_frame.shape[1] - 360, status_y - 30), 
                         (annotated_frame.shape[1] - 20, status_y + 10), status_bg_color, -1)
            cv2.putText(annotated_frame, status_text, (annotated_frame.shape[1] - 350, status_y), 
                       font, 1.0, status_color, 2)

            # Display capture history
            history_start_y = 170
            for idx, record in enumerate(capture_history):
                timestamp = record["Timestamp"]
                count = record["Total HLA"]
                status = record["Status"]
                last_status = status
                
                # Shorten path for display (show only filename)
                image_filename = os.path.basename(record["ImagePath"]) if "ImagePath" in record else "N/A"
                
                history_text = f"{idx + 1}: {timestamp} | HLA: {count} | Status: {status}"
                text_position = (30, history_start_y + (idx * 30))
                (text_width, text_height), _ = cv2.getTextSize(history_text, font, 0.7, 2)
                
                if status == "NG":
                    cv2.rectangle(annotated_frame, (text_position[0] - 5, text_position[1] - text_height - 5),
                                (text_position[0] + text_width + 5, text_position[1] + 5), (0, 0, 139), -1)
                cv2.putText(annotated_frame, history_text, text_position, font, 0.7, white_text_color, 2)

            blue_bg_color_1 = (122, 52, 0)
            sidebar_bottom_y = annotated_frame.shape[0] - 100
            cv2.rectangle(annotated_frame, (20, sidebar_bottom_y - 50), (sidebar_width - 20, sidebar_bottom_y), blue_bg_color_1, -1)
            cv2.putText(annotated_frame, f"TRAY: {hla_count} PCS", (30, sidebar_bottom_y - 10), font, 1.5, white_text_color, 5)

            indicator_color = (255, 255, 0) if last_status == "READY" else (0, 255, 0) if last_status == "OKE" else (0, 0, 255)
            indicator_text = "READY" if last_status == "READY" else "SUCCESS" if last_status == "OKE" else "FAILURE"
            cv2.rectangle(annotated_frame, (annotated_frame.shape[1] - 360, 20), (annotated_frame.shape[1] - 20, 90), indicator_color, -1)
            cv2.putText(annotated_frame, indicator_text, (annotated_frame.shape[1] - 350, 80), font, 2.0, black_text_color, 6)

            andon_x = annotated_frame.shape[1] - 100
            andon_y = annotated_frame.shape[0] - 300
            andon_width = 80
            andon_height = 80
            cv2.rectangle(annotated_frame, (andon_x, andon_y + andon_height + 20), (andon_x + andon_width, andon_y + 2 * andon_height + 20), (0, 255, 255), -1)

            if last_status == "OKE":
                cv2.rectangle(annotated_frame, (andon_x, andon_y), (andon_x + andon_width, andon_y + andon_height), (0, 255, 0), -1)
                cv2.rectangle(annotated_frame, (andon_x, andon_y + 2 * (andon_height + 20)), (andon_x + andon_width, andon_y + 3 * andon_height + 40), (0, 0, 0), -1)
            elif last_status == "NG":
                cv2.rectangle(annotated_frame, (andon_x, andon_y), (andon_x + andon_width, andon_y + andon_height), (0, 0, 0), -1)
                cv2.rectangle(annotated_frame, (andon_x, andon_y + 2 * (andon_height + 20)), (andon_x + andon_width, andon_y + 3 * andon_height + 40), (0, 0, 255), -1)
            else:
                cv2.rectangle(annotated_frame, (andon_x, andon_y), (andon_x + andon_width, andon_y + andon_height), (0, 0, 0), -1)
                cv2.rectangle(annotated_frame, (andon_x, andon_y + 2 * (andon_height + 20)), (andon_x + andon_width, andon_y + 3 * andon_height + 40), (0, 0, 0), -1)

            frame_color = (184, 132, 0)
            frame_thickness = 20
            cv2.putText(annotated_frame, f"Part Dangae: {total_hla}", (30, annotated_frame.shape[0] - 60), font, 1.0, white_text_color, 3)
            cv2.rectangle(annotated_frame, (0, 0), (annotated_frame.shape[1] - 1, annotated_frame.shape[0] - 1), frame_color, frame_thickness)

            resized_frame = cv2.resize(annotated_frame, (1395, 770))
            cv2.imshow("Deteksi Part HLA - Area Terbatas", resized_frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        except Exception as e:
            print(f"[ERROR] Error in main loop: {e}")
            traceback.print_exc()
            continue

except Exception as e:
    print(f"[ERROR] Error in main loop: {e}")
    traceback.print_exc()

finally:
    try:
        camera_stream.stop()
        cv2.destroyAllWindows()
        client.loop_stop()
    except Exception as e:
        print(f"[ERROR] Error during cleanup: {e}")
        traceback.print_exc()