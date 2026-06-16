import sqlite3
import os

# Define the absolute path to ensure the DB is created inside the reminder folder
DB_PATH = os.path.join(os.path.dirname(__file__), 'reminders.db')

def setup_database():
    """Initialize the database and create the reminders table if it doesn't exist."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                target_date DATE NOT NULL,
                notify_time TIME NOT NULL,
                prep_days INTEGER NOT NULL,
                status TEXT DEFAULT 'active'
            )
        ''')
        conn.commit()
        conn.close()
        print("[DB-REMINDER] Database SQLite untuk reminder berhasil diinisialisasi.")
    except sqlite3.Error as e:
        print(f"[DB-REMINDER - FATAL] Gagal inisialisasi database reminder: {e}")

def insert_reminder(chat_id, message, target_date, notify_time, prep_days):
    """Insert a new reminder into the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO reminders (chat_id, message, target_date, notify_time, prep_days, status)
            VALUES (?, ?, ?, ?, ?, 'active')
        ''', (chat_id, message, target_date, notify_time, prep_days))
        conn.commit()
        conn.close()
        print(f"[DB-REMINDER] Pengingat baru (Hari-H: {target_date}) berhasil disimpan untuk User {chat_id}.")
    except sqlite3.Error as e:
        print(f"[DB-REMINDER - ERROR] Gagal menyimpan pengingat User {chat_id}: {e}")

def get_due_reminders(current_time):
    """Fetch all active reminders that match the current time (HH:MM)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # Only fetch active reminders matching the current hour and minute
        cursor.execute('''
            SELECT id, chat_id, message, target_date, prep_days 
            FROM reminders 
            WHERE status = 'active' AND notify_time = ?
        ''', (current_time,))
        reminders = cursor.fetchall()
        conn.close()
        return reminders
    except sqlite3.Error as e:
        print(f"[DB-REMINDER - ERROR] Gagal membaca jadwal reminder rutin: {e}")
        return []

def mark_reminder_completed(reminder_id):
    """Update the status of a reminder to 'completed'."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE reminders 
            SET status = 'completed' 
            WHERE id = ?
        ''', (reminder_id,))
        conn.commit()
        conn.close()
        print(f"[DB-REMINDER] Pengingat ID {reminder_id} telah mencapai Hari-H dan ditandai sebagai 'completed'.")
    except sqlite3.Error as e:
        print(f"[DB-REMINDER - ERROR] Gagal mengubah status pengingat ID {reminder_id}: {e}")

def get_active_reminders_by_chat(chat_id):
    """Fetch all active reminders for a specific user."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, message, target_date, notify_time, prep_days 
            FROM reminders 
            WHERE chat_id = ? AND status = 'active'
        ''', (chat_id,))
        reminders = cursor.fetchall()
        conn.close()
        return reminders
    except sqlite3.Error as e:
        print(f"[DB-REMINDER - ERROR] Gagal membaca daftar pengingat aktif User {chat_id}: {e}")
        return []

def delete_reminder(reminder_id):
    """Delete a reminder from the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM reminders WHERE id = ?', (reminder_id,))
        conn.commit()
        conn.close()
        print(f"[DB-REMINDER] Pengingat ID {reminder_id} berhasil dihapus dari database.")
    except sqlite3.Error as e:
        print(f"[DB-REMINDER - ERROR] Gagal menghapus pengingat ID {reminder_id}: {e}")

def update_reminder_field(reminder_id, field, value):
    """Update a specific field of a reminder."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(f"UPDATE reminders SET {field} = ? WHERE id = ?", (value, reminder_id))
        conn.commit()
        conn.close()
        print(f"[DB-REMINDER] Field '{field}' pada pengingat ID {reminder_id} berhasil diperbarui.")
    except sqlite3.Error as e:
        print(f"[DB-REMINDER - ERROR] Gagal memperbarui field '{field}' pada pengingat ID {reminder_id}: {e}")