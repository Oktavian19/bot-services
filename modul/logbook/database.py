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
            if "active_location_profile" not in cred_cols:
                conn.execute("ALTER TABLE logbook_credentials ADD COLUMN active_location_profile TEXT DEFAULT 'office'")

            # Tabel profil lokasi multi-profile (office, home, other)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS logbook_location_profiles (
                    chat_id INTEGER NOT NULL,
                    profile_key TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    lat TEXT,
                    lng TEXT,
                    akurasi TEXT DEFAULT '15',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, profile_key),
                    FOREIGN KEY (chat_id) REFERENCES logbook_credentials(chat_id) ON DELETE CASCADE
                )
            ''')

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
                    location_profile TEXT DEFAULT 'office',
                    custom_lat TEXT,
                    custom_lng TEXT,
                    custom_akurasi TEXT,
                    telegram_message_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT,
                    FOREIGN KEY (chat_id) REFERENCES logbook_credentials(chat_id) ON DELETE CASCADE
                )
            ''')

            # Migrasi kolom location_profile, custom_lat, custom_lng, custom_akurasi pada tabel logbook_drafts jika belum ada
            cur.execute("PRAGMA table_info(logbook_drafts)")
            draft_cols = [r["name"] for r in cur.fetchall()]
            if "location_profile" not in draft_cols:
                conn.execute("ALTER TABLE logbook_drafts ADD COLUMN location_profile TEXT DEFAULT 'office'")
            if "custom_lat" not in draft_cols:
                conn.execute("ALTER TABLE logbook_drafts ADD COLUMN custom_lat TEXT")
            if "custom_lng" not in draft_cols:
                conn.execute("ALTER TABLE logbook_drafts ADD COLUMN custom_lng TEXT")
            if "custom_akurasi" not in draft_cols:
                conn.execute("ALTER TABLE logbook_drafts ADD COLUMN custom_akurasi TEXT")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_drafts_chat_id ON logbook_drafts(chat_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_drafts_date ON logbook_drafts(date)")

            # Migrasi data default_lat/lng yang ada ke profil 'office'
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute('''
                INSERT OR IGNORE INTO logbook_location_profiles (chat_id, profile_key, profile_name, lat, lng, akurasi, updated_at)
                SELECT chat_id, 'office', '🏢 Kantor (WFO)', default_lat, default_lng, default_akurasi, ?
                FROM logbook_credentials
                WHERE default_lat IS NOT NULL
            ''', (now_str,))

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
            cur.execute("SELECT chat_id, username, api_token, default_lat, default_lng, default_akurasi, reminder_time, reminder_days, active_location_profile, created_at, updated_at FROM logbook_credentials WHERE chat_id = ?", (chat_id,))
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

# --- MANAJEMEN LOKASI / GPS MULTI-PROFILE LOGBOOK ---

PROFILE_DEFINITIONS = {
    'office': '🏢 Kantor (WFO)',
    'home': '🏠 Rumah/Kos (WFH)',
    'other': '📍 Lokasi Lain/Klien'
}

def get_user_location_profiles(chat_id: int) -> dict:
    """Mengambil status ketiga profil lokasi (office, home, other) untuk user."""
    profiles = {}
    for key, name in PROFILE_DEFINITIONS.items():
        profiles[key] = {
            'profile_key': key,
            'profile_name': name,
            'lat': None,
            'lng': None,
            'akurasi': '15',
            'is_set': False,
            'updated_at': None
        }

    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT profile_key, profile_name, lat, lng, akurasi, updated_at FROM logbook_location_profiles WHERE chat_id = ?", (chat_id,))
            for r in cur.fetchall():
                k = r["profile_key"]
                if k in profiles:
                    profiles[k]['lat'] = r["lat"]
                    profiles[k]['lng'] = r["lng"]
                    profiles[k]['akurasi'] = r["akurasi"] or '15'
                    profiles[k]['is_set'] = bool(r["lat"] and r["lng"])
                    profiles[k]['updated_at'] = r["updated_at"]
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal membaca profil lokasi user {chat_id}: {e}")

    # Fallback jika profil office belum tercatat di logbook_location_profiles tapi ada di credentials
    if not profiles['office']['is_set']:
        try:
            with db_session() as conn:
                cur = conn.cursor()
                cur.execute("SELECT default_lat, default_lng, default_akurasi FROM logbook_credentials WHERE chat_id = ?", (chat_id,))
                c = cur.fetchone()
                if c and c["default_lat"]:
                    profiles['office']['lat'] = c["default_lat"]
                    profiles['office']['lng'] = c["default_lng"]
                    profiles['office']['akurasi'] = c["default_akurasi"] or '15'
                    profiles['office']['is_set'] = True
        except Exception:
            pass

    return profiles

def get_active_location_profile(chat_id: int) -> str:
    """Mengambil key profil lokasi aktif ('office', 'home', 'other'). Default 'office'."""
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT active_location_profile FROM logbook_credentials WHERE chat_id = ?", (chat_id,))
            row = cur.fetchone()
            if row and row["active_location_profile"]:
                return str(row["active_location_profile"]).strip()
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal membaca active profile user {chat_id}: {e}")
    return "office"

def set_active_location_profile(chat_id: int, profile_key: str) -> bool:
    """Mengubah profil lokasi aktif untuk user."""
    if profile_key not in PROFILE_DEFINITIONS:
        return False
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with db_session() as conn:
            conn.execute('''
                UPDATE logbook_credentials
                SET active_location_profile = ?, updated_at = ?
                WHERE chat_id = ?
            ''', (profile_key, now_str, chat_id))
        print(f"[DB-LOGBOOK] Active location profile User {chat_id} diubah ke '{profile_key}'.")
        return True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal ubah active profile user {chat_id}: {e}")
        return False

def save_location_profile(chat_id: int, profile_key: str, lat: str, lng: str, akurasi: str = "15") -> bool:
    """Menyimpan atau memperbarui koordinat pada profil lokasi tertentu."""
    if profile_key not in PROFILE_DEFINITIONS:
        return False
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    profile_name = PROFILE_DEFINITIONS[profile_key]
    try:
        with db_session() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO logbook_location_profiles
                (chat_id, profile_key, profile_name, lat, lng, akurasi, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (chat_id, profile_key, profile_name, str(lat).strip(), str(lng).strip(), str(akurasi).strip(), now_str))

            # Jika profil ini adalah profil aktif atau profil 'office', sinkronkan juga ke default_lat/lng credentials
            cur = conn.cursor()
            cur.execute("SELECT active_location_profile FROM logbook_credentials WHERE chat_id = ?", (chat_id,))
            c_row = cur.fetchone()
            act = c_row["active_location_profile"] if c_row else "office"
            if act == profile_key or profile_key == 'office':
                conn.execute('''
                    UPDATE logbook_credentials
                    SET default_lat = ?, default_lng = ?, default_akurasi = ?, updated_at = ?
                    WHERE chat_id = ?
                ''', (str(lat).strip(), str(lng).strip(), str(akurasi).strip(), now_str, chat_id))

        print(f"[DB-LOGBOOK] Profil '{profile_key}' User {chat_id} disimpan: ({lat}, {lng}, akurasi={akurasi}m).")
        return True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal menyimpan profil lokasi user {chat_id}: {e}")
        return False

def update_user_location(chat_id: int, lat: str, lng: str, akurasi: str = "15", profile_key: str = None) -> bool:
    """Memperbarui default koordinat lokasi (lat, lng, akurasi) untuk profil aktif atau profil yang dipilih."""
    if not profile_key:
        profile_key = get_active_location_profile(chat_id)
    return save_location_profile(chat_id, profile_key, lat, lng, akurasi)

def get_user_location(chat_id: int, profile_key: str = None) -> dict:
    """
    Mengambil lokasi user untuk profil tertentu (atau profil aktif jika profile_key None).
    Mengembalikan dict {'lat': ..., 'lng': ..., 'akurasi': ..., 'profile_key': ..., 'profile_name': ...}.
    """
    if not profile_key:
        profile_key = get_active_location_profile(chat_id)

    profiles = get_user_location_profiles(chat_id)
    prof = profiles.get(profile_key)
    if prof and prof['is_set']:
        return {
            "lat": prof["lat"],
            "lng": prof["lng"],
            "akurasi": prof["akurasi"],
            "profile_key": profile_key,
            "profile_name": prof["profile_name"]
        }

    # Jika profil yang diminta belum disetel, coba fallback ke profil 'office'
    office_prof = profiles.get('office')
    if office_prof and office_prof['is_set']:
        return {
            "lat": office_prof["lat"],
            "lng": office_prof["lng"],
            "akurasi": office_prof["akurasi"],
            "profile_key": "office",
            "profile_name": office_prof["profile_name"]
        }

    # Terakhir fallback ke default Mojokerto
    return {
        "lat": "-7.5815",
        "lng": "112.6247",
        "akurasi": "15",
        "profile_key": profile_key or "office",
        "profile_name": PROFILE_DEFINITIONS.get(profile_key, "🏢 Kantor (WFO)")
    }

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

def create_or_get_draft(chat_id: int = None, idempotency_key: str = "", date: str = "", projects = None, commits_summary: str = "", raw_metadata = None, jam_masuk: str = "07:10", jam_pulang: str = "16:25", location_profile: str = None, custom_lat: str = None, custom_lng: str = None, custom_akurasi: str = None):
    """
    Menyimpan draf logbook baru secara idempoten untuk user (chat_id).
    Mendukung penentuan profil lokasi kerja (office, home, other) dan koordinat kustom dari CLI.
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

            # Tentukan profile yang digunakan: jika location_profile dioper valid, pakai itu; jika tidak, baca profil aktif user
            if location_profile and location_profile in PROFILE_DEFINITIONS:
                act_prof = location_profile
            else:
                cur.execute("SELECT active_location_profile FROM logbook_credentials WHERE chat_id = ?", (chat_id,))
                c_row = cur.fetchone()
                act_prof = (c_row["active_location_profile"] if c_row and "active_location_profile" in c_row.keys() and c_row["active_location_profile"] else None) or "office"

            cur.execute('''
                INSERT INTO logbook_drafts 
                (chat_id, idempotency_key, date, projects, commits_summary, raw_metadata, status, jam_masuk, jam_pulang, location_profile, custom_lat, custom_lng, custom_akurasi, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (chat_id, idempotency_key, date, projects_json, commits_summary, raw_metadata_json, jam_masuk, jam_pulang, act_prof, custom_lat, custom_lng, custom_akurasi, now_str, now_str))
            draft_id = cur.lastrowid
            
            cur.execute("SELECT * FROM logbook_drafts WHERE id = ?", (draft_id,))
            new_row = cur.fetchone()
            return dict(new_row), True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal membuat/mengambil draf user {chat_id}: {e}")
        raise

def get_draft_submission_location(draft: dict) -> dict:
    """
    Mengambil metadata koordinat lokasi yang akan disubmit untuk draf tertentu.
    Jika draf memiliki custom_lat dan custom_lng (misal dikirim dari CLI), gunakan itu.
    Jika tidak, ambil koordinat profil draf (office, home, other) atau fallback ke default.
    Mengembalikan dict {'lat': str, 'lng': str, 'akurasi': str, 'profile_key': str, 'profile_name': str, 'is_custom': bool}.
    """
    if not draft:
        return {'lat': '-7.5815', 'lng': '112.6247', 'akurasi': '15', 'profile_key': 'office', 'profile_name': '🏢 Kantor (WFO)', 'is_custom': False}

    c_lat = draft.get('custom_lat')
    c_lng = draft.get('custom_lng')
    if c_lat and c_lng:
        return {
            'lat': str(c_lat).strip(),
            'lng': str(c_lng).strip(),
            'akurasi': str(draft.get('custom_akurasi') or '15').strip(),
            'profile_key': 'custom',
            'profile_name': '🎯 Kustom (CLI)',
            'is_custom': True
        }

    chat_id = draft.get('chat_id')
    prof_key = draft.get('location_profile') or 'office'
    loc = get_user_location(chat_id, profile_key=prof_key) if chat_id else {'lat': '-7.5815', 'lng': '112.6247', 'akurasi': '15', 'profile_name': '🏢 Kantor (WFO)'}
    loc['is_custom'] = False
    return loc

def update_draft_location_profile(draft_id: int, location_profile: str) -> bool:
    """Memperbarui profil lokasi draf (office, home, other)."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with db_session() as conn:
            conn.execute('''
                UPDATE logbook_drafts
                SET location_profile = ?, updated_at = ?
                WHERE id = ?
            ''', (location_profile, now_str, draft_id))
        return True
    except Exception as e:
        print(f"[DB-LOGBOOK - ERROR] Gagal update location_profile draft #{draft_id}: {e}")
        return False

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
