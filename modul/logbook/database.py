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
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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
            cur.execute("SELECT chat_id, username, api_token, default_lat, default_lng, default_akurasi, created_at, updated_at FROM logbook_credentials WHERE chat_id = ?", (chat_id,))
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
            cur.execute("SELECT chat_id, username, api_token, created_at, updated_at FROM logbook_credentials ORDER BY created_at ASC")
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal mengambil daftar user: {e}")
        return []

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
