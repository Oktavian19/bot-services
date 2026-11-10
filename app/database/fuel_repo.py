"""
Repository async untuk modul bensin & motor (bensin.db).
Mendukung pelacakan BBM, odometer nullable, akumulasi liter pending, dan recalculation otomatis.
"""

from typing import Any, List, Optional
from app.core.config import get_settings
from app.core.logger import logger
from app.database.connection import get_db_connection


async def init_fuel_db() -> None:
    """Inisialisasi tabel motor dan log_bensin, serta migrasi skema bila diperlukan."""
    settings = get_settings()
    async with get_db_connection(settings.BENSIN_DB_PATH) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS motor (
                chat_id INTEGER PRIMARY KEY,
                nama_motor TEXT NOT NULL,
                odometer_awal REAL NOT NULL,
                odometer_terakhir REAL NOT NULL,
                odometer_terakhir_oli REAL DEFAULT NULL
            )
        """)

        # Cek kolom odometer_terakhir_oli
        cursor = await conn.execute("PRAGMA table_info(motor)")
        columns_motor = await cursor.fetchall()
        col_names_motor = [c["name"] for c in columns_motor]
        if "odometer_terakhir_oli" not in col_names_motor:
            logger.info("[DB-BENSIN] Menambahkan kolom odometer_terakhir_oli ke tabel motor...")
            await conn.execute("ALTER TABLE motor ADD COLUMN odometer_terakhir_oli REAL DEFAULT NULL")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS log_bensin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                odometer REAL,
                rupiah INTEGER NOT NULL,
                liter REAL NOT NULL,
                jarak_tempuh REAL DEFAULT 0,
                konsumsi_kml REAL DEFAULT 0,
                tanggal DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Cek migrasi nullable odometer jika kolom masih not null
        cursor = await conn.execute("PRAGMA table_info(log_bensin)")
        columns = await cursor.fetchall()
        odo_col = next((c for c in columns if c["name"] == "odometer"), None)
        if odo_col and odo_col["notnull"] == 1:
            logger.info("[DB-BENSIN] Menjalankan migrasi skema tabel log_bensin (nullable odometer)...")
            await conn.execute("""
                CREATE TABLE log_bensin_migration (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    odometer REAL,
                    rupiah INTEGER NOT NULL,
                    liter REAL NOT NULL,
                    jarak_tempuh REAL DEFAULT 0,
                    konsumsi_kml REAL DEFAULT 0,
                    tanggal DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                INSERT INTO log_bensin_migration (id, chat_id, odometer, rupiah, liter, jarak_tempuh, konsumsi_kml, tanggal)
                SELECT id, chat_id, odometer, rupiah, liter, jarak_tempuh, konsumsi_kml, tanggal FROM log_bensin
            """)
            await conn.execute("DROP TABLE log_bensin")
            await conn.execute("ALTER TABLE log_bensin_migration RENAME TO log_bensin")
            logger.info("[DB-BENSIN] Migrasi skema log_bensin selesai!")

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_log_bensin_chat 
            ON log_bensin(chat_id);
        """)
    logger.info("[DB-BENSIN] Database bensin.db berhasil diinisialisasi (Async).")


