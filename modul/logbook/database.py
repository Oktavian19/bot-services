import sqlite3
import os
import json
import secrets
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
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def setup_database(force_reset: bool = False):
    """
    Inisialisasi skema multi-user untuk modul logbook.
    Jika force_reset=True atau terdeteksi skema single-user lama (logbook_credentials id PK),
    reset tabel agar bersih dan terstruktur untuk multi-user.
    """
    try:
        with db_session() as conn:
            cur = conn.cursor()

            # Deteksi apakah tabel lama berformat single user
            cur.execute("PRAGMA table_info(logbook_credentials)")
            cols = [r["name"] for r in cur.fetchall()]
            needs_reset = force_reset or ("id" in cols and "chat_id" not in cols)

            if needs_reset:
                print("[DB-LOGBOOK] Mereset skema database ke arsitektur multi-user...")
                conn.execute("DROP TABLE IF EXISTS logbook_drafts")
                conn.execute("DROP TABLE IF EXISTS logbook_credentials")

            conn.execute('''
                CREATE TABLE IF NOT EXISTS logbook_credentials (
                    chat_id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL,
                    password_encrypted TEXT NOT NULL,
                    api_token TEXT UNIQUE NOT NULL,
                    default_lat TEXT DEFAULT '-7.5815',
                    default_lng TEXT DEFAULT '112.6247',
                    default_akurasi TEXT DEFAULT '15',
                    reminder_time TEXT DEFAULT '16:05',
                    reminder_days TEXT DEFAULT '0,1,2,3,4',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')

            # Migrasi kolom reminder_time & reminder_days jika belum ada pada tabel credentials
            cur.execute("PRAGMA table_info(logbook_credentials)")
            cred_cols = [r["name"] for r in cur.fetchall()]
            if "reminder_time" not in cred_cols:
                conn.execute("ALTER TABLE logbook_credentials ADD COLUMN reminder_time TEXT DEFAULT '16:05'")
            if "reminder_days" not in cred_cols:
                conn.execute("ALTER TABLE logbook_credentials ADD COLUMN reminder_days TEXT DEFAULT '0,1,2,3,4'")

            conn.execute('''
                CREATE TABLE IF NOT EXISTS logbook_reminder_state (
                    chat_id INTEGER PRIMARY KEY,
                    target_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    next_retry_at TEXT,
                    last_message_id INTEGER,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (chat_id) REFERENCES logbook_credentials(chat_id) ON DELETE CASCADE
                )
            ''')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS logbook_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    date TEXT NOT NULL,
                    projects TEXT NOT NULL,
                    commits_summary TEXT NOT NULL,
                    raw_metadata TEXT NOT NULL,
                    status TEXT NOT NULL,
                    jam_masuk TEXT DEFAULT '07:10',
                    jam_pulang TEXT DEFAULT '16:25',
                    telegram_message_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT,
                    FOREIGN KEY (chat_id) REFERENCES logbook_credentials(chat_id) ON DELETE CASCADE
                )
            ''')

            conn.execute("CREATE INDEX IF NOT EXISTS idx_drafts_chat_id ON logbook_drafts(chat_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_drafts_date ON logbook_drafts(date)")

        print("[DB-LOGBOOK] Database SQLite multi-user untuk logbook berhasil diinisialisasi/diperiksa.")
    except Exception as e:
        print(f"[DB-LOGBOOK - FATAL] Gagal inisialisasi database logbook: {e}")
        raise

# --- MANAJEMEN USER & KREDENSIAL MULTI-USER ---

