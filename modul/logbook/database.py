import sqlite3
import os
import json
from datetime import datetime
from contextlib import contextmanager
from cryptography.fernet import Fernet

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logbook.db')

def get_cipher_suite():
    secret_key_str = os.environ.get('LOGBOOK_SECRET_KEY') or os.environ.get('MAGANG_SECRET_KEY')
    if secret_key_str:
        key = secret_key_str.encode()
    else:
        # Default fallback key jika environment variable belum diatur
        key = b'DWRTbF6-QoW9dcV_3yQVxctLtJXFOPcUJ7mveMW76jA='
    return Fernet(key)

def encrypt_cred(plain_text: str) -> str:
    cipher = get_cipher_suite()
    return cipher.encrypt(plain_text.encode()).decode()

def decrypt_cred(cipher_text: str) -> str:
    cipher = get_cipher_suite()
    return cipher.decrypt(cipher_text.encode()).decode()

@contextmanager
def db_session():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def setup_database():
    try:
        with db_session() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS logbook_credentials (
                    id INTEGER PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_encrypted TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS logbook_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    date TEXT NOT NULL,
                    projects TEXT NOT NULL,
                    commits_summary TEXT NOT NULL,
                    raw_metadata TEXT NOT NULL,
                    status TEXT NOT NULL,
                    jam_masuk TEXT DEFAULT '07:10',
                    jam_pulang TEXT DEFAULT '16:25',
                    telegram_message_id INTEGER,
                    telegram_chat_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT
                )
            ''')

            # Seed akun default jika belum ada
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM logbook_credentials")
            if cur.fetchone()[0] == 0:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                enc_pass = encrypt_cred("2341720117")
                cur.execute(
                    "INSERT INTO logbook_credentials (username, password_encrypted, updated_at) VALUES (?, ?, ?)",
                    ("2341720117", enc_pass, now_str)
                )
                print("[DB-LOGBOOK] Kredensial default DERMAGA (2341720117) berhasil dienkripsi dan di-seed.")
        print("[DB-LOGBOOK] Database SQLite untuk logbook berhasil diinisialisasi/diperiksa.")
    except Exception as e:
        print(f"[DB-LOGBOOK - FATAL] Gagal inisialisasi database logbook: {e}")

def get_active_credential():
    """Mengembalikan (username, plain_password) aktif dari database atau None."""
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT username, password_encrypted FROM logbook_credentials ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                plain_pass = decrypt_cred(row["password_encrypted"])
                return row["username"], plain_pass
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal membaca kredensial: {e}")
    return None, None

def set_active_credential(username: str, plain_password: str):
    """Menyimpan atau memperbarui kredensial akun DERMAGA."""
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        enc_pass = encrypt_cred(plain_password)
        with db_session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO logbook_credentials (id, username, password_encrypted, updated_at) VALUES (1, ?, ?, ?)",
                (username, enc_pass, now_str)
            )
        print(f"[DB-LOGBOOK] Kredensial akun {username} berhasil diperbarui.")
        return True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal menyimpan kredensial: {e}")
        return False

def create_or_get_draft(idempotency_key: str, date: str, projects, commits_summary: str, raw_metadata, jam_masuk: str = "07:10", jam_pulang: str = "16:25"):
    """
    Menyimpan draf logbook baru secara idempoten.
    Mengembalikan tuple (draft_dict, is_new: bool).
    """
    projects_json = json.dumps(projects) if isinstance(projects, (list, dict)) else str(projects)
    raw_metadata_json = json.dumps(raw_metadata) if isinstance(raw_metadata, (list, dict)) else str(raw_metadata)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with db_session() as conn:
            cur = conn.cursor()
            # Cek apakah draf dengan idempotency_key sudah ada
            cur.execute("SELECT * FROM logbook_drafts WHERE idempotency_key = ?", (idempotency_key,))
            existing = cur.fetchone()
            if existing:
                return dict(existing), False

            cur.execute('''
                INSERT INTO logbook_drafts 
                (idempotency_key, date, projects, commits_summary, raw_metadata, status, jam_masuk, jam_pulang, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            ''', (idempotency_key, date, projects_json, commits_summary, raw_metadata_json, jam_masuk, jam_pulang, now_str, now_str))
            draft_id = cur.lastrowid
            
            cur.execute("SELECT * FROM logbook_drafts WHERE id = ?", (draft_id,))
            new_row = cur.fetchone()
            return dict(new_row), True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal membuat/mengambil draf: {e}")
        raise

def get_draft(draft_id: int):
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM logbook_drafts WHERE id = ?", (draft_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal membaca draf #{draft_id}: {e}")
        return None

def update_draft_status(draft_id: int, status: str, error_message: str = None):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with db_session() as conn:
            conn.execute('''
                UPDATE logbook_drafts
                SET status = ?, error_message = ?, updated_at = ?
                WHERE id = ?
            ''', (status, error_message, now_str, draft_id))
        return True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal update status draf #{draft_id}: {e}")
        return False

def update_draft_summary(draft_id: int, new_summary: str):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with db_session() as conn:
            conn.execute('''
                UPDATE logbook_drafts
                SET commits_summary = ?, status = 'pending', updated_at = ?
                WHERE id = ?
            ''', (new_summary, now_str, draft_id))
        return True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal update isi summary draf #{draft_id}: {e}")
        return False

def update_telegram_message_info(draft_id: int, chat_id: int, message_id: int):
    try:
        with db_session() as conn:
            conn.execute('''
                UPDATE logbook_drafts
                SET telegram_chat_id = ?, telegram_message_id = ?
                WHERE id = ?
            ''', (chat_id, message_id, draft_id))
        return True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal update info pesan Telegram: {e}")
        return False

def get_recent_drafts(limit: int = 5):
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM logbook_drafts ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal mengambil draf terkini: {e}")
        return []
