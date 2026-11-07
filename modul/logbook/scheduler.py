import time
import random
import pytz
from datetime import datetime, timedelta
from telebot import types

from .database import (
    get_active_reminder_users, get_or_create_reminder_state,
    update_reminder_state, complete_reminder_for_today,
    has_today_draft_or_submission
)
from .website import get_authenticated_session, check_monitoring_page
from .sync import get_user_lock

LOCAL_TZ = pytz.timezone('Asia/Jakarta')

def process_user_reminder(bot, user, now, today_str):
    """
    Memeriksa dan mengevaluasi pengingat logbook untuk seorang pengguna.
    Mengembalikan True jika pengingat dikirim, False jika dilewati/selesai/gagal.
    """
    chat_id = user['chat_id']
    reminder_time = user.get('reminder_time', '16:05')
    reminder_days_str = user.get('reminder_days', '0,1,2,3,4')

    # 0. Evaluasi apakah hari ini termasuk dalam jadwal hari pengingat pengguna
    if not reminder_days_str or not reminder_days_str.strip():
        return False  # Pengingat dinonaktifkan (semua hari dimatikan)

    active_days = [int(x.strip()) for x in reminder_days_str.split(',') if x.strip().isdigit()]
    if now.weekday() not in active_days:
        return False  # Hari ini bukan hari pengingat (misal libur akhir pekan)

    # 1. Cek apakah pengguna sudah memiliki draf / submission aktif hari ini
    if has_today_draft_or_submission(chat_id, today_str):
        complete_reminder_for_today(chat_id, today_str)
        return False

    # 2. Ambil state pengingat pengguna untuk hari ini
    state = get_or_create_reminder_state(chat_id, today_str)
    status = state.get('status', 'idle')

    # Jika pengguna sudah selesai atau meminta berhenti untuk hari ini, lewati
    if status in ('completed', 'stopped'):
        return False

    current_time_str = now.strftime("%H:%M")
    # 3. Evaluasi apakah saatnya memicu pengingat:
    # - Pengingat pertama: status idle dan waktu saat ini cocok dengan reminder_time
    # - Pengingat ulang: status reminded dan waktu saat ini telah melewati next_retry_at
    should_remind = False
    is_retry = False

    if status == 'idle' and current_time_str == reminder_time:
        should_remind = True
        is_retry = False
    elif status == 'reminded':
        next_retry_at = state.get('next_retry_at')
        if next_retry_at and current_time_str >= next_retry_at and current_time_str <= "23:59":
            should_remind = True
            is_retry = True

    if not should_remind:
        return False

    # 4. Penguncian mutex per-user untuk mencegah bentrok dengan CLI / submit lain
    user_lock = get_user_lock(chat_id)
    with user_lock:
        # Periksa ulang draf pasca mendapatkan lock
        if has_today_draft_or_submission(chat_id, today_str):
            complete_reminder_for_today(chat_id, today_str)
            return False

        # 5. Cek website DERMAGA langsung apakah logbook hari ini sudah diisi
        try:
            session = get_authenticated_session(chat_id=chat_id)
            mon_info = check_monitoring_page(session, today_str)
        except Exception as scrape_err:
            print(f"[LOGBOOK-SCHEDULER - WARN] Gagal cek monitoring DERMAGA untuk User {chat_id}: {scrape_err}")
            return False

        if mon_info['exists']:
            print(f"[LOGBOOK-SCHEDULER] User {chat_id} ({user['username']}) terdeteksi sudah mengisi logbook di web untuk {today_str}.")
            complete_reminder_for_today(chat_id, today_str)
            return False

        # 6. Jika belum diisi, kirimkan notifikasi pengingat ke Telegram
        retry_count = state.get('retry_count', 0)
        markup = types.InlineKeyboardMarkup(row_width=1)
        btn_fill = types.InlineKeyboardButton("✍️ Isi Logbook", callback_data=f"log_remind_fill_{today_str}")
        markup.add(btn_fill)

        if is_retry or retry_count > 0:
            btn_stop = types.InlineKeyboardButton("🔕 Berhenti Ingatkan Hari Ini", callback_data=f"log_remind_stop_{today_str}")
            markup.add(btn_stop)

        retry_header = f" (Pengingat ke-{retry_count + 1})" if (is_retry or retry_count > 0) else ""
        text = (
            f"🔔 <b>Pengingat Logbook DERMAGA{retry_header}</b>\n\n"
            f"Halo <b>{user['username']}</b>, Anda terdeteksi <b>belum mengisi logbook</b> untuk hari ini:\n"
            f"🗓 Tanggal: <code>{today_str}</code>\n\n"
            f"Silakan klik tombol <b>✍️ Isi Logbook</b> di bawah untuk langsung mengisinya melalui bot."
        )
        if is_retry or retry_count > 0:
            text += "\n\n<i>Atau pilih '🔕 Berhenti Ingatkan Hari Ini' jika Anda tidak ingin diingatkan lagi sampai besok.</i>"

        msg_id = None
        try:
            sent_msg = bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
            msg_id = sent_msg.message_id
        except Exception as send_err:
            print(f"[LOGBOOK-SCHEDULER - ERROR] Gagal mengirim pesan pengingat ke {chat_id}: {send_err}")

        # 7. Pilih delay acak antara 55 sampai 60 menit untuk pengingat berikutnya
        delay_mins = random.randint(55, 60)
        next_retry_dt = now + timedelta(minutes=delay_mins)

        if next_retry_dt.date() == now.date() and next_retry_dt.strftime("%H:%M") <= "23:59":
            next_retry_str = next_retry_dt.strftime("%H:%M")
            print(f"[LOGBOOK-SCHEDULER] Pengingat User {chat_id} terkirim. Retry berikutnya diacak ke {next_retry_str} (jeda {delay_mins} mnt).")
        else:
            next_retry_str = None
            print(f"[LOGBOOK-SCHEDULER] Pengingat User {chat_id} terkirim. Batas hari tercapai, tidak ada retry lagi malam ini.")

        update_reminder_state(
            chat_id=chat_id,
            target_date=today_str,
            status='reminded',
            next_retry_at=next_retry_str,
            message_id=msg_id,
            increment_retry=True
        )
        return True

def jalankan_logbook_scheduler(bot):
    """
    Background scheduler daemon yang berjalan setiap menit untuk memeriksa
    dan mengingatkan pengisian logbook DERMAGA pengguna sesuai jam yang ditentukan.
    """
    print("[LOGBOOK-SCHEDULER] Scheduler pengingat logbook aktif (Zona Waktu: Asia/Jakarta).")
    while True:
        try:
            now = datetime.now(LOCAL_TZ)
            today_str = now.strftime("%Y-%m-%d")

            active_users = get_active_reminder_users()
            for user in active_users:
                process_user_reminder(bot, user, now, today_str)

        except Exception as e:
            print(f"[LOGBOOK-SCHEDULER - ERROR] Kesalahan pada putaran scheduler: {e}")

        # Tidur hingga detik ke-0 pada menit berikutnya
        now_after = datetime.now(LOCAL_TZ)
        sleep_secs = max(1.0, 60.0 - now_after.second - (now_after.microsecond / 1_000_000.0))
        time.sleep(sleep_secs)