def register_user_credential(chat_id: int, username: str, plain_password: str, api_token: str = None) -> str:
    """
    Menyimpan atau memperbarui kredensial DERMAGA dan token API untuk user (chat_id).
    Jika api_token None, otomatis generate token acak hex 32 karakter yang aman.
    Mengembalikan api_token: str.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    enc_pass = encrypt_cred(plain_password)

    try:
        with db_session() as conn:
            cur = conn.cursor()
            # Cek apakah user sudah punya token sebelumnya
            cur.execute("SELECT api_token FROM logbook_credentials WHERE chat_id = ?", (chat_id,))
            row = cur.fetchone()

            if api_token:
                final_token = api_token
            elif row and row["api_token"]:
                final_token = row["api_token"]
            else:
                final_token = secrets.token_hex(16)

            conn.execute('''
                INSERT OR REPLACE INTO logbook_credentials 
                (chat_id, username, password_encrypted, api_token, created_at, updated_at)
                VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM logbook_credentials WHERE chat_id = ?), ?), ?)
            ''', (chat_id, username, enc_pass, final_token, chat_id, now_str, now_str))

        print(f"[DB-LOGBOOK] Kredensial User {chat_id} ({username}) berhasil disimpan/diperbarui.")
        return final_token
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal mendaftarkan user {chat_id}: {e}")
        raise

def get_user_by_token(token: str) -> dict:
    """Mencari data user berdasarkan Bearer api_token."""
    if not token:
        return None
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM logbook_credentials WHERE api_token = ?", (token.strip(),))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal mencari user by token: {e}")
        return None

def get_user_by_chat_id(chat_id: int) -> dict:
    """Mengambil metadata user berdasarkan chat_id."""
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT chat_id, username, api_token, default_lat, default_lng, default_akurasi, reminder_time, reminder_days, created_at, updated_at FROM logbook_credentials WHERE chat_id = ?", (chat_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal membaca user {chat_id}: {e}")
        return None

def get_user_credential(chat_id: int) -> tuple:
    """Mengembalikan (username, plain_password) untuk chat_id tertentu."""
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT username, password_encrypted FROM logbook_credentials WHERE chat_id = ?", (chat_id,))
            row = cur.fetchone()
            if row:
                plain_pass = decrypt_cred(row["password_encrypted"])
                return row["username"], plain_pass
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal membaca kredensial user {chat_id}: {e}")
    return None, None

def regenerate_api_token(chat_id: int) -> str:
    """Membuat ulang API token baru untuk chat_id tertentu."""
    new_token = secrets.token_hex(16)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with db_session() as conn:
            conn.execute('''
                UPDATE logbook_credentials 
                SET api_token = ?, updated_at = ?
                WHERE chat_id = ?
            ''', (new_token, now_str, chat_id))
        return new_token
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal regenerate token user {chat_id}: {e}")
        return None

def delete_user_credential(chat_id: int) -> bool:
    """Menghapus seluruh akun dan draf logbook milik user."""
    try:
        with db_session() as conn:
            conn.execute("DELETE FROM logbook_credentials WHERE chat_id = ?", (chat_id,))
        print(f"[DB-LOGBOOK] Akun user {chat_id} berhasil dihapus.")
        return True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal menghapus akun user {chat_id}: {e}")
        return False

def get_all_users() -> list:
    """Mengambil daftar seluruh user terdaftar (untuk admin)."""
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT chat_id, username, api_token, reminder_time, reminder_days, created_at, updated_at FROM logbook_credentials ORDER BY created_at ASC")
            users = []
            for r in cur.fetchall():
                u = dict(r)
                u['is_active'] = True
                users.append(u)
            return users
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal mengambil daftar user: {e}")
        return []

# --- MANAJEMEN PENGINGAT LOGBOOK ---

def update_user_reminder_time(chat_id: int, reminder_time: str) -> bool:
    """Memperbarui jam pengingat logbook (format HH:MM) untuk user."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with db_session() as conn:
            conn.execute('''
                UPDATE logbook_credentials
                SET reminder_time = ?, updated_at = ?
                WHERE chat_id = ?
            ''', (reminder_time.strip(), now_str, chat_id))
        print(f"[DB-LOGBOOK] Jam pengingat User {chat_id} diubah menjadi {reminder_time}.")
        return True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal memperbarui jam pengingat user {chat_id}: {e}")
        return False

def get_user_reminder_time(chat_id: int) -> str:
    """Mengambil jam pengingat logbook user (default '16:05')."""
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT reminder_time FROM logbook_credentials WHERE chat_id = ?", (chat_id,))
            row = cur.fetchone()
            if row and row["reminder_time"]:
                return str(row["reminder_time"]).strip()
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal mengambil jam pengingat user {chat_id}: {e}")
    return "16:05"

def update_user_reminder_days(chat_id: int, reminder_days: str) -> bool:
    """Memperbarui daftar hari pengingat logbook (format string koma, contoh: '0,1,2,3,4') untuk user."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with db_session() as conn:
            conn.execute('''
                UPDATE logbook_credentials
                SET reminder_days = ?, updated_at = ?
                WHERE chat_id = ?
            ''', (reminder_days.strip(), now_str, chat_id))
        print(f"[DB-LOGBOOK] Hari pengingat User {chat_id} diubah menjadi '{reminder_days}'.")
        return True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal memperbarui hari pengingat user {chat_id}: {e}")
        return False

def get_user_reminder_days(chat_id: int) -> str:
    """Mengambil hari pengingat logbook user (default '0,1,2,3,4' yaitu Senin-Jumat)."""
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT reminder_days FROM logbook_credentials WHERE chat_id = ?", (chat_id,))
            row = cur.fetchone()
            if row and row["reminder_days"] is not None:
                return str(row["reminder_days"]).strip()
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal mengambil hari pengingat user {chat_id}: {e}")
    return "0,1,2,3,4"

def get_active_reminder_users() -> list:
    """Mengambil daftar seluruh user yang memiliki kredensial logbook aktif."""
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT chat_id, username, COALESCE(reminder_time, '16:05') as reminder_time, COALESCE(reminder_days, '0,1,2,3,4') as reminder_days FROM logbook_credentials")
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal mengambil user pengingat: {e}")
        return []

def get_or_create_reminder_state(chat_id: int, target_date: str) -> dict:
    """Mengambil atau menginisialisasi state pengingat untuk target_date."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM logbook_reminder_state WHERE chat_id = ?", (chat_id,))
            row = cur.fetchone()
            if row and row["target_date"] == target_date:
                return dict(row)

            # Jika belum ada atau tanggal berbeda (hari baru), reset state untuk hari ini
            conn.execute('''
                INSERT OR REPLACE INTO logbook_reminder_state
                (chat_id, target_date, status, retry_count, next_retry_at, last_message_id, updated_at)
                VALUES (?, ?, 'idle', 0, NULL, NULL, ?)
            ''', (chat_id, target_date, now_str))

            cur.execute("SELECT * FROM logbook_reminder_state WHERE chat_id = ?", (chat_id,))
            return dict(cur.fetchone())
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal inisialisasi state pengingat user {chat_id}: {e}")
        return {
            'chat_id': chat_id,
            'target_date': target_date,
            'status': 'idle',
            'retry_count': 0,
            'next_retry_at': None,
            'last_message_id': None,
            'updated_at': now_str
        }

