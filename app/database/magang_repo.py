"""
Repository async untuk modul Magang (users.db - diarsipkan).
"""

from typing import Any, List, Optional
from app.core.config import get_settings
from app.core.logger import logger
from app.database.connection import get_db_connection
from app.services.crypto import decrypt_text, encrypt_text


async def init_magang_db() -> None:
    """Inisialisasi tabel users untuk modul magang."""
    settings = get_settings()
    async with get_db_connection(settings.MAGANG_DB_PATH) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                password TEXT,
                last_status TEXT
            )
        """)
    logger.info("[DB-MAGANG] Database magang users.db berhasil diinisialisasi (Async).")


async def add_magang_user(chat_id: int, username: str, plain_password: str) -> None:
    """Menyimpan atau memperbarui user magang dengan password terenkripsi."""
    settings = get_settings()
    enc_pass = encrypt_text(plain_password, settings.MAGANG_SECRET_KEY)
    async with get_db_connection(settings.MAGANG_DB_PATH) as conn:
        await conn.execute(
            """
            INSERT OR REPLACE INTO users (chat_id, username, password, last_status)
            VALUES (?, ?, ?, NULL)
            """,
            (chat_id, username, enc_pass),
        )
    logger.info(f"[DB-MAGANG] User magang {chat_id} ({username}) berhasil disimpan.")


async def remove_magang_user(chat_id: int) -> bool:
    """Menghapus user magang dari database."""
    settings = get_settings()
    async with get_db_connection(settings.MAGANG_DB_PATH) as conn:
        cursor = await conn.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
        return cursor.rowcount > 0


async def update_magang_status(chat_id: int, status: str) -> bool:
    """Memperbarui status lamaran magang terakhir user."""
    settings = get_settings()
    async with get_db_connection(settings.MAGANG_DB_PATH) as conn:
        cursor = await conn.execute(
            "UPDATE users SET last_status = ? WHERE chat_id = ?", (status, chat_id)
        )
        return cursor.rowcount > 0


async def get_all_magang_users() -> List[dict[str, Any]]:
    """Mengambil semua user magang dan mendekripsi passwordnya."""
    settings = get_settings()
    async with get_db_connection(settings.MAGANG_DB_PATH) as conn:
        cursor = await conn.execute("SELECT chat_id, username, password, last_status FROM users")
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["plain_password"] = decrypt_text(d["password"], settings.MAGANG_SECRET_KEY)
            except Exception:
                d["plain_password"] = ""
            result.append(d)
        return result

