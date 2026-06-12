import sqlite3
import os
from cryptography.fernet import Fernet

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.db')

SECRET_KEY = os.environ.get('MAGANG_SECRET_KEY')
cipher_suite = Fernet(SECRET_KEY)

def encrypt_pass(plain_text):
    return cipher_suite.encrypt(plain_text.encode()).decode()

def decrypt_pass(cipher_text):
    return cipher_suite.decrypt(cipher_text.encode()).decode()

# --- DATABASE OPERATIONS ---
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            password TEXT,
            last_status TEXT
        )''')

def add_user_db(chat_id, username, plain_password):
    enc_password = encrypt_pass(plain_password)
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('INSERT OR REPLACE INTO users (chat_id, username, password, last_status) VALUES (?, ?, ?, ?)',
                     (chat_id, username, enc_password, None))

def remove_user_db(chat_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('DELETE FROM users WHERE chat_id = ?', (chat_id,))

def update_status_db(chat_id, status):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('UPDATE users SET last_status = ? WHERE chat_id = ?', (status, chat_id))

def get_all_users_db():
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute('SELECT chat_id, username, password, last_status FROM users')
        return cur.fetchall()