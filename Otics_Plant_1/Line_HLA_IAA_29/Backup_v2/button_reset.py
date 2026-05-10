import sys
import tkinter as tk
from tkinter import messagebox
from paho.mqtt import client as mqtt

# MQTT Configuration
mqtt_broker = "10.42.0.1"
mqtt_port = 1883
mqtt_topic_pub = "11220223_core_nais_judg"

# Use newer MQTT client API (avoid deprecation warning)
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()

def on_button_click():
    """Original reset button: sends fixed data_reset message."""
    data = "data_reset,1,1,1,1,1,1,1,1,1,1,#"
    client.publish(mqtt_topic_pub, data)
    print(f"Data '{data}' sent to topic '{mqtt_topic_pub}'")

def play_sound(track):
    """Send test_sound command for given track number."""
    data = f"test_sound,{track}"
    client.publish(mqtt_topic_pub, data)
    print(f"Sound test: '{data}' sent to topic '{mqtt_topic_pub}'")

def on_closing():
    if messagebox.askokcancel("Quit", "Do you want to quit?"):
        client.loop_stop()
        root.destroy()

# Connect MQTT
client.connect(mqtt_broker, mqtt_port, 60)
client.loop_start()

# Main window
root = tk.Tk()
root.title('RESET SISTEM KAMERA + TEST SUARA (10 SUARA)')
root.geometry('1095x770')
root.configure(bg='#e5e5e5')

def center_window(window):
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    x = (window.winfo_screenwidth() // 2) - (width // 2)
    y = (window.winfo_screenheight() // 2) - (height // 2)
    window.geometry('{}x{}+{}+{}'.format(width, height, x, y))

# Sidebar (left)
sidebar = tk.Frame(root, width=int(0.3 * 1395), bg='#e5e5e5', bd=2, relief='solid')
sidebar.pack(side='left', fill='y')

header = tk.Label(sidebar, text="CONTROL\nSISTEM KAMERA",
                  font=('Times New Roman', 26, 'bold'),
                  fg='#000000', bg='#e5e5e5')
header.pack(pady=20)

# Main content area
content_frame = tk.Frame(root, bg='#5379ec', bd=2, relief='solid')
content_frame.pack(expand=True, fill='both', padx=10, pady=10)

label1 = tk.Label(content_frame, text="APAKAH ADA KONDISI NG ?",
                  font=('Arial', 24), fg='white', bg='#5379ec')
label1.pack(pady=(50, 10))

label2 = tk.Label(content_frame, text="SILAHKAN RESET SISTEM KAMERA",
                  font=('Arial', 24), fg='white', bg='#5379ec')
label2.pack(pady=(10, 50))

# Original reset button
button_frame = tk.Frame(root, bg='#5379ec', bd=2, relief='solid')
button_frame.pack(pady=(0, 20))

reset_button = tk.Button(button_frame, text='BUTTON RESET SISTEM KAMERA',
                         command=on_button_click,
                         width=40, height=3, font=('Arial', 23),
                         bg='#87CEFA', fg='black',
                         activebackground='#00BFFF', bd=0)
reset_button.pack(padx=10, pady=10)

# --- Manual sound test buttons (10 suara) ---
sound_frame = tk.Frame(root, bg='#5379ec', bd=2, relief='solid')
sound_frame.pack(pady=(0, 30))

sound_label = tk.Label(sound_frame, text="UJI MANUAL SEMUA SUARA (10 SUARA)",
                       font=('Arial', 18, 'bold'),
                       fg='white', bg='#5379ec')
sound_label.pack(pady=(10, 10))

# Button definitions (label, track number)
buttons = [
    ("1. Oke selesai", 1),
    ("2. Terimakasih", 2),
    ("3. Alarm", 3),
    ("4. Box tidak terdeteksi", 4),
    ("5. Proses belum selesai", 5),
    ("6. Jumlah part tidak sesuai", 6),
    ("7. Dangae 80 pcs", 7),
    ("8. Dangae 88 pcs", 8),
    ("9. Dangae 108 pcs", 9),
    ("10. Reset berhasil", 10)   # track 10 added
]

# Create a subframe for the grid (to avoid pack/grid conflict)
grid_frame = tk.Frame(sound_frame, bg='#5379ec')
grid_frame.pack()

row = 0
col = 0
for (text, track) in buttons:
    btn = tk.Button(grid_frame, text=text,
                    command=lambda t=track: play_sound(t),
                    width=20, height=2, font=('Arial', 14),
                    bg='#FFFFFF', fg='black',
                    activebackground='#DDDDDD', bd=1)
    btn.grid(row=row, column=col, padx=10, pady=5, sticky="ew")
    col += 1
    if col > 2:   # 3 columns
        col = 0
        row += 1

# Make grid columns expand evenly
for i in range(3):
    grid_frame.grid_columnconfigure(i, weight=1)

center_window(root)
root.protocol("WM_DELETE_WINDOW", on_closing)
root.mainloop()