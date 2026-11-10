"""
Repository async komprehensif untuk modul Logbook DERMAGA (logbook.db).
Menjaga kompatibilitas 100% dengan skema tabel fisik eksisting di server produksi:
- logbook_credentials (password_encrypted, api_token, active_location_profile, dll.)
- logbook_location_profiles (profile_key, lat, lng, akurasi)
- logbook_drafts (projects, commits_summary, location_profile, telegram_message_id)
- logbook_reminder_state (target_date, retry_count, next_retry_at, status)
"""

from datetime import datetime
import json
import secrets
from typing import Any, List, Optional
from app.core.config import get_settings
from app.core.logger import logger
from app.database.connection import get_db_connection
from app.services.crypto import decrypt_text, encrypt_text

DEFAULT_JAM_MASUK = "07:10"
DEFAULT_JAM_PULANG = "16:25"
DEFAULT_REMINDER_TIME = "16:05"
DEFAULT_REMINDER_DAYS = "0,1,2,3,4"
DEFAULT_ACCURACY = "15"
DEFAULT_LAT = "-7.5815"
DEFAULT_LNG = "112.6247"

PROFILE_OFFICE = "office"
PROFILE_HOME = "home"
PROFILE_OTHER = "other"

PROFILE_DEFINITIONS = {
    PROFILE_OFFICE: {
        "key": PROFILE_OFFICE,
        "label": "Kantor (WFO)",
        "icon": "🏢",
        "default_name": "🏢 Kantor (WFO)",
    },
    PROFILE_HOME: {
        "key": PROFILE_HOME,
        "label": "Rumah / Kos (WFH)",
        "icon": "🏠",
        "default_name": "🏠 Rumah / Kos (WFH)",
    },
    PROFILE_OTHER: {
        "key": PROFILE_OTHER,
        "label": "Lokasi Lain / Klien",
        "icon": "📍",
        "default_name": "📍 Lokasi Lain / Klien",
    },
}


async def init_logbook_db() -> None:
    """Inisialisasi dan migrasi tabel multi-user logbook sesuai skema asli logbook.db."""
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        # 1. Kredensial Pengguna
        await conn.execute("""
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
                active_location_profile TEXT DEFAULT 'office',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Migrasi kolom bila belum ada
        cursor = await conn.execute("PRAGMA table_info(logbook_credentials)")
        cols = [r["name"] for r in await cursor.fetchall()]
        if "reminder_time" not in cols:
            await conn.execute("ALTER TABLE logbook_credentials ADD COLUMN reminder_time TEXT DEFAULT '16:05'")
        if "reminder_days" not in cols:
            await conn.execute("ALTER TABLE logbook_credentials ADD COLUMN reminder_days TEXT DEFAULT '0,1,2,3,4'")
        if "active_location_profile" not in cols:
            await conn.execute("ALTER TABLE logbook_credentials ADD COLUMN active_location_profile TEXT DEFAULT 'office'")

        # 2. Profil Lokasi Multi-Profile
        await conn.execute("""
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
        """)

        # 3. State Pengingat Harian
        await conn.execute("""
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
        """)

        # 4. Draf Logbook
        await conn.execute("""
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
        """)

        # Indeks
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_drafts_chat_id ON logbook_drafts(chat_id);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_drafts_date ON logbook_drafts(date);")

        # 5. State Pengingat Mingguan (Tanda Tangan Logbook)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS logbook_weekly_reminders (
                chat_id INTEGER NOT NULL,
                week_start_date TEXT NOT NULL,
                week_label TEXT,
                status TEXT NOT NULL,
                last_reminded_date TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, week_start_date),
                FOREIGN KEY (chat_id) REFERENCES logbook_credentials(chat_id) ON DELETE CASCADE
            )
        """)

    logger.info("[DB-LOGBOOK] Database logbook.db berhasil diverifikasi & diinisialisasi (Async).")


# --- USERS REPO ---

