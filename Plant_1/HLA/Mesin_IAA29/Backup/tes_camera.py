import cv2
import imutils
from imutils.video import VideoStream

rtsp_url = "rtsp://admin:oticsjetson1*@192.168.1.108:554"

def main():

    vs = VideoStream(rtsp_url).start()    # Open the RTSP stream

    while True:

        # Grab a frame at a time
        frame = vs.read()
        if frame is None:
            continue

        # Resize and display the frame on the screen
        frame = imutils.resize(frame, width = 1200)
        cv2.imshow('WyzeCam', frame)
    
        # Wait for the user to hit 'q' for quit
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break

    # Clean up and we're outta here.
    cv2.destroyAllWindows()
    vs.stop()

if __name__ == "__main__":
    main()