async def register_motor(
    chat_id: int,
    nama_motor: str,
    odometer_awal: float,
    odometer_terakhir_oli: Optional[float] = None
) -> None:
    """Mendaftarkan atau memperbarui motor milik pengguna."""
    settings = get_settings()
    async with get_db_connection(settings.BENSIN_DB_PATH) as conn:
        await conn.execute(
            """
            INSERT OR REPLACE INTO motor (chat_id, nama_motor, odometer_awal, odometer_terakhir, odometer_terakhir_oli)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, nama_motor, odometer_awal, odometer_awal, odometer_terakhir_oli),
        )
    logger.info(f"[DB-BENSIN] Data motor '{nama_motor}' berhasil disimpan untuk User {chat_id}.")


async def get_motor(chat_id: int) -> Optional[dict[str, Any]]:
    """Mengambil data motor milik pengguna."""
    settings = get_settings()
    async with get_db_connection(settings.BENSIN_DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT nama_motor, odometer_awal, odometer_terakhir, odometer_terakhir_oli FROM motor WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_odometer_oli(chat_id: int, odometer_oli: float) -> bool:
    """Memperbarui nilai odometer saat terakhir kali ganti oli."""
    settings = get_settings()
    async with get_db_connection(settings.BENSIN_DB_PATH) as conn:
        cursor = await conn.execute(
            "UPDATE motor SET odometer_terakhir_oli = ? WHERE chat_id = ?",
            (odometer_oli, chat_id),
        )
        updated = cursor.rowcount > 0
    if updated:
        logger.info(f"[DB-BENSIN] Odometer ganti oli User {chat_id} diperbarui menjadi {odometer_oli} km.")
    return updated


async def get_status_oli(chat_id: int) -> Optional[dict[str, Any]]:
    """Menghitung status kelayakan dan interval ganti oli motor (setiap 3000 km)."""
    motor = await get_motor(chat_id)
    if not motor:
        return None

    odo_akhir = motor["odometer_terakhir"]
    odo_oli = motor["odometer_terakhir_oli"]

    if odo_oli is None:
        return {
            "status": "belum_diatur",
            "terakhir_oli": None,
            "target_oli": None,
            "odo_sekarang": odo_akhir,
            "jarak_sejak_oli": 0.0,
            "sisa_km": 0.0,
        }

    target_oli = odo_oli + 3000.0
    jarak_sejak_oli = odo_akhir - odo_oli
    sisa_km = target_oli - odo_akhir

    if sisa_km < 0:
        status = "terlewat"
    elif sisa_km <= 200:
        status = "mendekati"
    else:
        status = "aman"

    return {
        "status": status,
        "terakhir_oli": odo_oli,
        "target_oli": target_oli,
        "odo_sekarang": odo_akhir,
        "jarak_sejak_oli": jarak_sejak_oli,
        "sisa_km": sisa_km,
    }


async def add_log_bensin(
    chat_id: int,
    odometer_sekarang: Optional[float],
    rupiah: int,
    liter: float
) -> Optional[dict[str, Any]]:
    """Menambahkan log transaksi bensin dengan kalkulasi akumulasi bila tanpa odometer."""
    settings = get_settings()
    async with get_db_connection(settings.BENSIN_DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT odometer_terakhir FROM motor WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        if not row:
            logger.warning(f"[DB-BENSIN] User {chat_id} belum mendaftarkan motor.")
            return None

        odometer_terakhir = row["odometer_terakhir"]

        # Kasus 1: Tanpa Odometer
        if odometer_sekarang is None:
            await conn.execute(
                """
                INSERT INTO log_bensin (chat_id, odometer, rupiah, liter, jarak_tempuh, konsumsi_kml)
                VALUES (?, NULL, ?, ?, 0, 0)
                """,
                (chat_id, rupiah, liter),
            )
            logger.info(f"[DB-BENSIN] Log tanpa odo (Rp{rupiah}, {liter:.2f}L) disimpan untuk User {chat_id}.")
            return {
                "tanpa_odo": True,
                "rupiah": rupiah,
                "liter": round(liter, 2),
                "jarak": 0.0,
                "kml": 0.0,
            }

        # Kasus 2: Dengan Odometer (Hitung jarak & akumulasi liter pending)
        odometer_sekarang = float(odometer_sekarang)
        cursor = await conn.execute(
            """
            SELECT id FROM log_bensin 
            WHERE chat_id = ? AND odometer IS NOT NULL 
            ORDER BY id DESC LIMIT 1
            """,
            (chat_id,),
        )
        last_odo_log = await cursor.fetchone()

        if last_odo_log:
            last_id = last_odo_log["id"]
            cursor_pending = await conn.execute(
                """
                SELECT SUM(liter) as sum_l, COUNT(*) as cnt 
                FROM log_bensin 
                WHERE chat_id = ? AND id > ? AND odometer IS NULL
                """,
                (chat_id, last_id),
            )
        else:
            cursor_pending = await conn.execute(
                """
                SELECT SUM(liter) as sum_l, COUNT(*) as cnt 
                FROM log_bensin 
                WHERE chat_id = ? AND odometer IS NULL
                """,
                (chat_id,),
            )

        row_pending = await cursor_pending.fetchone()
        pending_liters = row_pending["sum_l"] if (row_pending and row_pending["sum_l"]) else 0.0
        pending_count = row_pending["cnt"] if (row_pending and row_pending["cnt"]) else 0

        jarak_tempuh = odometer_sekarang - odometer_terakhir
        total_liter = pending_liters + liter
        konsumsi_kml = round(jarak_tempuh / total_liter, 2) if total_liter > 0 else 0.0

        await conn.execute(
            """
            INSERT INTO log_bensin (chat_id, odometer, rupiah, liter, jarak_tempuh, konsumsi_kml)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chat_id, odometer_sekarang, rupiah, liter, jarak_tempuh, konsumsi_kml),
        )
        await conn.execute(
            "UPDATE motor SET odometer_terakhir = ? WHERE chat_id = ?",
            (odometer_sekarang, chat_id),
        )

    logger.info(f"[DB-BENSIN] Log transaksi (Rp{rupiah}, {liter:.2f}L) disimpan untuk User {chat_id}. Km/L: {konsumsi_kml}")
    return {
        "tanpa_odo": False,
        "jarak": jarak_tempuh,
        "liter": round(liter, 2),
        "kml": konsumsi_kml,
        "total_liter_akumulasi": round(total_liter, 2),
        "jumlah_log_tanpa_odo": pending_count,
    }


