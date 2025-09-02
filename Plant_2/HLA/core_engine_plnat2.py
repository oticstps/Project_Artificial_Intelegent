# nais camai plant 2
# wanda


import paho.mqtt.client as mqtt
from imutils.video import VideoStream
from ultralytics import YOLO
from datetime import datetime
import cv2
import time
import os
import subprocess

mqtt_broker = "10.42.0.1"
mqtt_port = 1883
mqtt_topic_pub = "11220223_core_nais_result"
mqtt_topic_sub = "11220223_core_nais_judg"
media_folder = "/home/camaiplant2/Desktop/HASIL_DETEKSI_HLA"
capture_history = []
last_capture_time = 0
capture_cooldown = 60  # 1 minutes
parsed_data = None
total_hla = 192
oke_counter = 0
ng_counter = 0
status_text = "Standby"
status_color = (255, 255, 255)
last_status = "READY"
def parse_message(message):
    """Parse incoming MQTT message."""
    if message.startswith("data_judg,"):
        data_string = message[len("data_judg,"):].rstrip('#')
        data_values = data_string.split(',')
        parsed_data = []
        for value in data_values:
            if value:
                parsed_data.append(int(value))
        return parsed_data
    else:
        print("Invalid message format.")
        return None
def on_connect(client, userdata, flags, rc):
    """Callback for when the client receives a CONNACK response from the server."""
    if rc == 0:
        print("Connected to broker")
        client.subscribe(mqtt_topic_sub)
    else:
        print("Connection failed with code", rc)
def on_message(client, userdata, msg):
    """Callback for when a PUBLISH message is received from the server."""
    global parsed_data
    try:
        parsed_data = parse_message(msg.payload.decode('utf-8'))
        if parsed_data is not None:
            print("Parsed Data:", parsed_data)
    except Exception as e:
        print(f"[ERROR] Error parsing MQTT message: {e}")
# Initialize MQTT Client
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
try:
    client.connect(mqtt_broker, mqtt_port, 60)
    client.loop_start()
except Exception as e:
    print(f"[ERROR] MQTT connection failed: {e}")
    exit()
# Load YOLO Model
try:
    model = YOLO("/home/camaiplant2/on/best_31_03_2024_150_ym.pt")
    class_names = [
        'hla', 'hla_terlentang', 'hla_terbalik', 'kosong', 'p_tray_ng', 'p_tray_oke',
        'baud_hj', 'box_hla', 'tutup_spidol', 'tutup_pulpen_1', 'tutup_pulpen_2',
        'kanban', 'indikator_off'
    ]
except Exception as e:
    print(f"[ERROR] Error loading YOLO model: {e}")
    exit()

rtsp_base_url = "rtsp://admin:pt_otics1*@192.168.1.108"
print("[INFO] starting video stream...")
camera_stream = VideoStream(rtsp_base_url).start()
def capture_image(annotated_frame, timestamp, result_status, year, month, day):
    daily_folder = os.path.join(media_folder, f"{year:04d}-{month:02d}-{day:02d}")
    ok_folder = os.path.join(daily_folder, "OK")
    ng_folder = os.path.join(daily_folder, "NG")
    os.makedirs(ok_folder, exist_ok=True)
    os.makedirs(ng_folder, exist_ok=True)
    save_folder = ok_folder if result_status == "OK" else ng_folder
    image_save_path = os.path.join(save_folder, f"hla_capture_{timestamp}.jpg")
    print(f"[INFO] Capturing image: {image_save_path}")
    try:
        cv2.imwrite(image_save_path, annotated_frame)
        print(f"[INFO] Image saved to {image_save_path}")
    except Exception as e:
        print(f"[ERROR] Error saving image: {e}")
        
        
def update_capture_history(hla_count, timestamp, status):
    capture_history.append({"Timestamp": timestamp, "Total HLA": hla_count, "Status": status})
    if len(capture_history) > 30:
        capture_history.pop(0)
