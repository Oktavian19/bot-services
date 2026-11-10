"""
Repository async untuk modul reminder (reminders.db).
"""

from typing import Any, List, Optional
from app.core.config import get_settings
from app.core.logger import logger
from app.database.connection import get_db_connection


async def init_reminder_db() -> None:
    """Inisialisasi tabel reminders dan indeks di reminders.db."""
    settings = get_settings()
    async with get_db_connection(settings.REMINDER_DB_PATH) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                target_date DATE NOT NULL,
                notify_time TIME NOT NULL,
                prep_days INTEGER NOT NULL,
                status TEXT DEFAULT 'active'
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reminders_active_time 
            ON reminders(status, notify_time);
        """)
    logger.info("[DB-REMINDER] Database reminders.db berhasil diinisialisasi (Async WAL Mode).")


async def insert_reminder(
    chat_id: int,
    message: str,
    target_date: str,
    notify_time: str,
    prep_days: int
) -> int:
    """Menyimpan pengingat baru ke database."""
    settings = get_settings()
    async with get_db_connection(settings.REMINDER_DB_PATH) as conn:
        cursor = await conn.execute(
            """
            INSERT INTO reminders (chat_id, message, target_date, notify_time, prep_days, status)
            VALUES (?, ?, ?, ?, ?, 'active')
            """,
            (chat_id, message, target_date, notify_time, prep_days),
        )
        reminder_id = cursor.lastrowid or 0
    logger.info(f"[DB-REMINDER] Pengingat baru ID {reminder_id} (Hari-H: {target_date}) disimpan untuk user {chat_id}.")
    return reminder_id


async def get_due_reminders(current_time: str) -> List[dict[str, Any]]:
    """Mengambil pengingat aktif yang cocok dengan jam saat ini (HH:MM)."""
    settings = get_settings()
    async with get_db_connection(settings.REMINDER_DB_PATH) as conn:
        cursor = await conn.execute(
            """
            SELECT id, chat_id, message, target_date, prep_days 
            FROM reminders 
            WHERE status = 'active' AND notify_time = ?
            """,
            (current_time,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def mark_reminder_completed(reminder_id: int) -> bool:
    """Mengubah status pengingat menjadi 'completed'."""
    settings = get_settings()
    async with get_db_connection(settings.REMINDER_DB_PATH) as conn:
        cursor = await conn.execute(
            "UPDATE reminders SET status = 'completed' WHERE id = ?",
            (reminder_id,),
        )
        updated = cursor.rowcount > 0
    logger.info(f"[DB-REMINDER] Pengingat ID {reminder_id} ditandai sebagai completed.")
    return updated


async def get_active_reminders_by_chat(chat_id: int) -> List[dict[str, Any]]:
    """Mengambil semua pengingat aktif milik user tertentu."""
    settings = get_settings()
    async with get_db_connection(settings.REMINDER_DB_PATH) as conn:
        cursor = await conn.execute(
            """
            SELECT id, message, target_date, notify_time, prep_days 
            FROM reminders 
            WHERE chat_id = ? AND status = 'active'
            ORDER BY target_date ASC, notify_time ASC
            """,
            (chat_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_reminder_by_id(reminder_id: int) -> Optional[dict[str, Any]]:
    """Mengambil data pengingat berdasarkan ID."""
    settings = get_settings()
    async with get_db_connection(settings.REMINDER_DB_PATH) as conn:
        cursor = await conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_reminder(reminder_id: int) -> bool:
    """Menghapus pengingat dari database."""
    settings = get_settings()
    async with get_db_connection(settings.REMINDER_DB_PATH) as conn:
        cursor = await conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        deleted = cursor.rowcount > 0
    logger.info(f"[DB-REMINDER] Pengingat ID {reminder_id} berhasil dihapus.")
    return deleted


async def update_reminder_field(reminder_id: int, field: str, value: Any) -> bool:
    """Memperbarui field spesifik pada pengingat."""
    allowed_fields = {'message', 'target_date', 'notify_time', 'prep_days', 'status'}
    if field not in allowed_fields:
        logger.warning(f"[DB-REMINDER] Field update '{field}' ditolak.")
        return False

    settings = get_settings()
    async with get_db_connection(settings.REMINDER_DB_PATH) as conn:
        cursor = await conn.execute(
            f"UPDATE reminders SET {field} = ? WHERE id = ?",
            (value, reminder_id),
        )
        updated = cursor.rowcount > 0
    logger.info(f"[DB-REMINDER] Field '{field}' pada pengingat ID {reminder_id} diperbarui.")
    return updated