async def register_user_credential(
    chat_id: int,
    username: str,
    plain_pass: str,
    api_token: Optional[str] = None
) -> str:
    """Mendaftarkan kredensial DERMAGA dan token API untuk user."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    enc_pass = encrypt_text(plain_pass)
    settings = get_settings()

    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT api_token FROM logbook_credentials WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()

        if api_token:
            final_token = api_token
        elif row and row["api_token"]:
            final_token = row["api_token"]
        else:
            final_token = secrets.token_hex(16)

        await conn.execute(
            """
            INSERT OR REPLACE INTO logbook_credentials 
            (chat_id, username, password_encrypted, api_token, created_at, updated_at)
            VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM logbook_credentials WHERE chat_id = ?), ?), ?)
            """,
            (chat_id, username, enc_pass, final_token, chat_id, now_str, now_str),
        )

        # Inisialisasi default office profile jika belum ada
        cursor_loc = await conn.execute(
            "SELECT profile_key FROM logbook_location_profiles WHERE chat_id = ? AND profile_key = 'office'",
            (chat_id,),
        )
        if not await cursor_loc.fetchone():
            await conn.execute(
                """
                INSERT OR IGNORE INTO logbook_location_profiles 
                (chat_id, profile_key, profile_name, lat, lng, akurasi, updated_at)
                VALUES (?, 'office', '🏢 Kantor (WFO)', ?, ?, ?, ?)
                """,
                (chat_id, DEFAULT_LAT, DEFAULT_LNG, DEFAULT_ACCURACY, now_str),
            )

    logger.info(f"[DB-LOGBOOK] Kredensial User {chat_id} ({username}) berhasil disimpan/diperbarui.")
    return final_token


async def get_user_by_token(token: str) -> Optional[dict[str, Any]]:
    """Mencari data user berdasarkan Bearer api_token."""
    if not token:
        return None
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT * FROM logbook_credentials WHERE api_token = ?", (token.strip(),)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_chat_id(chat_id: int) -> Optional[dict[str, Any]]:
    """Mengambil record user berdasarkan chat ID."""
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT * FROM logbook_credentials WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_credential(chat_id: int) -> Optional[tuple[str, str]]:
    """Mengambil username dan plain password terdekripsi."""
    user = await get_user_by_chat_id(chat_id)
    if not user or not user.get("password_encrypted"):
        return None
    plain = decrypt_text(user["password_encrypted"])
    return user["username"], plain


async def regenerate_api_token(chat_id: int) -> Optional[str]:
    """Membuat ulang token API untuk user."""
    new_token = secrets.token_hex(16)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            """
            UPDATE logbook_credentials 
            SET api_token = ?, updated_at = ? 
            WHERE chat_id = ?
            """,
            (new_token, now_str, chat_id),
        )
        if cursor.rowcount > 0:
            return new_token
    return None


async def delete_user_credential(chat_id: int) -> bool:
    """Menghapus akun user beserta seluruh data draf dan lokasinya."""
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute("DELETE FROM logbook_credentials WHERE chat_id = ?", (chat_id,))
        return cursor.rowcount > 0


async def get_all_users() -> List[dict[str, Any]]:
    """Mengambil seluruh pengguna logbook untuk admin panel."""
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            """
            SELECT c.*, 
                   COUNT(d.id) as total_drafts,
                   MAX(d.date) as last_draft_date
            FROM logbook_credentials c
            LEFT JOIN logbook_drafts d ON c.chat_id = d.chat_id
            GROUP BY c.chat_id
            ORDER BY c.created_at DESC
            """
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# --- LOCATIONS REPO ---

async def save_location_profile(
    chat_id: int,
    profile_key: str,
    lat: str,
    lng: str,
    accuracy: str = "15",
    name: Optional[str] = None
) -> None:
    """Menyimpan atau memperbarui profil koordinat GPS pada logbook_location_profiles."""
    default_name = PROFILE_DEFINITIONS.get(profile_key, {}).get("default_name", f"Lokasi {profile_key.title()}")
    final_name = name or default_name
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()

    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        await conn.execute(
            """
            INSERT OR REPLACE INTO logbook_location_profiles 
            (chat_id, profile_key, profile_name, lat, lng, akurasi, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (chat_id, profile_key, final_name, lat, lng, accuracy, now_str),
        )


