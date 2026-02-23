import serial
import time

SERIAL_PORT = 'COM5'  # Sesuaikan dengan port serial yang Anda gunakan
BAUD_RATE = 115200

ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)

def read_from_serial():
    while ser.in_waiting > 0:
        data = ser.readline().decode('utf-8').strip()
        print(f"Received data: {data}")

def send_to_serial(data):
    ser.write(data.encode('utf-8') + b'\n')

try:
    print("Koneksi serial berhasil.")
    
    while True:
        # Cek data yang masuk dari Arduino (RTC time)
        read_from_serial()

        # Kirim data jika diperlukan
        trigger_message = input("Masukkan perintah untuk mengirim data (atau ketik 'exit' untuk keluar): ")
        
        if trigger_message.lower() == 'exit':
            break
        
        send_to_serial(trigger_message)
        time.sleep(1)

except KeyboardInterrupt:
    print("Program dihentikan oleh pengguna.")

finally:
    ser.close()
    print("Koneksi serial ditutup.")
