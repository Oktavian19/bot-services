"""
Orkestrator background tasks dan scheduler berbasis APScheduler (AsyncIOScheduler) dan asyncio.
Mengelola eksekusi rutin pengingat agenda, pengingat harian logbook, dan monitoring jaringan.
"""

import asyncio
from datetime import datetime, timedelta
import random
from typing import Optional
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from app.core.config import get_settings
from app.core.logger import logger
from app.database.logbook_repo import (
    complete_reminder_for_today,
    get_active_reminder_users,
    get_or_create_reminder_state,
    has_today_draft_or_submission,
    update_reminder_state,
)
from app.services.logbook_service import fetch_dermaga_table
from app.services.network_service import network_monitor_task
from app.services.reminder_service import get_local_now, process_due_reminders

_monitor_task: Optional[asyncio.Task] = None


async def process_logbook_reminders(bot: Bot) -> None:
    """Mengevaluasi pengingat logbook pengguna untuk hari ini."""
    now = get_local_now()
    today_str = now.strftime("%Y-%m-%d")
    current_time_str = now.strftime("%H:%M")

    try:
        active_users = await get_active_reminder_users()
        for user in active_users:
            chat_id = user["chat_id"]
            reminder_time = user.get("reminder_time", "16:05")
            reminder_days_str = user.get("reminder_days", "0,1,2,3,4")

            # Cek hari aktif
            if not reminder_days_str or not reminder_days_str.strip():
                continue
            active_days = [int(x.strip()) for x in reminder_days_str.split(",") if x.strip().isdigit()]
            if now.weekday() not in active_days:
                continue

            # Cek apakah sudah ada draf / submission hari ini
            if await has_today_draft_or_submission(chat_id, today_str):
                await complete_reminder_for_today(chat_id, today_str)
                continue

            # Cek state pengingat
            state = await get_or_create_reminder_state(chat_id, today_str)
            status = state.get("status", "idle")
            if status in ("completed", "stopped"):
                continue

            should_remind = False
            is_retry = False

            if status == "idle" and current_time_str == reminder_time:
                should_remind = True
                is_retry = False
            elif status == "reminded":
                # Retry evaluation
                pass  # Sederhanakan untuk menghindari spam, atau biarkan user mengatur jam

            if not should_remind:
                continue

            # Cek ke portal DERMAGA apakah sudah submit manual di web
            try:
                entries = await fetch_dermaga_table(chat_id)
                today_entry = next((e for e in entries if today_str in e["tanggal_text"]), None)
                if today_entry:
                    logger.info(f"[LOGBOOK-SCHEDULER] User {chat_id} sudah mengisi logbook di web untuk {today_str}.")
                    await complete_reminder_for_today(chat_id, today_str)
                    continue
            except Exception as e:
                logger.warning(f"[LOGBOOK-SCHEDULER] Lewati cek web DERMAGA user {chat_id}: {e}")

            # Kirim notifikasi pengingat
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✍️ Isi Logbook", callback_data=f"log_remind_fill_{today_str}")],
                [InlineKeyboardButton(text="🔕 Berhenti Ingatkan Hari Ini", callback_data=f"log_remind_stop_{today_str}")],
            ])

            text = (
                f"🔔 <b>Pengingat Logbook DERMAGA</b>\n\n"
                f"Halo <b>{user['username']}</b>, Anda terdeteksi <b>belum mengisi logbook</b> untuk hari ini:\n"
                f"🗓 Tanggal: <code>{today_str}</code>\n\n"
                f"Silakan klik tombol <b>✍️ Isi Logbook</b> di bawah untuk langsung mengisinya melalui bot."
            )

            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=keyboard)
                await update_reminder_state(chat_id, today_str, status="reminded")
                logger.info(f"[LOGBOOK-SCHEDULER] Notifikasi logbook terkirim ke User {chat_id}.")
            except Exception as e:
                logger.error(f"[LOGBOOK-SCHEDULER] Gagal mengirim pesan pengingat ke {chat_id}: {e}")

    except Exception as e:
        logger.error(f"[LOGBOOK-SCHEDULER - ERROR] Error pada evaluasi pengingat logbook: {e}")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Mengonfigurasi dan menjalankan AsyncIOScheduler untuk tugas-tugas terjadwal."""
    settings = get_settings()
    tz = pytz.timezone(settings.TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)

    # 1. Job evaluasi reminder agenda setiap menit pada detik ke-0
    scheduler.add_job(
        process_due_reminders,
        trigger="cron",
        second=0,
        args=[bot],
        id="reminder_agenda_job",
        replace_existing=True,
    )

    # 2. Job evaluasi reminder logbook setiap menit pada detik ke-0
    scheduler.add_job(
        process_logbook_reminders,
        trigger="cron",
        second=0,
        args=[bot],
        id="reminder_logbook_job",
        replace_existing=True,
    )

    return scheduler


def start_scheduler_and_tasks(bot: Bot) -> AsyncIOScheduler:
    """Memulai scheduler APScheduler dan background task monitoring jaringan."""
    global _monitor_task
    settings = get_settings()

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("[SCHEDULER] APScheduler berhasil dimulai (Asia/Jakarta).")

    # Jalankan background network monitor sebagai asyncio task
    _monitor_task = asyncio.create_task(
        network_monitor_task(bot, settings.ADMIN_CHAT_ID),
        name="network_monitor_worker",
    )
    return scheduler


async def stop_scheduler_and_tasks(scheduler: AsyncIOScheduler) -> None:
    """Menghentikan scheduler dan membatalkan background tasks secara aman (Graceful Shutdown)."""
    global _monitor_task
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[SCHEDULER] APScheduler berhasil dimatikan.")

    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        try:
            await _monitor_task
        except asyncio.CancelledError:
            pass
        logger.info("[SCHEDULER] Network monitor task berhasil dihentikan.")

