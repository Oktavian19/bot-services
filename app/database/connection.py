"""
Database connection manager berbasis aiosqlite.
Menyediakan context manager asinkron dengan konfigurasi PRAGMA optimal (WAL mode, foreign keys, busy timeout).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Union
import aiosqlite
from app.core.logger import logger


@asynccontextmanager
async def get_db_connection(db_path: Union[str, Path]) -> AsyncGenerator[aiosqlite.Connection, None]:
    """
    Context manager async untuk koneksi SQLite.
    Mengaktifkan WAL mode, timeout 5000ms, foreign keys, dan row factory Row.
    """
    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(str(path_obj)) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA busy_timeout=5000;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            await conn.commit()
        except Exception as e:
            await conn.rollback()
            logger.error(f"[DB-ASYNC] Error saat transaksi SQLite di {path_obj}: {e}")
            raise