async def get_statistik_bensin(chat_id: int) -> dict[str, float]:
    """Menghitung rata-rata dan konsumsi terakhir km/L."""
    settings = get_settings()
    async with get_db_connection(settings.BENSIN_DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT odometer_awal, odometer_terakhir FROM motor WHERE chat_id = ?", (chat_id,)
        )
        motor = await cursor.fetchone()
        if not motor:
            return {"rata_rata": 0.0, "terakhir": 0.0}

        odo_awal = motor["odometer_awal"]
        odo_akhir = motor["odometer_terakhir"]
        total_jarak = odo_akhir - odo_awal

        cursor = await conn.execute(
            """
            SELECT id, konsumsi_kml 
            FROM log_bensin 
            WHERE chat_id = ? AND odometer IS NOT NULL 
            ORDER BY id DESC LIMIT 1
            """,
            (chat_id,),
        )
        last_odo_log = await cursor.fetchone()
        if not last_odo_log or total_jarak <= 0:
            return {"rata_rata": 0.0, "terakhir": 0.0}

        last_id = last_odo_log["id"]
        terakhir_kml = last_odo_log["konsumsi_kml"]

        cursor_sum = await conn.execute(
            "SELECT SUM(liter) as sum_l FROM log_bensin WHERE chat_id = ? AND id <= ?",
            (chat_id, last_id),
        )
        row_sum = await cursor_sum.fetchone()
        total_liter_verified = row_sum["sum_l"] if row_sum and row_sum["sum_l"] else 0.0

        rata_rata_kml = round(total_jarak / total_liter_verified, 2) if total_liter_verified > 0 else 0.0

    return {
        "rata_rata": rata_rata_kml,
        "terakhir": terakhir_kml,
    }


