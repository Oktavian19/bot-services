"""
Service bisnis untuk modul Reminder Agenda.
Menangani formatting pesan, kalkulasi hari persiapan (H-x), dan evaluasi notifikasi due.
"""

from datetime import datetime
import pytz
from aiogram import Bot
from app.core.config import get_settings
from app.core.logger import logger
from app.database.reminder_repo import (
    get_due_reminders,
    mark_reminder_completed,
)


def get_local_now() -> datetime:
    """Mengembalikan waktu sekarang berdasarkan zona waktu yang dikonfigurasi (Asia/Jakarta)."""
    settings = get_settings()
    tz = pytz.timezone(settings.TIMEZONE)
    return datetime.now(tz)


def format_reminders_list_text(reminders: list[dict]) -> str:
    """Memformat daftar pengingat aktif menjadi teks HTML untuk hub reminder."""
    text = "📅 <b>Daftar Pengingat Aktif Anda:</b>\n\n"
    if not reminders:
        text += "<i>Anda belum memiliki pengingat yang aktif saat ini.</i>"
    else:
        for idx, r in enumerate(reminders, 1):
            r_msg = r["message"]
            r_date = r["target_date"]
            r_time = r["notify_time"]
            r_prep = r["prep_days"]
            try:
                tampilan_tanggal = datetime.strptime(r_date, "%Y-%m-%d").strftime("%d-%m-%Y")
            except Exception:
                tampilan_tanggal = r_date
            text += f"{idx}. <b>{r_msg}</b>\n   🗓 Hari-H: <code>{tampilan_tanggal}</code> ({r_time} WIB) | ⏳ H-{r_prep}\n\n"
    return text


async def process_due_reminders(bot: Bot) -> None:
    """
    Mengevaluasi pengingat yang jatuh tempo pada menit saat ini dan mengirimkan pesan notifikasi.
    Dipanggil secara berkala oleh scheduler setiap pergantian menit.
    """
    now = get_local_now()
    current_time_str = now.strftime("%H:%M")
    current_date = now.date()

    try:
        due_reminders = await get_due_reminders(current_time_str)
        for r in due_reminders:
            r_id = r["id"]
            chat_id = r["chat_id"]
            message = r["message"]
            target_date_str = r["target_date"]
            prep_days = r["prep_days"]

            try:
                target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            days_left = (target_date - current_date).days

            if 0 <= days_left <= prep_days:
                if days_left == 0:
                    header = "🚨 <b>REMINDER HARI INI!</b> 🚨"
                    await mark_reminder_completed(r_id)
                elif days_left == 1:
                    header = "🔔 <b>REMINDER (BESOK!)</b> 🔔"
                else:
                    header = f"🔔 <b>REMINDER (H-{days_left})</b> 🔔"

                full_message = f"{header}\n\n{message}"

                try:
                    await bot.send_message(chat_id=chat_id, text=full_message, parse_mode="HTML")
                    logger.info(f"[REMINDER-SCHEDULER] Notifikasi terkirim (H-{days_left}) ID {r_id} ke User {chat_id}.")
                except Exception as e:
                    logger.error(f"[REMINDER-SCHEDULER] Gagal kirim reminder {r_id} ke {chat_id}: {e}")

    except Exception as e:
        logger.error(f"[REMINDER-SCHEDULER - ERROR] Gagal memproses due reminders: {e}")

