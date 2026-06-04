import sqlite3
import os

# Define the absolute path to ensure the DB is created inside the reminder folder
DB_PATH = os.path.join(os.path.dirname(__file__), 'reminders.db')

def setup_database():
    """Initialize the database and create the reminders table if it doesn't exist."""
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

def insert_reminder(chat_id, message, target_date, notify_time, prep_days):
    """Insert a new reminder into the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO reminders (chat_id, message, target_date, notify_time, prep_days, status)
        VALUES (?, ?, ?, ?, ?, 'active')
    ''', (chat_id, message, target_date, notify_time, prep_days))
    conn.commit()
    conn.close()

def get_due_reminders(current_time):
    """Fetch all active reminders that match the current time (HH:MM)."""
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

def mark_reminder_completed(reminder_id):
    """Update the status of a reminder to 'completed'."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE reminders 
        SET status = 'completed' 
        WHERE id = ?
    ''', (reminder_id,))
    conn.commit()
    conn.close()