async def recalculate_bensin_logs(chat_id: int) -> None:
    """Menghitung ulang jarak tempuh, km/L, dan odometer terakhir untuk semua log milik user."""
    settings = get_settings()
    async with get_db_connection(settings.BENSIN_DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT odometer_awal FROM motor WHERE chat_id = ?", (chat_id,)
        )
        row_motor = await cursor.fetchone()
        if not row_motor:
            return

        odometer_prev = row_motor["odometer_awal"]
        pending_liters = 0.0

        cursor = await conn.execute(
            "SELECT id, odometer, liter FROM log_bensin WHERE chat_id = ? ORDER BY id ASC",
            (chat_id,),
        )
        logs = await cursor.fetchall()

        for log in logs:
            log_id = log["id"]
            odometer = log["odometer"]
            liter = log["liter"]

            if odometer is None:
                pending_liters += liter
                await conn.execute(
                    "UPDATE log_bensin SET jarak_tempuh = 0, konsumsi_kml = 0 WHERE id = ?",
                    (log_id,),
                )
            else:
                jarak_tempuh = odometer - odometer_prev
                total_liter = pending_liters + liter
                konsumsi_kml = round(jarak_tempuh / total_liter, 2) if total_liter > 0 else 0.0

                await conn.execute(
                    "UPDATE log_bensin SET jarak_tempuh = ?, konsumsi_kml = ? WHERE id = ?",
                    (jarak_tempuh, konsumsi_kml, log_id),
                )
                pending_liters = 0.0
                odometer_prev = odometer

        await conn.execute(
            "UPDATE motor SET odometer_terakhir = ? WHERE chat_id = ?",
            (odometer_prev, chat_id),
        )

    logger.info(f"[DB-BENSIN] Recalculation selesai untuk User {chat_id}. Odo Terakhir: {odometer_prev}")


async def get_logs_bensin(chat_id: int, limit: int = 10) -> List[dict[str, Any]]:
    """Mengambil riwayat log bensin terbaru."""
    settings = get_settings()
    async with get_db_connection(settings.BENSIN_DB_PATH) as conn:
        cursor = await conn.execute(
            """
            SELECT id, odometer, rupiah, liter, jarak_tempuh, konsumsi_kml, tanggal 
            FROM log_bensin 
            WHERE chat_id = ? 
            ORDER BY id DESC 
            LIMIT ?
            """,
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_log_bensin_by_id(log_id: int, chat_id: int) -> Optional[dict[str, Any]]:
    """Mengambil satu log bensin spesifik."""
    settings = get_settings()
    async with get_db_connection(settings.BENSIN_DB_PATH) as conn:
        cursor = await conn.execute(
            """
            SELECT id, odometer, rupiah, liter, jarak_tempuh, konsumsi_kml, tanggal 
            FROM log_bensin 
            WHERE id = ? AND chat_id = ?
            """,
            (log_id, chat_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_log_bensin(log_id: int, chat_id: int) -> bool:
    """Menghapus satu log bensin dan memicu recalculation riwayat."""
    settings = get_settings()
    async with get_db_connection(settings.BENSIN_DB_PATH) as conn:
        cursor = await conn.execute(
            "DELETE FROM log_bensin WHERE id = ? AND chat_id = ?",
            (log_id, chat_id),
        )
        deleted = cursor.rowcount > 0

    if deleted:
        logger.info(f"[DB-BENSIN] Log #{log_id} dihapus untuk User {chat_id}. Memulai recalculation...")
        await recalculate_bensin_logs(chat_id)
    return deleted


async def update_log_bensin(
    log_id: int,
    chat_id: int,
    odometer: Optional[float],
    rupiah: int,
    liter: float
) -> bool:
    """Memperbarui satu log bensin dan memicu recalculation riwayat."""
    settings = get_settings()
    async with get_db_connection(settings.BENSIN_DB_PATH) as conn:
        if odometer is None:
            cursor = await conn.execute(
                """
                UPDATE log_bensin 
                SET odometer = NULL, rupiah = ?, liter = ? 
                WHERE id = ? AND chat_id = ?
                """,
                (rupiah, liter, log_id, chat_id),
            )
        else:
            cursor = await conn.execute(
                """
                UPDATE log_bensin 
                SET odometer = ?, rupiah = ?, liter = ? 
                WHERE id = ? AND chat_id = ?
                """,
                (odometer, rupiah, liter, log_id, chat_id),
            )
        updated = cursor.rowcount > 0

    if updated:
        logger.info(f"[DB-BENSIN] Log #{log_id} diperbarui untuk User {chat_id}. Memulai recalculation...")
        await recalculate_bensin_logs(chat_id)
    return updated

