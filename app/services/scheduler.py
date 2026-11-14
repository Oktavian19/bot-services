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
    get_weekly_reminder_state,
    has_today_draft_or_submission,
    set_weekly_reminder_status,
    update_reminder_state,
)
from app.services.logbook_service import fetch_dermaga_table, fetch_weekly_logbook_cards
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

            if status == "idle" and current_time_str >= reminder_time:
                should_remind = True
                is_retry = False
            elif status == "reminded":
                next_retry_at = state.get("next_retry_at")
                if next_retry_at and next_retry_at <= current_time_str <= "23:59":
                    should_remind = True
                    is_retry = True

            if not should_remind:
                continue

            # Cek ke portal DERMAGA apakah sudah submit manual di web
            try:
                entries = await fetch_dermaga_table(chat_id)
                today_entry = next(
                    (
                        e
                        for e in entries
                        if e.get("tanggal_iso") == today_str or today_str in e.get("tanggal_text", "")
                    ),
                    None,
                )
                if today_entry:
                    logger.info(f"[LOGBOOK-SCHEDULER] User {chat_id} sudah mengisi logbook di web untuk {today_str}.")
                    await complete_reminder_for_today(chat_id, today_str)
                    continue
            except Exception as e:
                logger.warning(f"[LOGBOOK-SCHEDULER] Lewati cek web DERMAGA user {chat_id}: {e}")

            # Kirim notifikasi pengingat
            retry_count = state.get("retry_count", 0)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✍️ Isi Logbook", callback_data=f"log_remind_fill_{today_str}")],
                [InlineKeyboardButton(text="🔕 Berhenti Ingatkan Hari Ini", callback_data=f"log_remind_stop_{today_str}")],
            ])

            retry_header = f" (Pengingat ke-{retry_count + 1})" if (is_retry or retry_count > 0) else ""
            text = (
                f"🔔 <b>Pengingat Logbook DERMAGA{retry_header}</b>\n\n"
                f"Halo <b>{user['username']}</b>, Anda terdeteksi <b>belum mengisi logbook</b> untuk hari ini:\n"
                f"🗓 Tanggal: <code>{today_str}</code>\n\n"
                f"Silakan klik tombol <b>✍️ Isi Logbook</b> di bawah untuk langsung mengisinya melalui bot."
            )
            if is_retry or retry_count > 0:
                text += "\n\n<i>Atau pilih '🔕 Berhenti Ingatkan Hari Ini' jika Anda tidak ingin diingatkan lagi sampai besok.</i>"

            try:
                sent_msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=keyboard)

                delay_mins = random.randint(55, 60)
                next_retry_dt = now + timedelta(minutes=delay_mins)
                if next_retry_dt.date() == now.date() and next_retry_dt.strftime("%H:%M") <= "23:59":
                    next_retry_str = next_retry_dt.strftime("%H:%M")
                    logger.info(
                        f"[LOGBOOK-SCHEDULER] Pengingat User {chat_id} terkirim (ke-{retry_count + 1}). "
                        f"Retry berikutnya dijadwalkan pukul {next_retry_str} (jeda {delay_mins} mnt)."
                    )
                else:
                    next_retry_str = None
                    logger.info(
                        f"[LOGBOOK-SCHEDULER] Pengingat User {chat_id} terkirim (ke-{retry_count + 1}). "
                        f"Batas hari tercapai, tidak ada retry lagi malam ini."
                    )

                await update_reminder_state(
                    chat_id,
                    today_str,
                    status="reminded",
                    count_increment=1,
                    next_retry_at=next_retry_str,
                    last_message_id=sent_msg.message_id,
                )
            except Exception as e:
                logger.error(f"[LOGBOOK-SCHEDULER] Gagal mengirim pesan pengingat ke {chat_id}: {e}")

    except Exception as e:
        logger.error(f"[LOGBOOK-SCHEDULER - ERROR] Error pada evaluasi pengingat logbook: {e}")


