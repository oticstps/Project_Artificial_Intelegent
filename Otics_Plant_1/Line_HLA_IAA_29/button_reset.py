
# #tes


import os
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from paho.mqtt import client as mqtt


# =========================================================
# PATH / DATABASE CONFIG
# =========================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "judgment_history.db")


# =========================================================
# MQTT CONFIG
# =========================================================
mqtt_broker = "10.42.0.1"
mqtt_port = 1883
mqtt_topic_pub = "11220223_core_nais_judg"

try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()


# =========================================================
# DATABASE HELPERS
# =========================================================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS judgment_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                program_date TEXT NOT NULL,
                hla_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                image_path TEXT,
                active_part TEXT,
                expected_hla INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def fetch_records(program_date_filter=""):
    with get_db_connection() as conn:
        if program_date_filter.strip():
            rows = conn.execute(
                """
                SELECT id, timestamp, program_date, hla_count, status, image_path, active_part, expected_hla, created_at
                FROM judgment_history
                WHERE program_date = ?
                ORDER BY id DESC
                """,
                (program_date_filter.strip(),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, timestamp, program_date, hla_count, status, image_path, active_part, expected_hla, created_at
                FROM judgment_history
                ORDER BY id DESC
                """
            ).fetchall()
    return rows


def insert_record(timestamp_text, program_date_text, hla_count, status, image_path, active_part, expected_hla):
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO judgment_history (
                timestamp, program_date, hla_count, status, image_path, active_part, expected_hla
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp_text,
                program_date_text,
                int(hla_count),
                status,
                image_path,
                active_part,
                int(expected_hla) if expected_hla != "" else 0,
            ),
        )
        conn.commit()


def update_record(record_id, timestamp_text, program_date_text, hla_count, status, image_path, active_part, expected_hla):
    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE judgment_history
            SET timestamp = ?,
                program_date = ?,
                hla_count = ?,
                status = ?,
                image_path = ?,
                active_part = ?,
                expected_hla = ?
            WHERE id = ?
            """,
            (
                timestamp_text,
                program_date_text,
                int(hla_count),
                status,
                image_path,
                active_part,
                int(expected_hla) if expected_hla != "" else 0,
                int(record_id),
            ),
        )
        conn.commit()


def delete_record(record_id):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM judgment_history WHERE id = ?", (int(record_id),))
        conn.commit()


def count_today_ok(program_date_text):
    if not program_date_text.strip():
        return 0
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total_ok FROM judgment_history WHERE program_date = ? AND status = 'OKE'",
            (program_date_text.strip(),),
        ).fetchone()
    return int(row["total_ok"]) if row else 0


# =========================================================
# MQTT ACTIONS
# =========================================================
def on_button_click():
    data = "data_reset,1,1,1,1,1,1,1,1,1,1,#"
    client.publish(mqtt_topic_pub, data)
    print(f"Data '{data}' sent to topic '{mqtt_topic_pub}'")
    messagebox.showinfo("Info", "Perintah reset berhasil dikirim.")


def play_sound(track):
    data = f"test_sound,{track}"
    client.publish(mqtt_topic_pub, data)
    print(f"Sound test: '{data}' sent to topic '{mqtt_topic_pub}'")


def on_closing():
    if messagebox.askokcancel("Quit", "Do you want to quit?"):
        client.loop_stop()
        root.destroy()


# =========================================================
# CRUD UI HELPERS
# =========================================================
def clear_form():
    entry_id_var.set("")
    entry_timestamp_var.set("")
    entry_program_date_var.set("")
    entry_hla_count_var.set("0")
    combo_status_var.set("OKE")
    entry_active_part_var.set("None")
    entry_expected_hla_var.set("0")
    entry_image_path_var.set("")
    tree.selection_remove(tree.selection())


def validate_form():
    if not entry_timestamp_var.get().strip():
        raise ValueError("Timestamp wajib diisi.")
    if not entry_program_date_var.get().strip():
        raise ValueError("Program Date wajib diisi. Format contoh: 2026_04_14")
    if combo_status_var.get().strip() not in {"OKE", "NG"}:
        raise ValueError("Status harus OKE atau NG.")
    int(entry_hla_count_var.get().strip())
    if entry_expected_hla_var.get().strip() != "":
        int(entry_expected_hla_var.get().strip())