def draw_leds(frame, green_led_on, red_led_on, orange_led_on):
    led_width = 60
    led_height = 25
    led_position_x = 30
    led_position_y = [1200, 1240, 1280]
    colors = {
        "on": {
            "green": (0, 255, 0),
            "red": (0, 0, 255),
            "orange": (255, 165, 0)
        },
        "off": (50, 50, 50)
    }
    cv2.rectangle(frame, (led_position_x, led_position_y[0]), 
                  (led_position_x + led_width, led_position_y[0] + led_height), 
                  colors["on"]["green"] if green_led_on else colors["off"], -1)
    cv2.rectangle(frame, (led_position_x, led_position_y[1]), 
                  (led_position_x + led_width, led_position_y[1] + led_height), 
                  colors["on"]["red"] if red_led_on else colors["off"], -1)
    cv2.rectangle(frame, (led_position_x, led_position_y[2]), 
                  (led_position_x + led_width, led_position_y[2] + led_height), 
                  colors["on"]["orange"] if orange_led_on else colors["off"], -1)
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.6
    font_thickness = 2
    white_color = (255, 255, 255)
    cv2.putText(frame, "Hasil OKE", (led_position_x + led_width + 10, led_position_y[0] + led_height - 5), 
                font, font_scale, white_color, font_thickness)
    cv2.putText(frame, "Ada NG", (led_position_x + led_width + 10, led_position_y[1] + led_height - 5), 
                font, font_scale, white_color, font_thickness)
    cv2.putText(frame, "Running", (led_position_x + led_width + 10, led_position_y[2] + led_height - 5), 
                font, font_scale, white_color, font_thickness)
