"""
Service backup online SQLite WAL-safe dan pengiriman arsip ke Telegram Admin.
Menggunakan SQLite Online Backup API (sqlite3.Connection.backup) agar aman dijalankan saat bot aktif.
"""

import asyncio
from contextlib import closing
from datetime import datetime
import html
from pathlib import Path
import sqlite3
import tempfile
from typing import Any
import zipfile
from aiogram import Bot
from aiogram.types import FSInputFile
from app.core.config import get_settings
from app.core.logger import logger
from app.services.reminder_service import get_local_now


def _backup_single_db(src_path: Path, dest_path: Path) -> dict[str, Any]:
    """Membuat salinan konsisten database SQLite (termasuk WAL) dan memverifikasi integritasnya."""
    with closing(sqlite3.connect(str(src_path), timeout=5.0)) as src_conn:
        with closing(sqlite3.connect(str(dest_path))) as dst_conn:
            src_conn.backup(dst_conn)
            cur = dst_conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            integrity_rows = cur.fetchall()
            integrity = (
                "OK"
                if integrity_rows and len(integrity_rows) == 1 and str(integrity_rows[0][0]).lower() == "ok"
                else "; ".join(str(r[0]) for r in integrity_rows)
            )
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            tables = [r[0] for r in cur.fetchall()]
            table_counts = {}
            for tbl in tables:
                safe_tbl = tbl.replace('"', '""')
                cur.execute(f'SELECT COUNT(*) FROM "{safe_tbl}";')
                row = cur.fetchone()
                table_counts[tbl] = row[0] if row else 0

    return {
        "name": src_path.name,
        "size_bytes": dest_path.stat().st_size,
        "integrity": integrity,
        "tables": table_counts,
    }


def _collect_existing_db_paths() -> list[Path]:
    """Mengumpulkan path database SQLite unik yang tersedia di disk."""
    settings = get_settings()
    candidates = [
        settings.REMINDER_DB_PATH,
        settings.BENSIN_DB_PATH,
        settings.LOGBOOK_DB_PATH,
        settings.MAGANG_DB_PATH,
    ]
    seen: set[Path] = set()
    existing: list[Path] = []
    for raw_path in candidates:
        resolved = Path(raw_path).resolve()
        if resolved not in seen and resolved.exists() and resolved.is_file():
            seen.add(resolved)
            existing.append(resolved)
    return existing


def create_sqlite_backup_archive(output_dir: Path) -> tuple[Path, list[dict[str, Any]]]:
    """Menjalankan online backup seluruh DB SQLite ke dalam satu arsip ZIP beserta manifest."""
    db_paths = _collect_existing_db_paths()
    now = get_local_now()
    ts = now.strftime("%Y%m%d_%H%M%S")
    zip_path = output_dir / f"bot-services_backup_{ts}.zip"

    if not db_paths:
        return zip_path, []

    stats: list[dict[str, Any]] = []
    manifest_lines = [f"bot-services SQLite Online Backup @ {now.isoformat()}", ""]

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src in db_paths:
            snap_path = output_dir / src.name
            info = _backup_single_db(src, snap_path)
            stats.append(info)
            zf.write(snap_path, arcname=src.name)

            tables_summary = ", ".join(f"{k}={v}" for k, v in info["tables"].items()) or "no tables"
            manifest_lines.append(
                f"- {info['name']} | size={info['size_bytes']}B | integrity={info['integrity']} | {tables_summary}"
            )
        zf.writestr("manifest.txt", "\n".join(manifest_lines) + "\n")

    return zip_path, stats


def _format_backup_caption(zip_size: int, stats: list[dict[str, Any]], scheduled: bool) -> str:
    """Menyusun caption HTML ringkasan backup untuk pesan Telegram."""
    mode_label = "Terjadwal (Mingguan)" if scheduled else "Manual (/backup)"
    now_str = get_local_now().strftime("%Y-%m-%d %H:%M:%S WIB")
    lines = [
        f"🗄 <b>Backup Database SQLite — {mode_label}</b>",
        f"🕒 Waktu: <code>{now_str}</code>",
        f"📦 Ukuran ZIP: <code>{zip_size / 1024:.1f} KB</code>\n",
    ]
    for item in stats:
        total_rows = sum(item["tables"].values())
        status_icon = "✅" if item["integrity"] == "OK" else "⚠️"
        lines.append(
            f"{status_icon} <code>{html.escape(item['name'])}</code> — "
            f"{item['size_bytes'] / 1024:.1f} KB ({total_rows} baris | {html.escape(item['integrity'])})"
        )
    lines.append("\n🔐 <i>File .env/.env.bot tidak disertakan demi keamanan kunci enkripsi.</i>")
    return "\n".join(lines)


async def send_sqlite_backup_to_telegram(
    bot: Bot,
    target_chat_id: int,
    scheduled: bool = False,
) -> tuple[bool, str]:
    """Membuat backup arsip ZIP seluruh DB SQLite dan mengirimkannya ke chat admin."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path, stats = await asyncio.to_thread(create_sqlite_backup_archive, Path(tmpdir))
            if not stats:
                return False, "Tidak ada file database SQLite yang ditemukan untuk dibackup."

            zip_size = zip_path.stat().st_size
            if zip_size > 49 * 1024 * 1024:
                return False, f"Ukuran backup ({zip_size / (1024 * 1024):.1f} MB) melebihi batas upload bot Telegram (50 MB)."

            caption = _format_backup_caption(zip_size, stats, scheduled=scheduled)
            await bot.send_document(
                chat_id=target_chat_id,
                document=FSInputFile(str(zip_path), filename=zip_path.name),
                caption=caption,
                parse_mode="HTML",
            )
            logger.info(f"[BACKUP] Arsip {zip_path.name} ({zip_size}B) berhasil dikirim ke {target_chat_id}.")
            return True, f"Backup {zip_path.name} berhasil dikirim."
    except Exception as exc:
        logger.error(f"[BACKUP - ERROR] Gagal membuat/mengirim backup SQLite: {exc}")
        return False, f"Gagal membuat backup: {exc}"


async def run_scheduled_backup(bot: Bot) -> None:
    """Job scheduler untuk auto-backup mingguan ke ADMIN_CHAT_ID."""
    settings = get_settings()
    if not settings.ADMIN_CHAT_ID:
        logger.warning("[BACKUP] ADMIN_CHAT_ID belum diatur; auto-backup terjadwal dilewati.")
        return
    await send_sqlite_backup_to_telegram(bot, settings.ADMIN_CHAT_ID, scheduled=True)