async def get_user_location_profiles(chat_id: int) -> List[dict[str, Any]]:
    """Mengambil status ketiga profil lokasi (office, home, other) untuk user."""
    profiles = {}
    for key, info in PROFILE_DEFINITIONS.items():
        name = info["default_name"] if isinstance(info, dict) else str(info)
        profiles[key] = {
            "profile_key": key,
            "profile_name": name,
            "lat": None,
            "lng": None,
            "akurasi": DEFAULT_ACCURACY,
            "is_set": False,
            "updated_at": None,
        }

    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            """
            SELECT profile_key, profile_name, lat, lng, akurasi, updated_at 
            FROM logbook_location_profiles 
            WHERE chat_id = ?
            """,
            (chat_id,),
        )
        rows = await cursor.fetchall()
        for r in rows:
            k = r["profile_key"]
            if k in profiles:
                profiles[k]["lat"] = r["lat"]
                profiles[k]["lng"] = r["lng"]
                profiles[k]["akurasi"] = r["akurasi"] or DEFAULT_ACCURACY
                profiles[k]["is_set"] = bool(r["lat"] and r["lng"])
                profiles[k]["updated_at"] = r["updated_at"]

    return list(profiles.values())


async def get_active_location_profile(chat_id: int) -> str:
    """Mengambil key profil lokasi aktif user (default: 'office')."""
    user = await get_user_by_chat_id(chat_id)
    return user["active_location_profile"] if (user and user.get("active_location_profile")) else PROFILE_OFFICE


async def set_active_location_profile(chat_id: int, profile_key: str) -> None:
    """Mengubah profil lokasi aktif yang dipilih user."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        await conn.execute(
            "UPDATE logbook_credentials SET active_location_profile = ?, updated_at = ? WHERE chat_id = ?",
            (profile_key, now_str, chat_id),
        )


async def get_user_location(chat_id: int, profile_key: Optional[str] = None) -> tuple[str, str, str]:
    """Mengambil (lat, lng, accuracy) untuk profil tertentu atau profil aktif user."""
    target_profile = profile_key or await get_active_location_profile(chat_id)
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT lat, lng, akurasi FROM logbook_location_profiles WHERE chat_id = ? AND profile_key = ?",
            (chat_id, target_profile),
        )
        row = await cursor.fetchone()
        if row and row["lat"] and row["lng"]:
            return row["lat"], row["lng"], row["akurasi"] or DEFAULT_ACCURACY

        # Fallback ke office
        cursor_off = await conn.execute(
            "SELECT lat, lng, akurasi FROM logbook_location_profiles WHERE chat_id = ? AND profile_key = 'office'",
            (chat_id,),
        )
        row_off = await cursor_off.fetchone()
        if row_off and row_off["lat"] and row_off["lng"]:
            return row_off["lat"], row_off["lng"], row_off["akurasi"] or DEFAULT_ACCURACY

        # Fallback ke credentials default
        user = await get_user_by_chat_id(chat_id)
        if user and user.get("default_lat"):
            return user["default_lat"], user["default_lng"], user.get("default_akurasi", DEFAULT_ACCURACY)

    return DEFAULT_LAT, DEFAULT_LNG, DEFAULT_ACCURACY


async def update_user_location(chat_id: int, lat: str, lng: str, accuracy: str = "15") -> None:
    """Menyimpan koordinat ke profil lokasi yang saat ini aktif."""
    active_profile = await get_active_location_profile(chat_id)
    await save_location_profile(chat_id, active_profile, lat, lng, accuracy)


# --- DRAFTS REPO ---

async def create_or_get_draft(
    chat_id: int,
    idempotency_key: str,
    date: str,
    projects: list,
    commits_summary: str,
    raw_metadata: list = None,
    jam_masuk: str = "07:10",
    jam_pulang: str = "16:25",
    target_profile: Optional[str] = None
) -> tuple[dict[str, Any], bool]:
    """Membuat draf baru secara idempoten atau mengembalikan draf yang sudah ada."""
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT * FROM logbook_drafts WHERE idempotency_key = ?", (idempotency_key,)
        )
        existing = await cursor.fetchone()
        if existing:
            d = dict(existing)
            d["summary"] = d.get("commits_summary", "")
            return d, False

        proj_json = json.dumps(projects, ensure_ascii=False)
        raw_json = json.dumps(raw_metadata or [], ensure_ascii=False)
        profile_to_use = target_profile or await get_active_location_profile(chat_id)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor_ins = await conn.execute(
            """
            INSERT INTO logbook_drafts 
            (chat_id, idempotency_key, date, projects, commits_summary, raw_metadata, status, jam_masuk, jam_pulang, location_profile, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                idempotency_key,
                date,
                proj_json,
                commits_summary,
                raw_json,
                jam_masuk,
                jam_pulang,
                profile_to_use,
                now_str,
                now_str,
            ),
        )
        draft_id = cursor_ins.lastrowid

        cursor_get = await conn.execute(
            "SELECT * FROM logbook_drafts WHERE id = ?", (draft_id,)
        )
        new_row = dict(await cursor_get.fetchone())
        new_row["summary"] = new_row.get("commits_summary", "")
        return new_row, True


