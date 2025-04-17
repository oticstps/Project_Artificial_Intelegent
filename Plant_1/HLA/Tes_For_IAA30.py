# adi


#IAA 30
# /home/camaiplant2/on/best.pt
# /home/otics/on/best.pt


import paho.mqtt.client as mqtt
from imutils.video import VideoStream
from ultralytics import YOLO
import cv2
import time
import os
import subprocess
import traceback

# Constants
#MQTT_BROKER = "192.168.170.246"
MQTT_BROKER = "10.42.0.1"

MQTT_PORT = 1883
MQTT_TOPIC_PUB = "11220223_core_nais_result"
MQTT_TOPIC_PUB_INSERT = "11220223_core_nais_insert"
MQTT_TOPIC_SUB = "11220223_core_nais_judg"
RTSP_BASE_URL = "rtsp://admin:pt_otics1*@192.168.1.108:554/cam/realmonitor?channel=1&subtype=0"
COMMON_PATHS = ["/cam/realmonitor?channel=1&subtype=0"]
MEDIA_FOLDER = "media"
OK_FOLDER = os.path.join(MEDIA_FOLDER, "OK")
NG_FOLDER = os.path.join(MEDIA_FOLDER, "NG")
MODEL_PATH = "/home/otics/on/best.pt"
CLASS_NAMES = ['hla', 'off', 'altar', 'box_after', '108_pcs_hla', '80_pcs_hla', '88_pcs_hla', 'hla_terlentang', 'hla_terbalik', 'tray']

# Initialize MQTT Client
client = mqtt.Client()

# Global Variables
# total_hla = None
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
judgment_cooldown = 60  # Cooldown untuk judgment (dalam detik)
last_judgment = 0  # Waktu terakhir judgment dilakukan


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
    global total_hla_count, previous_hla_count, alarm_counter, last_capture_time, parsed_data
    client.publish(MQTT_TOPIC_PUB, "data_result,1,1,1,1,1,1,1,1,1,1,#")
    alarm_counter = 0
    total_hla_count = 0
    previous_hla_count = 0
    last_capture_time = 0
    parsed_data = None
    print("[INFO] Conditions reset to initial state.")

    

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to broker")
        client.subscribe(MQTT_TOPIC_SUB)
    else:
        print("Connection failed with code", rc)

def on_message(client, userdata, msg):
    global parsed_data
    parsed_data = parse_message(msg.payload.decode('utf-8'))
    if parsed_data is not None:
        print("Parsed Data:", parsed_data)
        if msg.payload.decode('utf-8').startswith("data_reset,"):
            reset_conditions()

def test_stream(path):
    rtsp_url = RTSP_BASE_URL + path
    vs = VideoStream(rtsp_url).start()
    time.sleep(2.0)
    frame = vs.read()
    vs.stop()
    return frame is not None

def capture_image(annotated_frame, timestamp, result_status):
    save_folder = OK_FOLDER if result_status == "OK" else NG_FOLDER
    image_save_path = os.path.join(save_folder, f"hla_capture_{timestamp}.jpg")
    print(f"[INFO] Capturing image: {image_save_path}")
    cv2.imwrite(image_save_path, annotated_frame)
    print(f"[INFO] Image saved to {image_save_path}")

def update_capture_history(hla_count, timestamp, status):
    capture_history.append({"Timestamp": timestamp, "Total HLA": hla_count, "Status": status})
    if len(capture_history) > 30:
        capture_history.pop(0)