while True:
    time.sleep(0.1)
    try:
        frame = camera_stream.read()
        if frame is None:
            print("[ERROR] Unable to read frame from camera stream")
            break
        try:
            results = model(frame, conf=0.6)
        except Exception as e:
            print(f"[ERROR] Error during model inference: {e}")
            continue
        detected_objects = results[0].boxes.data.cpu().numpy()
        hla_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'hla')
        hla_terlentang_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'hla_terlentang')
        hla_terbalik_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'hla_terbalik')
        kosong_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'kosong')
        p_tray_ng_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'p_tray_ng')
        p_tray_oke_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'p_tray_oke')
        baud_hj_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'baud_hj')
        box_hla_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'box_hla')
        tutup_spidol_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'tutup_spidol')
        tutup_pulpen_1_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'tutup_pulpen_1')
        tutup_pulpen_2_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'tutup_pulpen_2')
        kanban_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'kanban')
        indikator_off_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'indikator_off')
        if indikator_off_count > 0:
            print("[INFO] 'indikator_off' detected. Shutting down the system in 2 seconds...")
            time.sleep(2)
            subprocess.call(['sudo', '/sbin/shutdown', '-h', 'now'])

        if total_hla is not None and parsed_data is not None and parsed_data[1] == 1:
            year = parsed_data[3]
            month = parsed_data[4]
            day = parsed_data[5]
            hour = parsed_data[6]
            minute = parsed_data[7]
            second = parsed_data[8]
            timestamp = f"{year:04d}{month:02d}{day:02d}_{hour:02d}{minute:02d}{second:02d}"
            if hla_count == total_hla:
                try:
                    client.publish(mqtt_topic_pub, "data_result,1,1,1,1,1,1,1,1,1,1,#")
                    status = "OK"
                    if (time.time() - last_capture_time) >= capture_cooldown:
                        print(f"Published data_result OK for total_hla={total_hla} to mqtt_topic_pub")
                        last_capture_time = time.time()
                        oke_counter += 1
                        update_capture_history(hla_count, timestamp, status)
                        capture_image(annotated_frame, timestamp, "OK", year, month, day)
                    time.sleep(1)
                except Exception as e:
                    print(f"[ERROR] Error publishing MQTT message: {e}")
            elif hla_count != total_hla:
                print(f"Published data_result NG for total_hla={total_hla} to mqtt_topic_pub")
                cv2.rectangle(annotated_frame, (annotated_frame.shape[1] - 360, 20), (annotated_frame.shape[1] - 20, 90), indicator_color, -1)
                cv2.putText(annotated_frame, indicator_text, (annotated_frame.shape[1] - 350, 80), font, 2.0, black_text_color, 6)
                status = "NG"
                update_capture_history(hla_count, timestamp, status)
                capture_image(annotated_frame, timestamp, "NG", year, month, day)
                try:
                    client.publish(mqtt_topic_pub, "data_result,0,0,0,0,0,0,0,0,0,0,#")
                    time.sleep(1)
                except Exception as e:
                    print(f"[ERROR] Error publishing MQTT message: {e}")
            parsed_data[1] = 0
            status = "OK" if hla_count == total_hla else "NG"
        
        
        annotated_frame = results[0].plot(
            line_width=1,
            labels=True,
            conf=False,
            font_size=0,
            font="Arial.ttf",
            pil=False,
            img=None
        )
        sidebar_width = 600
        sidebar_color = (142, 112, 0)
        cv2.rectangle(annotated_frame, (0, 0), (sidebar_width, annotated_frame.shape[0]), sidebar_color, -1)
        red_bg_color = (0, 155, 255)
        white_text_color = (255, 255, 255)
        black_text_color = (0, 0, 0)
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.rectangle(annotated_frame, (20, 30), (sidebar_width - 20, 100), red_bg_color, -1)
        cv2.putText(annotated_frame, f"Total Produksi: {oke_counter} Box", (30, 80), font, 1.5, black_text_color, 5)
        indicator_color = (255, 255, 0) if last_status == "READY" else (0, 255, 0) if last_status == "SUCCESS" else (0, 0, 255)
        indicator_text = "READY" if last_status == "READY" else "OK" if last_status == "FAILURE" else "NG"
        status_y = 90 + 15 + 50
        status_bg_color = (50, 50, 50)
        cv2.rectangle(annotated_frame, (annotated_frame.shape[1] - 360, 20), (annotated_frame.shape[1] - 20, 90), indicator_color, -1)
        cv2.putText(annotated_frame, indicator_text, (annotated_frame.shape[1] - 350, 80), font, 2.0, black_text_color, 6)
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
        cv2.putText(annotated_frame, f"Part: {hla_count} PCS", (30, sidebar_bottom_y - 10), font, 1.5, white_text_color, 5)
        if last_status == "READY":
            indicator_color = (255, 255, 0)
            indicator_text = "READY"
        else:
            indicator_color = (0, 255, 0) if last_status == "OK" else (0, 0, 255)
            indicator_text = last_status
        cv2.rectangle(annotated_frame, (annotated_frame.shape[1] - 360, 20), (annotated_frame.shape[1] - 20, 90), indicator_color, -1)
        cv2.putText(annotated_frame, indicator_text, (annotated_frame.shape[1] - 350, 80), font, 2.0, black_text_color, 6)
        andon_x = annotated_frame.shape[1] - 120
        andon_y = annotated_frame.shape[0] - 300
        andon_width = 80
        andon_height = 80
        cv2.rectangle(annotated_frame, (andon_x, andon_y + andon_height + 20), (andon_x + andon_width, andon_y + 2 * andon_height + 20), (0, 255, 255), -1)
        cv2.putText(annotated_frame, "RUNNING", (andon_x - 175, andon_y + andon_height + 80), font, 1.2, (255, 255, 255), 5)
        cv2.putText(annotated_frame, "OK", (andon_x - 90, andon_y + andon_height // 2 + 10), font, 1.2, (255, 255, 255), 5)
        cv2.putText(annotated_frame, "NG", (andon_x - 90, andon_y + 2 * andon_height + 40 + andon_height // 2 + 10), font, 1.2, (255, 255, 255), 5)
        if last_status == "OK":
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
        cv2.putText(annotated_frame, f"Standard pcs per box: {total_hla}", (30, annotated_frame.shape[0] - 60), font, 1.0, white_text_color, 3)
        cv2.rectangle(annotated_frame, (0, 0), (annotated_frame.shape[1] - 1, annotated_frame.shape[0] - 1), frame_color, frame_thickness)
        resized_frame = cv2.resize(annotated_frame, (1395, 770))
        cv2.imshow("Deteksi Part HLA", resized_frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
                                                                                                                 
    except Exception as e:
        print(f"[ERROR] Error sistem image: {e}")                                                                                                
        camera_stream.stop()
        cv2.destroyAllWindows()
        client.loop_stop()