def update_reminder_state(chat_id: int, target_date: str, status: str, next_retry_at: str = None, message_id: int = None, increment_retry: bool = False) -> bool:
    """Memperbarui status pengingat harian user."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT retry_count, last_message_id FROM logbook_reminder_state WHERE chat_id = ?", (chat_id,))
            row = cur.fetchone()
            current_retry = row["retry_count"] if row else 0
            new_retry = (current_retry + 1) if increment_retry else current_retry
            final_msg_id = message_id if message_id is not None else (row["last_message_id"] if row else None)

            conn.execute('''
                INSERT OR REPLACE INTO logbook_reminder_state
                (chat_id, target_date, status, retry_count, next_retry_at, last_message_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (chat_id, target_date, status, new_retry, next_retry_at, final_msg_id, now_str))
        return True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal update state pengingat user {chat_id}: {e}")
        return False

def stop_reminder_for_today(chat_id: int, target_date: str) -> bool:
    """Menghentikan pengingat dan scan logbook untuk hari target_date."""
    return update_reminder_state(chat_id, target_date, status='stopped', next_retry_at=None)

def complete_reminder_for_today(chat_id: int, target_date: str) -> bool:
    """Menandai bahwa logbook untuk hari target_date telah terisi atau selesai."""
    return update_reminder_state(chat_id, target_date, status='completed', next_retry_at=None)

def has_today_draft_or_submission(chat_id: int, target_date: str) -> bool:
    """Memeriksa apakah sudah ada draf aktif (pending/approved) atau submission sukses hari ini."""
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT COUNT(*) as cnt FROM logbook_drafts 
                WHERE chat_id = ? AND date = ? AND status IN ('pending', 'approved', 'submitted')
            ''', (chat_id, target_date))
            row = cur.fetchone()
            return (row["cnt"] > 0) if row else False
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal cek status draf hari ini untuk user {chat_id}: {e}")
        return False

# --- MANAJEMEN DRAF LOGBOOK MULTI-USER ---

def create_or_get_draft(chat_id: int = None, idempotency_key: str = "", date: str = "", projects = None, commits_summary: str = "", raw_metadata = None, jam_masuk: str = "07:10", jam_pulang: str = "16:25"):
    """
    Menyimpan draf logbook baru secara idempoten untuk user (chat_id).
    Mengembalikan tuple (draft_dict, is_new: bool).
    """
    projects_json = json.dumps(projects) if isinstance(projects, (list, dict)) else str(projects)
    raw_metadata_json = json.dumps(raw_metadata) if isinstance(raw_metadata, (list, dict)) else str(raw_metadata)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not chat_id:
        try:
            with db_session() as conn:
                cur = conn.cursor()
                cur.execute("SELECT chat_id FROM logbook_credentials ORDER BY created_at ASC LIMIT 1")
                row = cur.fetchone()
                if row:
                    chat_id = row["chat_id"]
        except Exception:
            pass

    if not chat_id:
        raise ValueError("chat_id diperlukan untuk membuat draf logbook.")

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
                (chat_id, idempotency_key, date, projects, commits_summary, raw_metadata, status, jam_masuk, jam_pulang, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            ''', (chat_id, idempotency_key, date, projects_json, commits_summary, raw_metadata_json, jam_masuk, jam_pulang, now_str, now_str))
            draft_id = cur.lastrowid
            
            cur.execute("SELECT * FROM logbook_drafts WHERE id = ?", (draft_id,))
            new_row = cur.fetchone()
            return dict(new_row), True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal membuat/mengambil draf user {chat_id}: {e}")
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

def update_telegram_message_info(draft_id: int, message_id: int):
    try:
        with db_session() as conn:
            conn.execute('''
                UPDATE logbook_drafts
                SET telegram_message_id = ?
                WHERE id = ?
            ''', (message_id, draft_id))
        return True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal update info pesan Telegram: {e}")
        return False

def get_recent_drafts(chat_id: int = None, limit: int = 5):
    """Mengambil riwayat draf terkini. Jika chat_id diberikan, difilter per user."""
    try:
        with db_session() as conn:
            cur = conn.cursor()
            if chat_id:
                cur.execute("SELECT * FROM logbook_drafts WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, limit))
            else:
                cur.execute("SELECT * FROM logbook_drafts ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal mengambil draf terkini: {e}")
        return []