# Setup
try:
    subprocess.Popen(["python", "/home/otics/on/button_reset.py"])
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
        try:
            results = model(frame, conf=0.7)
            detected_objects = results[0].boxes.data.cpu().numpy()
            class_counts = {class_name: 0 for class_name in CLASS_NAMES}

            for obj in detected_objects:
                if int(obj[5]) < len(CLASS_NAMES):
                    class_name = CLASS_NAMES[int(obj[5])]
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
            print(last_status)
            print(parsed_data)

            if total_hla is not None and parsed_data is not None and parsed_data[1] == 1:
                timestamp = f"{parsed_data[3]:04d}{parsed_data[4]:02d}{parsed_data[5]:02d}_{parsed_data[6]:02d}{parsed_data[7]:02d}{parsed_data[8]:02d}"
                if hla_terlentang_count > 0 or hla_terbalik_count > 0:
                    client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,0,#")
                if hla_count == total_hla:
                    client.publish(MQTT_TOPIC_PUB, "data_result,1,1,1,1,1,1,1,1,1,1,#")
                    status_text, status_color, condition_button = "JUDGMENT: OFFLINE", (0, 0, 255), 0
                    if (time.time() - last_capture_time) >= capture_cooldown:
                        status = "OKE"
                        oke_counter += 1
                        client.publish(MQTT_TOPIC_PUB_INSERT, f"data_oke,1,1,1,{oke_counter},#")
                        update_capture_history(hla_count, timestamp, status)
                        capture_image(results[0].plot(), timestamp, "OK")
                        last_capture_time = time.time()
                    time.sleep(1)
                    
                elif hla_count != total_hla:
                    client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,0,#")
                    alarm_counter = 1
                    status = "NG"
                    ng_counter += 1
                    update_capture_history(hla_count, timestamp, status)
                    capture_image(results[0].plot(), timestamp, "NG")
                    time.sleep(1)
                parsed_data[1] = 0
                
     
            # Judgment Cooldown Logic
            if (time.time() - last_judgment) >= judgment_cooldown:
                if hla_count == 44:
                    status_text = "JUDGMENT: INTERLOCK"
                    status_color = (0, 255, 0)
                    condition_button = 1
                    print(condition_button)
                    last_judgment = time.time()  # Update waktu terakhir judgment
            # Initialize last_status
            if hla_count == 0 and condition_button == 1:
                client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,0,#")
                status = "NG"
                time.sleep(1)
                
                # Add success/failure indicator at the top right corner
                indicator_text = "FAILURE"
                indicator_color = (0, 0, 255)  # Red for failure
                cv2.rectangle(annotated_frame, (annotated_frame.shape[1] - 360, 20), (annotated_frame.shape[1] - 20, 90), indicator_color, -1)
                cv2.putText(annotated_frame, indicator_text, (annotated_frame.shape[1] - 350, 80), font, 2.0, black_text_color, 6)

                # Add new indicator with "NG PROSES!" text below the existing indicator
                ng_proses_text = "NG PROSES!"
                ng_proses_color = (0, 0, 255)  # Red for NG PROSES!
                ng_proses_y = 90 + 90  # Position below the existing indicator
                cv2.rectangle(annotated_frame, (annotated_frame.shape[1] - 360, ng_proses_y), (annotated_frame.shape[1] - 20, ng_proses_y + 70), ng_proses_color, -1)
                cv2.putText(annotated_frame, ng_proses_text, (annotated_frame.shape[1] - 350, ng_proses_y + 50), font, 2.0, black_text_color, 6)
            
            
            if alarm_counter == 1:
                client.publish(MQTT_TOPIC_PUB, "data_result,0,0,0,0,0,0,0,0,0,0,#")
                time.sleep(1)
                
                
            annotated_frame = results[0].plot(line_width=1, labels=True, conf=True)
            sidebar_width = 600
            sidebar_color = (142, 112, 0)
            cv2.rectangle(annotated_frame, (0, 0), (sidebar_width, annotated_frame.shape[0]), sidebar_color, -1)
            red_bg_color = (0, 0, 255)
            white_text_color = (255, 255, 255)
            black_text_color = (0, 0, 0)
            font = cv2.FONT_HERSHEY_SIMPLEX
            cv2.rectangle(annotated_frame, (20, 30), (sidebar_width - 20, 100), red_bg_color, -1)
            cv2.putText(annotated_frame, f"TOTAL: {oke_counter} Tray", (30, 80), font, 1.5, white_text_color, 5)

            status_y = 90 + 15 + 50
            status_bg_color = (50, 50, 50)
            cv2.rectangle(annotated_frame, (annotated_frame.shape[1] - 360, status_y - 30), (annotated_frame.shape[1] - 20, status_y + 10), status_bg_color, -1)
            cv2.putText(annotated_frame, status_text, (annotated_frame.shape[1] - 350, status_y), font, 1.0, status_color, 2)

            history_start_y = 150
            for idx, record in enumerate(capture_history):
                timestamp, count = record["Timestamp"], record["Total HLA"]
                status = record["Status"]
                last_status = status
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
            cv2.imshow("Deteksi Part HLA", resized_frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        except Exception as e:
            print(f"[ERROR] Error in main loop: {e}")
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