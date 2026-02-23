import paho.mqtt.client as mqtt
from imutils.video import VideoStream
from ultralytics import YOLO
from datetime import datetime
import cv2
import time
import os


mqtt_broker = "192.168.150.225"
mqtt_port = 1883
mqtt_topic_pub = "11220223_core_nais_result"
mqtt_topic_sub = "11220223_core_nais_judg"

def parse_message(message):
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
    if rc == 0:
        print("Connected to broker")
        client.subscribe(mqtt_topic_sub)
    else:
        print("Connection failed with code", rc)



def on_message(client, userdata, msg):
    global parsed_data
    parsed_data = parse_message(msg.payload.decode('utf-8'))
    if parsed_data is not None:
        print("Parsed Data:", parsed_data)




client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect(mqtt_broker, mqtt_port, 60)
client.loop_start()


model = YOLO("D:/on/Project_Artificial_Intelegent/Computer_Vision/Otics_Plant1_HLA/Mesin_IAA29/yolov8n.pt")
class_names = ['hla', 'off', 'altar', 'box_after', 'adm_export', 'tmmin']
media_folder = "media"
ok_folder = os.path.join(media_folder, "OK")
ng_folder = os.path.join(media_folder, "NG")
rtsp_base_url = "rtsp://admin:pt_otics1*@192.168.1.108:554/cam/realmonitor?channel=1&subtype=0"
common_paths = ["/cam/realmonitor?channel=1&subtype=0"]

os.makedirs(ok_folder, exist_ok=True)
os.makedirs(ng_folder, exist_ok=True)

def test_stream(path):
    rtsp_url = rtsp_base_url + path
    vs = VideoStream(rtsp_url).start()
    time.sleep(2.0)
    frame = vs.read()
    vs.stop()
    return frame is not None

for path in common_paths:
    if test_stream(path):
        print(f"[INFO] stream path found: {path}")
        rtsp_url = rtsp_base_url + path
        break
else:
    print("[ERROR] no valid stream path found")
    exit()

print("[INFO] starting video stream...")
camera_stream = VideoStream(rtsp_url).start()



def capture_image(frame, timestamp, result_status):
    if result_status == "OK":
        save_folder = ok_folder
    else:
        save_folder = ng_folder


    
    image_save_path = os.path.join(save_folder, f"hla_capture_{timestamp}.jpg")
    print(f"[INFO] Capturing image: {image_save_path}")
    cv2.imwrite(image_save_path, frame)
    print(f"[INFO] Image saved to {image_save_path}")


capture_history = []
last_capture_time = 0
capture_cooldown = 60
parsed_data = None

def update_capture_history(hla_count, timestamp, status):
    capture_history.append({"Timestamp": timestamp, "Total HLA": hla_count, "Status": status})
    if len(capture_history) > 30:
        capture_history.pop(0)

while True:
    time.sleep(0.1)
    frame = camera_stream.read()
    if frame is None:
        break
    try:
        results = model(frame, conf=0.65)
    except Exception as e:
        print(f"[ERROR] Error during model inference: {e}")
        continue

    detected_objects = results[0].boxes.data.cpu().numpy()
    hla_count = sum(1 for obj in detected_objects if int(obj[5]) < len(class_names) and class_names[int(obj[5])] == 'hla')
    
    print(f"Number of 'hla' objects detected: {hla_count}")
    print(parsed_data)

    if parsed_data is not None and parsed_data[1] == 1:

        year = parsed_data[3]
        month = parsed_data[4]
        day = parsed_data[5]
        hour = parsed_data[6]
        minute = parsed_data[7]
        second = parsed_data[8]

        timestamp = f"{year:04d}{month:02d}{day:02d}_{hour:02d}{minute:02d}{second:02d}"

        if hla_count == 88 and (time.time() - last_capture_time) >= capture_cooldown:

            client.publish(mqtt_topic_pub, "data_result,1,1,1,1,1,1,1,1,1,1,#")
            print("Published data_result OK to mqtt_topic_pub")
            capture_image(frame, timestamp, "OK")  
            last_capture_time = time.time()  
        elif hla_count != 88 and (time.time() - last_capture_time) >= capture_cooldown:
            
            client.publish(mqtt_topic_pub, "data_result,0,0,0,0,0,0,0,0,0,0,#")
            print("Published data_result NG to mqtt_topic_pub")
            capture_image(frame, timestamp, "NG")  
        
        parsed_data[1] = 0
        update_capture_history(hla_count, timestamp, "OK" if hla_count == 88 else "NG")

    annotated_frame = results[0].plot(line_width=1, labels=True, conf=True)
    sidebar_width = 600
    sidebar_color = (142, 112, 0)
    cv2.rectangle(annotated_frame, (0, 0), (sidebar_width, annotated_frame.shape[0]), sidebar_color, -1)
    red_bg_color = (0, 0, 255)
    cv2.rectangle(annotated_frame, (20, 30), (sidebar_width - 20, 100), red_bg_color, -1)
    white_text_color = (255, 255, 255)
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(annotated_frame, f"HLA Count: {hla_count}", (30, 80), font, 1.5, white_text_color, 5)
    history_start_y = 150
    for idx, record in enumerate(capture_history):
        timestamp, count = record["Timestamp"], record["Total HLA"]
        status = record["Status"]
        history_text = f"{idx + 1}: {timestamp} | HLA: {count} | Status: {status}"
        cv2.putText(annotated_frame, history_text, (30, history_start_y + (idx * 30)), font, 0.7, white_text_color, 2)

    frame_color = (184, 132, 0)
    frame_thickness = 20
    cv2.rectangle(annotated_frame, (0, 0), (annotated_frame.shape[1] - 1, annotated_frame.shape[0] - 1), frame_color, frame_thickness)
    resized_frame = cv2.resize(annotated_frame, (1395, 770))
    cv2.imshow("Deteksi Part HLA", resized_frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# Cleanup
camera_stream.stop()
cv2.destroyAllWindows()
client.loop_stop()
