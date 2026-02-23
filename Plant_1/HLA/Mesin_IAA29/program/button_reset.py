import sys
import tkinter as tk
from tkinter import messagebox
from paho.mqtt import client as mqtt

mqtt_broker = "10.42.0.1"
mqtt_port = 1883
mqtt_topic_pub_insert = "11220223_core_nais_judg"

def on_button_click():
    data = "data_reset,1,1,1,1,1,1,1,1,1,1,#"
    client.publish(mqtt_topic_pub_insert, data)
    print(f"Data '{data}' sent to topic '{mqtt_topic_pub_insert}'")

def on_closing():
    if messagebox.askokcancel("Quit", "Do you want to quit?"):
        client.loop_stop()
        root.destroy()

client = mqtt.Client()
client.connect(mqtt_broker, mqtt_port, 60)
client.loop_start()

root = tk.Tk()
root.title('RESET SISTEM KAMERA')
root.geometry('1095x770')
root.configure(bg='#e5e5e5')

# Function to center the window on the screen
def center_window(window):
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    x = (window.winfo_screenwidth() // 2) - (width // 2)
    y = (window.winfo_screenheight() // 2) - (height // 2)
    window.geometry('{}x{}+{}+{}'.format(width, height, x, y))

# Sidebar
sidebar = tk.Frame(root, width=int(0.3 * 1395), bg='#e5e5e5', bd=2, relief='solid')
sidebar.pack(side='left', fill='y')

header = tk.Label(sidebar, text="CONTROL\nSISTEM KAMERA", font=('Times New Roman', 26, 'bold'), fg='#000000', bg='#e5e5e5')
header.pack(pady=20)

# Main content
content_frame = tk.Frame(root, bg='#5379ec', bd=2, relief='solid')
content_frame.pack(expand=True, fill='both', padx=10, pady=10)

label1 = tk.Label(content_frame, text="APAKAH ADA KONDISI NG ?", font=('Arial', 24), fg='white', bg='#5379ec')
label1.pack(pady=(50, 10))

label2 = tk.Label(content_frame, text="SILAHKAN RESET SISTEM KAMERA", font=('Arial', 24), fg='white', bg='#5379ec')
label2.pack(pady=(10, 50))

# Button
button_frame = tk.Frame(root, bg='#5379ec', bd=2, relief='solid')
button_frame.pack(pady=(0, 50))

button = tk.Button(button_frame, text='BUTTON RESET SISTEM KAMERA', command=on_button_click, width=40, height=3, font=('Arial', 23), bg='#87CEFA', fg='black', activebackground='#00BFFF', bd=0)
button.pack(padx=10, pady=10)

center_window(root)
root.protocol("WM_DELETE_WINDOW", on_closing)
root.mainloop()


# wanda