async def process_weekly_signature_reminders(bot: Bot) -> None:
    """Mengevaluasi dan mengingatkan tanda tangan/pengajuan logbook mingguan pada slider DERMAGA."""
    now = get_local_now()
    today = now.date()
    today_str = now.strftime("%Y-%m-%d")

    try:
        active_users = await get_active_reminder_users()
        for user in active_users:
            chat_id = user["chat_id"]
            try:
                cards = await fetch_weekly_logbook_cards(chat_id)
            except Exception as e:
                logger.warning(f"[LOGBOOK-WEEKLY] Gagal mengambil kartu mingguan untuk User {chat_id}: {e}")
                continue

            unsubmitted_cards = []
            for card in cards:
                data_awal = card.get("data_awal")
                status_raw = card.get("status", "").lower()
                if not data_awal:
                    continue

                try:
                    start_date = datetime.strptime(data_awal, "%Y-%m-%d").date()
                    sunday_date = start_date + timedelta(days=6)
                except Exception:
                    continue

                # Pengingat dimulai dari hari Minggu di minggu tersebut
                if today < sunday_date:
                    continue

                state = await get_weekly_reminder_state(chat_id, data_awal)
                current_status = state.get("status") if state else "idle"

                # Jika di DERMAGA sudah diajukan / diverifikasi, tandai selesai
                if "menunggu verifikasi" in status_raw or "verif" in status_raw:
                    if current_status != "completed":
                        await set_weekly_reminder_status(chat_id, data_awal, status="completed", week_label=card["label"])
                    continue

                # Jika masih 'Belum diajukan'
                if "belum diajukan" in status_raw:
                    if current_status == "stopped":
                        continue

                    # Hindari pengiriman ganda di hari yang sama
                    if state and state.get("last_reminded_date") == today_str:
                        continue

                    unsubmitted_cards.append(card)

            if unsubmitted_cards:
                lines = []
                stop_buttons = []
                for c in unsubmitted_cards:
                    lines.append(f"• <b>{c['label']}</b> (<code>{c['rentang_tanggal']}</code>) — <i>{c['hari_terisi']} hari terisi</i>")
                    stop_buttons.append([
                        InlineKeyboardButton(
                            text=f"🔕 Berhenti Ingatkan {c['label']}",
                            callback_data=f"log_stop_week_{c['data_awal']}",
                        )
                    ])

                text = (
                    "⚠️ <b>Pengingat Tanda Tangan Logbook Mingguan</b>\n\n"
                    f"Halo <b>{user['username']}</b>, terdeteksi terdapat logbook mingguan yang <b>belum diajukan / ditandatangani</b>:\n\n"
                    + "\n".join(lines) + "\n\n"
                    "Mohon segera buka portal DERMAGA untuk menandatangani dan mengajukan logbook tersebut ke Dosen & Supervisor:\n"
                    "🔗 <a href='https://jti.polinema.ac.id/dermaga/mahasiswa/monitoring'>Buka Monitoring DERMAGA</a>"
                )

                keyboard_rows = [
                    [InlineKeyboardButton(text="🌐 Buka Monitoring DERMAGA", url="https://jti.polinema.ac.id/dermaga/mahasiswa/monitoring")]
                ]
                keyboard_rows.extend(stop_buttons)
                keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

                try:
                    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=keyboard)
                    for c in unsubmitted_cards:
                        await set_weekly_reminder_status(
                            chat_id,
                            c["data_awal"],
                            status="reminded",
                            week_label=c["label"],
                            last_reminded_date=today_str,
                        )
                    logger.info(f"[LOGBOOK-WEEKLY] Notifikasi tanda tangan mingguan terkirim ke User {chat_id} ({len(unsubmitted_cards)} minggu).")
                except Exception as err:
                    logger.error(f"[LOGBOOK-WEEKLY] Gagal mengirim pesan ke {chat_id}: {err}")

    except Exception as e:
        logger.error(f"[LOGBOOK-WEEKLY - ERROR] Error pada evaluasi pengingat mingguan: {e}")


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

    # 3. Job evaluasi reminder tanda tangan mingguan setiap hari pukul 08:00 WIB
    scheduler.add_job(
        process_weekly_signature_reminders,
        trigger="cron",
        hour=8,
        minute=0,
        second=0,
        args=[bot],
        id="weekly_signature_job",
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

