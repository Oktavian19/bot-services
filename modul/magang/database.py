import sqlite3
import os
from cryptography.fernet import Fernet

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.db')

SECRET_KEY_STR = os.environ.get('MAGANG_SECRET_KEY')
SECRET_KEY = SECRET_KEY_STR.encode() if SECRET_KEY_STR else b''
cipher_suite = Fernet(SECRET_KEY)

def encrypt_pass(plain_text):
    return cipher_suite.encrypt(plain_text.encode()).decode()

def decrypt_pass(cipher_text):
    return cipher_suite.decrypt(cipher_text.encode()).decode()

# --- DATABASE OPERATIONS ---
def init_db():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                password TEXT,
                last_status TEXT
            )''')
        print("[DB-MAGANG] Database SQLite untuk magang berhasil diinisialisasi/diperiksa.")
    except sqlite3.Error as e:
        print(f"[DB-MAGANG - FATAL] Gagal inisialisasi database magang: {e}")

def add_user_db(chat_id, username, plain_password):
    try:
        enc_password = encrypt_pass(plain_password)
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute('INSERT OR REPLACE INTO users (chat_id, username, password, last_status) VALUES (?, ?, ?, ?)',
                         (chat_id, username, enc_password, None))
        print(f"[DB-MAGANG] Kredensial User {chat_id} ({username}) berhasil dienkripsi dan disimpan ke database.")
    except Exception as e:
        print(f"[DB-MAGANG - ERROR] Gagal mengenkripsi/menyimpan data User {chat_id}: {e}")

def remove_user_db(chat_id):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute('DELETE FROM users WHERE chat_id = ?', (chat_id,))
        print(f"[DB-MAGANG] Data User {chat_id} berhasil dihapus secara permanen dari database.")
    except sqlite3.Error as e:
        print(f"[DB-MAGANG - ERROR] Gagal menghapus data User {chat_id}: {e}")

def update_status_db(chat_id, status):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute('UPDATE users SET last_status = ? WHERE chat_id = ?', (status, chat_id))
        print(f"[DB-MAGANG] Status terbaru User {chat_id} berhasil di-commit ke database.")
    except sqlite3.Error as e:
        print(f"[DB-MAGANG - ERROR] Gagal memperbarui status User {chat_id}: {e}")

def get_all_users_db():
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute('SELECT chat_id, username, password, last_status FROM users')
        return cur.fetchall()