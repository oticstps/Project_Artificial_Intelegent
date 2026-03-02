from imutils.video import VideoStream
import cv2
import time

# Define the RTSP URL base
rtsp_base_url = "rtsp://admin:pt_otics1*@192.168.1.108:554"

# Extended common RTSP paths
common_paths = [
    "/cam/realmonitor?channel=1&subtype=0"
]

def test_stream(path):
    rtsp_url = rtsp_base_url + path
    print(f"[INFO] testing {rtsp_url}")
    vs = VideoStream(rtsp_url).start()
    time.sleep(2.0)  # Allow the camera sensor to warm up
    frame = vs.read()
    vs.stop()
    return frame is not None

# Loop through common paths
for path in common_paths:
    if test_stream(path):
        print(f"[INFO] stream path found: {path}")
        rtsp_url = rtsp_base_url + path
        break
else:
    print("[ERROR] no valid stream path found")
    exit()

# Start the video stream with the correct path
print("[INFO] starting video stream...")
vs = VideoStream(rtsp_url).start()

# Allow the camera sensor to warm up
time.sleep(2.0)

# Loop over frames from the video stream
while True:
    # Grab the frame from the threaded video stream
    frame = vs.read()

    # Check if the frame is None (end of the video stream)
    if frame is None:
        break

    # Resize the frame to 1920x1080
    frame = cv2.resize(frame, (1395, 770))

    # Display the frame to the screen
    cv2.imshow("Frame", frame)

    # If the `q` key was pressed, break from the loop
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# Do a bit of cleanup
cv2.destroyAllWindows()
vs.stop()