async def get_draft(draft_id: int) -> Optional[dict[str, Any]]:
    """Mengambil data draf berdasarkan ID."""
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute("SELECT * FROM logbook_drafts WHERE id = ?", (draft_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["summary"] = d.get("commits_summary", "")
        return d


async def update_draft_status(draft_id: int, status: str) -> bool:
    """Mengubah status draf logbook."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            "UPDATE logbook_drafts SET status = ?, updated_at = ? WHERE id = ?",
            (status, now_str, draft_id),
        )
        return cursor.rowcount > 0


async def update_draft_summary(draft_id: int, new_summary: str) -> bool:
    """Mengubah isi ringkasan pekerjaan draf logbook."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            "UPDATE logbook_drafts SET commits_summary = ?, updated_at = ? WHERE id = ?",
            (new_summary, now_str, draft_id),
        )
        return cursor.rowcount > 0


async def update_draft_location_profile(draft_id: int, profile_key: str) -> bool:
    """Mengubah profil lokasi yang diasosiasikan dengan draf."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            "UPDATE logbook_drafts SET location_profile = ?, updated_at = ? WHERE id = ?",
            (profile_key, now_str, draft_id),
        )
        return cursor.rowcount > 0


async def update_telegram_message_info(draft_id: int, message_id: int) -> bool:
    """Menyimpan ID pesan Telegram untuk memudahkan edit notifikasi."""
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            "UPDATE logbook_drafts SET telegram_message_id = ? WHERE id = ?",
            (message_id, draft_id),
        )
        return cursor.rowcount > 0


async def get_recent_drafts(chat_id: int, limit: int = 5) -> List[dict[str, Any]]:
    """Mengambil daftar draf logbook terbaru milik pengguna."""
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            """
            SELECT * FROM logbook_drafts 
            WHERE chat_id = ? 
            ORDER BY date DESC, id DESC 
            LIMIT ?
            """,
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["summary"] = d.get("commits_summary", "")
            result.append(d)
        return result


# --- REMINDERS REPO ---

async def update_user_reminder_time(chat_id: int, reminder_time: str) -> None:
    """Memperbarui jam pengingat harian user."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        await conn.execute(
            "UPDATE logbook_credentials SET reminder_time = ?, updated_at = ? WHERE chat_id = ?",
            (reminder_time, now_str, chat_id),
        )


async def get_user_reminder_time(chat_id: int) -> str:
    """Mengambil jam pengingat harian user (default: '16:05')."""
    user = await get_user_by_chat_id(chat_id)
    return user["reminder_time"] if (user and user.get("reminder_time")) else DEFAULT_REMINDER_TIME


async def update_user_reminder_days(chat_id: int, reminder_days: str) -> None:
    """Memperbarui hari aktif pengingat (misal: '0,1,2,3,4')."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        await conn.execute(
            "UPDATE logbook_credentials SET reminder_days = ?, updated_at = ? WHERE chat_id = ?",
            (reminder_days, now_str, chat_id),
        )


async def get_user_reminder_days(chat_id: int) -> str:
    """Mengambil daftar indeks hari pengingat aktif."""
    user = await get_user_by_chat_id(chat_id)
    return user["reminder_days"] if (user and user.get("reminder_days") is not None) else DEFAULT_REMINDER_DAYS


async def get_active_reminder_users() -> List[dict[str, Any]]:
    """Mengambil semua pengguna terdaftar untuk dievaluasi oleh scheduler pengingat."""
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT chat_id, username, reminder_time, reminder_days FROM logbook_credentials WHERE reminder_days != ''"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_or_create_reminder_state(chat_id: int, date_str: str) -> dict[str, Any]:
    """Mengambil atau menginisialisasi state pengingat harian user."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT * FROM logbook_reminder_state WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()

        if row and row["target_date"] == date_str:
            return dict(row)

        await conn.execute(
            """
            INSERT OR REPLACE INTO logbook_reminder_state 
            (chat_id, target_date, status, retry_count, updated_at)
            VALUES (?, ?, 'idle', 0, ?)
            """,
            (chat_id, date_str, now_str),
        )

        cursor_get = await conn.execute(
            "SELECT * FROM logbook_reminder_state WHERE chat_id = ?", (chat_id,)
        )
        return dict(await cursor_get.fetchone())