def refresh_table():
    for item in tree.get_children():
        tree.delete(item)

    rows = fetch_records(filter_program_date_var.get())
    for row in rows:
        tree.insert(
            "",
            "end",
            values=(
                row["id"],
                row["timestamp"],
                row["program_date"],
                row["hla_count"],
                row["status"],
                row["active_part"] or "",
                row["expected_hla"] or 0,
                row["image_path"] or "",
                row["created_at"] or "",
            ),
        )

    summary_date = filter_program_date_var.get().strip()
    if summary_date:
        summary_var.set(f"Total OKE pada {summary_date}: {count_today_ok(summary_date)}")
    else:
        summary_var.set(f"Total data tampil: {len(rows)}")


def on_tree_select(event=None):
    selected = tree.selection()
    if not selected:
        return

    values = tree.item(selected[0], "values")
    entry_id_var.set(values[0])
    entry_timestamp_var.set(values[1])
    entry_program_date_var.set(values[2])
    entry_hla_count_var.set(values[3])
    combo_status_var.set(values[4])
    entry_active_part_var.set(values[5])
    entry_expected_hla_var.set(values[6])
    entry_image_path_var.set(values[7])


def add_record_ui():
    try:
        validate_form()
        insert_record(
            timestamp_text=entry_timestamp_var.get().strip(),
            program_date_text=entry_program_date_var.get().strip(),
            hla_count=entry_hla_count_var.get().strip(),
            status=combo_status_var.get().strip(),
            image_path=entry_image_path_var.get().strip(),
            active_part=entry_active_part_var.get().strip(),
            expected_hla=entry_expected_hla_var.get().strip(),
        )
        refresh_table()
        clear_form()
        messagebox.showinfo("Sukses", "Data berhasil ditambahkan.")
    except Exception as e:
        messagebox.showerror("Error", str(e))


def update_record_ui():
    try:
        record_id = entry_id_var.get().strip()
        if not record_id:
            raise ValueError("Pilih data yang ingin diubah terlebih dahulu.")
        validate_form()
        update_record(
            record_id=record_id,
            timestamp_text=entry_timestamp_var.get().strip(),
            program_date_text=entry_program_date_var.get().strip(),
            hla_count=entry_hla_count_var.get().strip(),
            status=combo_status_var.get().strip(),
            image_path=entry_image_path_var.get().strip(),
            active_part=entry_active_part_var.get().strip(),
            expected_hla=entry_expected_hla_var.get().strip(),
        )
        refresh_table()
        messagebox.showinfo("Sukses", "Data berhasil diperbarui.")
    except Exception as e:
        messagebox.showerror("Error", str(e))


def delete_record_ui():
    try:
        record_id = entry_id_var.get().strip()
        if not record_id:
            raise ValueError("Pilih data yang ingin dihapus terlebih dahulu.")
        if not messagebox.askyesno("Konfirmasi", f"Hapus data ID {record_id}?"):
            return
        delete_record(record_id)
        refresh_table()
        clear_form()
        messagebox.showinfo("Sukses", "Data berhasil dihapus.")
    except Exception as e:
        messagebox.showerror("Error", str(e))


def fill_example_today():
    entry_timestamp_var.set("20260414_083000")
    entry_program_date_var.set("2026_04_14")
    entry_hla_count_var.set("80")
    combo_status_var.set("OKE")
    entry_active_part_var.set("tmmin-1E")
    entry_expected_hla_var.set("80")
    entry_image_path_var.set("media/OK/2026_04_14/hla_capture_20260414_083000.jpg")


# =========================================================
# CONNECT MQTT + INIT DB
# =========================================================
init_database()
client.connect(mqtt_broker, mqtt_port, 60)
client.loop_start()


# =========================================================
# MAIN WINDOW
# =========================================================
root = tk.Tk()
root.title('RESET SISTEM KAMERA + TEST SUARA + CRUD SQLITE')
root.geometry('1450x900')
root.configure(bg='#e5e5e5')