async def update_reminder_state(chat_id: int, date_str: str, status: str, count_increment: int = 1) -> None:
    """Memperbarui status dan jumlah counter pengingat."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        await conn.execute(
            """
            UPDATE logbook_reminder_state 
            SET retry_count = retry_count + ?, 
                status = ?, 
                updated_at = ? 
            WHERE chat_id = ? AND target_date = ?
            """,
            (count_increment, status, now_str, chat_id, date_str),
        )


async def stop_reminder_for_today(chat_id: int, date_str: str) -> None:
    """Menghentikan pengingat untuk hari ini setelah user menekan tombol 'Hentikan'."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        await conn.execute(
            """
            UPDATE logbook_reminder_state 
            SET status = 'stopped', updated_at = ? 
            WHERE chat_id = ? AND target_date = ?
            """,
            (now_str, chat_id, date_str),
        )


async def complete_reminder_for_today(chat_id: int, date_str: str) -> None:
    """Menandai pengingat hari ini selesai (sudah dibuat draf/submit)."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        await conn.execute(
            """
            UPDATE logbook_reminder_state 
            SET status = 'completed', updated_at = ? 
            WHERE chat_id = ? AND target_date = ?
            """,
            (now_str, chat_id, date_str),
        )


async def has_today_draft_or_submission(chat_id: int, date_str: str) -> bool:
    """Memeriksa apakah user sudah memiliki draf submitted/draft untuk tanggal hari ini."""
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            """
            SELECT id FROM logbook_drafts 
            WHERE chat_id = ? AND date = ? AND status IN ('submitted', 'draft')
            """,
            (chat_id, date_str),
        )
        return bool(await cursor.fetchone())


# --- WEEKLY REMINDERS REPO ---

async def get_weekly_reminder_state(chat_id: int, week_start_date: str) -> Optional[dict[str, Any]]:
    """Mengambil status pengingat tanda tangan mingguan untuk minggu tertentu."""
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT * FROM logbook_weekly_reminders WHERE chat_id = ? AND week_start_date = ?",
            (chat_id, week_start_date),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def set_weekly_reminder_status(
    chat_id: int,
    week_start_date: str,
    status: str,
    week_label: Optional[str] = None,
    last_reminded_date: Optional[str] = None
) -> None:
    """Menyimpan atau memperbarui status pengingat mingguan."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = get_settings()
    async with get_db_connection(settings.LOGBOOK_DB_PATH) as conn:
        existing = await get_weekly_reminder_state(chat_id, week_start_date)
        if existing:
            query = "UPDATE logbook_weekly_reminders SET status = ?, updated_at = ?"
            params = [status, now_str]
            if week_label:
                query += ", week_label = ?"
                params.append(week_label)
            if last_reminded_date:
                query += ", last_reminded_date = ?"
                params.append(last_reminded_date)
            query += " WHERE chat_id = ? AND week_start_date = ?"
            params.extend([chat_id, week_start_date])
            await conn.execute(query, tuple(params))
        else:
            await conn.execute(
                """
                INSERT INTO logbook_weekly_reminders 
                (chat_id, week_start_date, week_label, status, last_reminded_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (chat_id, week_start_date, week_label or "", status, last_reminded_date or "", now_str),
            )


async def stop_weekly_reminder(chat_id: int, week_start_date: str) -> None:
    """Menghentikan pengingat tanda tangan logbook untuk minggu tertentu."""
    await set_weekly_reminder_status(chat_id, week_start_date, status="stopped")