def center_window(window):
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    x = (window.winfo_screenwidth() // 2) - (width // 2)
    y = (window.winfo_screenheight() // 2) - (height // 2)
    window.geometry(f'{width}x{height}+{x}+{y}')


# Layout utama
left_panel = tk.Frame(root, width=420, bg='#e5e5e5')
left_panel.pack(side='left', fill='y', padx=10, pady=10)

right_panel = tk.Frame(root, bg='#f7f7f7', bd=2, relief='solid')
right_panel.pack(side='right', expand=True, fill='both', padx=10, pady=10)

# Header kiri
header = tk.Label(
    left_panel,
    text="CONTROL\nSISTEM KAMERA",
    font=('Times New Roman', 24, 'bold'),
    fg='#000000',
    bg='#e5e5e5'
)
header.pack(pady=15)

instruction_frame = tk.Frame(left_panel, bg='#5379ec', bd=2, relief='solid')
instruction_frame.pack(fill='x', pady=(0, 15))

tk.Label(
    instruction_frame,
    text="APAKAH ADA KONDISI NG ?",
    font=('Arial', 18, 'bold'),
    fg='white',
    bg='#5379ec'
).pack(pady=(20, 8))

tk.Label(
    instruction_frame,
    text="SILAHKAN RESET SISTEM KAMERA",
    font=('Arial', 18),
    fg='white',
    bg='#5379ec'
).pack(pady=(8, 20))

button_frame = tk.Frame(left_panel, bg='#5379ec', bd=2, relief='solid')
button_frame.pack(fill='x', pady=(0, 15))

reset_button = tk.Button(
    button_frame,
    text='BUTTON RESET SISTEM KAMERA',
    command=on_button_click,
    width=30,
    height=2,
    font=('Arial', 18, 'bold'),
    bg='#87CEFA',
    fg='black',
    activebackground='#00BFFF',
    bd=0,
)
reset_button.pack(padx=10, pady=12)

sound_frame = tk.Frame(left_panel, bg='#5379ec', bd=2, relief='solid')
sound_frame.pack(fill='x', pady=(0, 15))

tk.Label(
    sound_frame,
    text="UJI MANUAL SEMUA SUARA",
    font=('Arial', 16, 'bold'),
    fg='white',
    bg='#5379ec'
).pack(pady=(10, 10))

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
    ("10. Reset berhasil", 10),
]

grid_frame = tk.Frame(sound_frame, bg='#5379ec')
grid_frame.pack(padx=8, pady=(0, 10), fill='x')

row = 0
col = 0
for text, track in buttons:
    btn = tk.Button(
        grid_frame,
        text=text,
        command=lambda t=track: play_sound(t),
        width=20,
        height=2,
        font=('Arial', 11),
        bg='#FFFFFF',
        fg='black',
        activebackground='#DDDDDD',
        bd=1,
    )
    btn.grid(row=row, column=col, padx=6, pady=5, sticky="ew")
    col += 1
    if col > 1:
        col = 0
        row += 1

for i in range(2):
    grid_frame.grid_columnconfigure(i, weight=1)

# Kanan: Filter + Table
filter_frame = tk.Frame(right_panel, bg='#f7f7f7')
filter_frame.pack(fill='x', padx=10, pady=10)

tk.Label(filter_frame, text="Filter Program Date", font=('Arial', 11, 'bold'), bg='#f7f7f7').pack(side='left')
filter_program_date_var = tk.StringVar()
entry_filter = tk.Entry(filter_frame, textvariable=filter_program_date_var, width=18, font=('Arial', 11))
entry_filter.pack(side='left', padx=8)

tk.Button(filter_frame, text="Refresh", command=refresh_table, font=('Arial', 10, 'bold'), bg='#D9EAFD').pack(side='left', padx=5)
tk.Button(filter_frame, text="Clear Filter", command=lambda: (filter_program_date_var.set(""), refresh_table()), font=('Arial', 10)).pack(side='left', padx=5)

summary_var = tk.StringVar(value="Total data tampil: 0")
tk.Label(filter_frame, textvariable=summary_var, font=('Arial', 11, 'bold'), bg='#f7f7f7', fg='#0a4f8a').pack(side='right')

columns = ("id", "timestamp", "program_date", "hla_count", "status", "active_part", "expected_hla", "image_path", "created_at")
tree = ttk.Treeview(right_panel, columns=columns, show='headings', height=16)

headings = {
    "id": "ID",
    "timestamp": "Timestamp",
    "program_date": "Program Date",
    "hla_count": "HLA Count",
    "status": "Status",
    "active_part": "Active Part",
    "expected_hla": "Expected HLA",
    "image_path": "Image Path",
    "created_at": "Created At",
}

widths = {
    "id": 60,
    "timestamp": 150,
    "program_date": 110,
    "hla_count": 90,
    "status": 80,
    "active_part": 120,
    "expected_hla": 100,
    "image_path": 260,
    "created_at": 140,
}

for col_name in columns:
    tree.heading(col_name, text=headings[col_name])
    tree.column(col_name, width=widths[col_name], anchor='center')

tree.pack(fill='both', expand=True, padx=10, pady=(0, 10))
tree.bind("<<TreeviewSelect>>", on_tree_select)

scrollbar_y = ttk.Scrollbar(tree, orient='vertical', command=tree.yview)
tree.configure(yscrollcommand=scrollbar_y.set)
scrollbar_y.pack(side='right', fill='y')

# Form CRUD
form_frame = tk.LabelFrame(right_panel, text="FORM CRUD JUDGMENT HISTORY", font=('Arial', 11, 'bold'), bg='#f7f7f7')
form_frame.pack(fill='x', padx=10, pady=(0, 10))

entry_id_var = tk.StringVar()
entry_timestamp_var = tk.StringVar()
entry_program_date_var = tk.StringVar()
entry_hla_count_var = tk.StringVar(value="0")
combo_status_var = tk.StringVar(value="OKE")
entry_active_part_var = tk.StringVar(value="None")
entry_expected_hla_var = tk.StringVar(value="0")
entry_image_path_var = tk.StringVar()

fields = [
    ("ID", entry_id_var, 0, 0, True),
    ("Timestamp", entry_timestamp_var, 0, 2, False),
    ("Program Date", entry_program_date_var, 1, 0, False),
    ("HLA Count", entry_hla_count_var, 1, 2, False),
    ("Active Part", entry_active_part_var, 2, 0, False),
    ("Expected HLA", entry_expected_hla_var, 2, 2, False),
    ("Image Path", entry_image_path_var, 3, 0, False),
]

for label_text, var, row_idx, col_idx, readonly in fields:
    tk.Label(form_frame, text=label_text, font=('Arial', 10, 'bold'), bg='#f7f7f7').grid(row=row_idx, column=col_idx, padx=8, pady=6, sticky='w')
    entry = tk.Entry(form_frame, textvariable=var, width=32, font=('Arial', 10))
    if readonly:
        entry.configure(state='readonly')
    if label_text == "Image Path":
        entry.grid(row=row_idx, column=col_idx + 1, columnspan=3, padx=8, pady=6, sticky='ew')
    else:
        entry.grid(row=row_idx, column=col_idx + 1, padx=8, pady=6, sticky='ew')

# Status combobox
status_label = tk.Label(form_frame, text="Status", font=('Arial', 10, 'bold'), bg='#f7f7f7')
status_label.grid(row=3, column=2, padx=8, pady=6, sticky='w')
status_combo = ttk.Combobox(form_frame, textvariable=combo_status_var, values=["OKE", "NG"], state='readonly', width=29)
status_combo.grid(row=3, column=3, padx=8, pady=6, sticky='ew')

for i in range(4):
    form_frame.grid_columnconfigure(i, weight=1)

crud_button_frame = tk.Frame(form_frame, bg='#f7f7f7')
crud_button_frame.grid(row=4, column=0, columnspan=4, pady=(10, 12))

tk.Button(crud_button_frame, text="Tambah", command=add_record_ui, font=('Arial', 10, 'bold'), bg='#C8F7C5', width=14).pack(side='left', padx=5)
tk.Button(crud_button_frame, text="Update", command=update_record_ui, font=('Arial', 10, 'bold'), bg='#FFF3B0', width=14).pack(side='left', padx=5)
tk.Button(crud_button_frame, text="Delete", command=delete_record_ui, font=('Arial', 10, 'bold'), bg='#FFB3B3', width=14).pack(side='left', padx=5)
tk.Button(crud_button_frame, text="Clear Form", command=clear_form, font=('Arial', 10), width=14).pack(side='left', padx=5)
tk.Button(crud_button_frame, text="Contoh Isi", command=fill_example_today, font=('Arial', 10), width=14).pack(side='left', padx=5)

refresh_table()
center_window(root)
root.protocol("WM_DELETE_WINDOW", on_closing)
root.mainloop()
