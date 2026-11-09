import os
import re
import json
import html
import time
import requests
from telebot import types
from datetime import datetime
from .database import (
    setup_database, get_draft, update_draft_status, update_draft_summary,
    update_telegram_message_info, get_recent_drafts, register_user_credential,
    get_user_by_chat_id, get_user_credential, regenerate_api_token,
    delete_user_credential, get_all_users, update_user_reminder_time,
    get_user_reminder_time, update_user_reminder_days, get_user_reminder_days,
    update_user_location, get_user_location,
    PROFILE_DEFINITIONS, get_user_location_profiles, get_active_location_profile,
    set_active_location_profile, save_location_profile, update_draft_location_profile,
    get_draft_submission_location,
    complete_reminder_for_today, stop_reminder_for_today,
    get_or_create_reminder_state, create_or_get_draft
)
from .website import submit_logbook_to_dermaga, fetch_dermaga_table, test_dermaga_login
from .server import run_http_server
from .scheduler import jalankan_logbook_scheduler

def get_admin_chat_id() -> str:
    raw = os.environ.get('ADMIN_CHAT_ID', '')
    return raw.strip("'\" ")

def get_logbook_public_url() -> str:
    raw = os.environ.get('LOGBOOK_PUBLIC_URL', 'http://127.0.0.1:8088/api/logbook')
    return raw.strip("'\" ")

def is_admin(chat_or_user_id) -> bool:
    admin_id = get_admin_chat_id()
    if not admin_id:
        return True
    return str(chat_or_user_id).strip() == admin_id

def check_message_admin(message) -> bool:
    """Periksa apakah chat.id atau from_user.id merupakan admin."""
    if is_admin(message.chat.id):
        return True
    if getattr(message, 'from_user', None) and is_admin(message.from_user.id):
        return True
    return False

def format_draft_message(draft: dict) -> str:
    """Format tampilan pesan konfirmasi logbook ke Telegram HTML."""
    date = draft.get('date', '-')
    jam_masuk = draft.get('jam_masuk', '07:10')
    jam_pulang = draft.get('jam_pulang', '16:25')
    
    # Parse projects
    projects_raw = draft.get('projects', '[]')
    try:
        projects = json.loads(projects_raw) if isinstance(projects_raw, str) else projects_raw
        projects_str = ", ".join(projects) if isinstance(projects, list) else str(projects)
    except Exception:
        projects_str = str(projects_raw)

    summary = html.escape(draft.get('commits_summary', '-'))

    # Parse raw metadata commits
    commits_raw = draft.get('raw_metadata', '[]')
    commits_list = []
    try:
        commits = json.loads(commits_raw) if isinstance(commits_raw, str) else commits_raw
        if isinstance(commits, list):
            for c in commits:
                h = html.escape(str(c.get('hash', '')))
                subj = html.escape(str(c.get('subject', '')))
                proj = html.escape(str(c.get('project', '')))
                commits_list.append(f"• <code>[{proj}]</code> <code>{h}</code> {subj}")
    except Exception:
        pass

    commits_text = "\n".join(commits_list) if commits_list else "<i>Tidak ada metadata commit detail.</i>"

    # Lokasi submit draft (custom CLI atau profil office/home/other)
    loc = get_draft_submission_location(draft)
    prof_name = loc.get('profile_name', '🏢 Kantor (WFO)')
    lat_str = loc.get('lat', '-')
    lng_str = loc.get('lng', '-')
    maps_link = f"<a href=\"https://www.google.com/maps?q={lat_str},{lng_str}\"><code>{lat_str}, {lng_str}</code></a>"

    text = (
        f"📖 <b>Draf Logbook Harian</b>\n\n"
        f"🗓 <b>Tanggal:</b> <code>{date}</code>\n"
        f"⏰ <b>Jam Kerja:</b> <code>{jam_masuk} - {jam_pulang}</code>\n"
        f"📍 <b>Lokasi Submit:</b> <b>{prof_name}</b> ({maps_link})\n"
        f"📦 <b>Proyek:</b> <b>{projects_str}</b>\n\n"
        f"📝 <b>Ringkasan Aktivitas:</b>\n"
        f"{summary}\n\n"
        f"🔨 <b>Daftar Commit Hari Ini:</b>\n"
        f"{commits_text}\n\n"
        f"Silakan konfirmasi untuk melakukan pengisian ke portal DERMAGA:"
    )
    return text

def build_draft_keyboard(draft_id: int, current_profile: str = 'office'):
    markup = types.InlineKeyboardMarkup()
    btn_confirm = types.InlineKeyboardButton("✅ Konfirmasi", callback_data=f"log_confirm_{draft_id}")
    btn_edit = types.InlineKeyboardButton("✏️ Ubah", callback_data=f"log_edit_{draft_id}")
    btn_cancel = types.InlineKeyboardButton("❌ Batal", callback_data=f"log_cancel_{draft_id}")
    markup.row(btn_confirm, btn_edit, btn_cancel)

    # Baris tombol switch lokasi draf
    switch_btns = []
    if current_profile != 'office':
        switch_btns.append(types.InlineKeyboardButton("🏢 Switch: Kantor", callback_data=f"log_draft_loc_{draft_id}_office"))
    if current_profile != 'home':
        switch_btns.append(types.InlineKeyboardButton("🏠 Switch: WFH", callback_data=f"log_draft_loc_{draft_id}_home"))
    if current_profile != 'other':
        switch_btns.append(types.InlineKeyboardButton("📍 Switch: Lain", callback_data=f"log_draft_loc_{draft_id}_other"))

    if switch_btns:
        markup.row(*switch_btns)

    return markup

def send_draft_confirmation(bot, draft_id: int):
    """Mengirim pesan konfirmasi draf baru ke Telegram Pengguna terkait."""
    draft = get_draft(draft_id)
    if not draft:
        return

    chat_id = draft.get('chat_id')
    if not chat_id:
        admin_id_str = get_admin_chat_id()
        chat_id = int(admin_id_str) if admin_id_str.isdigit() else admin_id_str

    if not chat_id:
        print(f"[LOGBOOK - WARN] Tidak ada target chat_id untuk draf #{draft_id}, notifikasi dilewati.")
        return

    loc = get_draft_submission_location(draft)
    prof_key = loc.get('profile_key') or 'office'
    text = format_draft_message(draft)
    markup = build_draft_keyboard(draft_id, prof_key)

    try:
        msg = bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
        update_telegram_message_info(draft_id, msg.chat.id, msg.message_id)
        print(f"[LOGBOOK] Pesan konfirmasi draf #{draft_id} terkirim ke User ({chat_id}).")
    except Exception as e:
        print(f"[LOGBOOK - ERROR] Gagal mengirim pesan konfirmasi draf #{draft_id} ke {chat_id}: {e}")

def handle_edit_input(message, bot, draft_id: int):
    """Handler langkah berikutnya untuk menerima teks revisi ringkasan."""
    draft = get_draft(draft_id)
    if not draft:
        bot.send_message(message.chat.id, "❌ Draf tidak ditemukan.")
        return

    if draft.get('chat_id') and message.chat.id != draft.get('chat_id') and not is_admin(message.chat.id):
        bot.send_message(message.chat.id, "⛔ Akses ditolak. Ini bukan draf Anda.")
        return

    new_text = message.text.strip()
    if not new_text or new_text.startswith('/'):
        bot.send_message(message.chat.id, "❌ Perubahan dibatalkan atau format tidak valid.")
        return

    update_draft_summary(draft_id, new_text)
    updated_draft = get_draft(draft_id)

    loc = get_draft_submission_location(updated_draft)
    prof_key = loc.get('profile_key') or 'office'
    text = format_draft_message(updated_draft)
    markup = build_draft_keyboard(draft_id, prof_key)

    bot.send_message(
        message.chat.id,
        "✅ <b>Ringkasan berhasil diperbarui!</b>\nBerikut draf yang siap disetujui ulang:\n\n" + text,
        parse_mode="HTML",
        reply_markup=markup
    )

def validate_time_format(time_str: str) -> bool:
    """Memvalidasi format 24-jam HH:MM (00:00 s/d 23:59)."""
    try:
        parts = time_str.strip().split(':')
        if len(parts) != 2:
            return False
        h, m = int(parts[0]), int(parts[1])
        return 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        return False

def handle_set_jam_input(message, bot):
    """Handler langkah berikutnya untuk menerima teks jam pengingat baru."""
    time_str = message.text.strip() if message.text else ""
    if not time_str or time_str.startswith('/'):
        bot.send_message(message.chat.id, "❌ Pengaturan jam pengingat dibatalkan.")
        return

    if not validate_time_format(time_str):
        bot.send_message(
            message.chat.id,
            "❌ Format jam tidak valid. Harap gunakan format 24 jam <code>HH:MM</code> (antara 00:00 s/d 23:59).\nContoh: <code>16:05</code>",
            parse_mode="HTML"
        )
        return

    h, m = time_str.split(':')
    norm_time = f"{int(h):02d}:{int(m):02d}"
    update_user_reminder_time(message.chat.id, norm_time)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📖 Kembali ke Menu Logbook", callback_data="log_menu_back"))
    bot.send_message(
        message.chat.id,
        f"✅ <b>Jam Pengingat Berhasil Disimpan!</b>\n\n"
        f"Mulai hari ini, Anda akan diingatkan terkait logbook pada pukul <b>{norm_time} WIB</b>.",
        parse_mode="HTML",
        reply_markup=markup
    )

def parse_coordinates_input(text: str):
    """
    Mencoba mengekstrak lat, lng, dan akurasi (opsional) dari teks atau URL Google Maps.
    Mengembalikan (lat: float, lng: float, akurasi: float) atau None jika tidak valid.
    """
    text = (text or "").strip()
    if not text:
        return None

    # 1. Cek apakah ini shortlink Google Maps (maps.app.goo.gl atau goo.gl/maps)
    if 'maps.app.goo.gl' in text or 'goo.gl/maps' in text:
        try:
            match_url = re.search(r'https?://[^\s]+', text)
            if match_url:
                resp = requests.get(match_url.group(0), allow_redirects=True, timeout=5)
                text = resp.url
        except Exception as e:
            print(f"[LOGBOOK-LOCATION] Gagal resolve shortlink maps: {e}")

    # 2. Cek apakah URL Google Maps mengandung koordinat:
    # Contoh: /@lat,lng atau ?q=lat,lng atau /place/lat,lng atau /search/lat,lng
    url_match = re.search(r'[@\?&]q?=?(-?\d+\.\d+),(-?\d+\.\d+)', text)
    if url_match:
        try:
            lat = float(url_match.group(1))
            lng = float(url_match.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                return lat, lng, 15.0
        except ValueError:
            pass

    # 3. Format teks langsung: "-7.9467, 112.6156" atau "-7.9467 112.6156" atau "-7.9467, 112.6156, 15"
    clean = text.replace('(', '').replace(')', '').replace(';', ',').replace(',', ' ')
    parts = [p.strip() for p in clean.split() if p.strip()]
    if len(parts) >= 2:
        try:
            lat = float(parts[0])
            lng = float(parts[1])
            akurasi = float(parts[2]) if len(parts) >= 3 else 15.0
            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                akurasi = max(1.0, min(100.0, akurasi))
                return lat, lng, akurasi
        except ValueError:
            return None

    return None

def handle_set_lokasi_input(message, bot):
    """Handler penerima lokasi GPS baru (via Telegram Location pin atau teks/URL koordinat)."""
    # 1. Jika dikirim melalui pin lokasi Telegram (Native Location)
    if getattr(message, 'location', None) is not None:
        lat = message.location.latitude
        lng = message.location.longitude
        akurasi = getattr(message.location, 'horizontal_accuracy', None) or 15.0
        lat_str = f"{lat:.6f}"
        lng_str = f"{lng:.6f}"
        akurasi_str = f"{int(round(akurasi))}"

        update_user_location(message.chat.id, lat_str, lng_str, akurasi_str)
        maps_url = f"https://www.google.com/maps?q={lat_str},{lng_str}"

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📖 Kembali ke Menu Logbook", callback_data="log_menu_back"))

        bot.send_message(
            message.chat.id,
            f"✅ <b>Lokasi GPS Berhasil Diperbarui!</b>\n\n"
            f"📍 Koordinat: <a href=\"{maps_url}\"><code>{lat_str}, {lng_str}</code></a>\n"
            f"🎯 Estimasi Akurasi: <b>±{akurasi_str} meter</b>\n\n"
            f"<i>Koordinat ini akan otomatis digunakan saat submit absensi/logbook DERMAGA Anda.</i>",
            parse_mode="HTML",
            reply_markup=markup
        )
        return

    # 2. Jika dikirim dalam bentuk teks
    text = (message.text or "").strip()
    if not text or text.startswith('/'):
        bot.send_message(message.chat.id, "❌ Pengaturan lokasi logbook dibatalkan.")
        return

    parsed = parse_coordinates_input(text)
    if not parsed:
        bot.send_message(
            message.chat.id,
            "❌ <b>Format Koordinat Tidak Valid!</b>\n\n"
            "Pastikan Anda mengirim:\n"
            "• Pin lokasi langsung dari Telegram (ikon 📎 ➔ Location)\n"
            "• Atau angka koordinat: <code>-7.9467, 112.6156</code>\n"
            "• Atau link Google Maps tempat magang Anda.",
            parse_mode="HTML"
        )
        return

    lat, lng, akurasi = parsed
    lat_str = f"{lat:.6f}"
    lng_str = f"{lng:.6f}"
    akurasi_str = f"{int(round(akurasi))}"

    update_user_location(message.chat.id, lat_str, lng_str, akurasi_str)
    maps_url = f"https://www.google.com/maps?q={lat_str},{lng_str}"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📖 Kembali ke Menu Logbook", callback_data="log_menu_back"))

    bot.send_message(
        message.chat.id,
        f"✅ <b>Lokasi GPS Berhasil Diperbarui!</b>\n\n"
        f"📍 Koordinat: <a href=\"{maps_url}\"><code>{lat_str}, {lng_str}</code></a>\n"
        f"🎯 Estimasi Akurasi: <b>±{akurasi_str} meter</b>\n\n"
        f"<i>Koordinat ini akan otomatis digunakan saat submit absensi/logbook DERMAGA Anda.</i>",
        parse_mode="HTML",
        reply_markup=markup
    )

def handle_set_profile_lokasi_input(message, bot, profile_key: str):
    """Handler penerima lokasi GPS baru untuk profil tertentu (office, home, other)."""
    p_name = PROFILE_DEFINITIONS.get(profile_key, profile_key)

    # 1. Jika dikirim melalui pin lokasi Telegram (Native Location)
    if getattr(message, 'location', None) is not None:
        lat = message.location.latitude
        lng = message.location.longitude
        akurasi = getattr(message.location, 'horizontal_accuracy', None) or 15.0
        lat_str = f"{lat:.6f}"
        lng_str = f"{lng:.6f}"
        akurasi_str = f"{int(round(akurasi))}"

        save_location_profile(message.chat.id, profile_key, lat_str, lng_str, akurasi_str)
        maps_url = f"https://www.google.com/maps?q={lat_str},{lng_str}"

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📍 Buka Menu Lokasi GPS", callback_data="log_menu_set_lokasi"))
        markup.add(types.InlineKeyboardButton("📖 Kembali ke Menu Logbook", callback_data="log_menu_back"))

        bot.send_message(
            message.chat.id,
            f"✅ <b>Lokasi {p_name} Berhasil Disimpan!</b>\n\n"
            f"📍 Koordinat: <a href=\"{maps_url}\"><code>{lat_str}, {lng_str}</code></a>\n"
            f"🎯 Estimasi Akurasi: <b>±{akurasi_str} meter</b>",
            parse_mode="HTML",
            reply_markup=markup
        )
        return

    # 2. Jika dikirim dalam bentuk teks
    text = (message.text or "").strip()
    if not text or text.startswith('/'):
        bot.send_message(message.chat.id, f"❌ Pengaturan lokasi {p_name} dibatalkan.")
        return

    parsed = parse_coordinates_input(text)
    if not parsed:
        bot.send_message(
            message.chat.id,
            f"❌ <b>Format Koordinat Tidak Valid untuk {p_name}!</b>\n\n"
            "Pastikan Anda mengirim:\n"
            "• Pin lokasi langsung dari Telegram (ikon 📎 ➔ Location)\n"
            "• Atau angka koordinat: <code>-7.9467, 112.6156</code>\n"
            "• Atau link Google Maps.",
            parse_mode="HTML"
        )
        return

    lat, lng, akurasi = parsed
    lat_str = f"{lat:.6f}"
    lng_str = f"{lng:.6f}"
    akurasi_str = f"{int(round(akurasi))}"

    save_location_profile(message.chat.id, profile_key, lat_str, lng_str, akurasi_str)
    maps_url = f"https://www.google.com/maps?q={lat_str},{lng_str}"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📍 Buka Menu Lokasi GPS", callback_data="log_menu_set_lokasi"))
    markup.add(types.InlineKeyboardButton("📖 Kembali ke Menu Logbook", callback_data="log_menu_back"))

    bot.send_message(
        message.chat.id,
        f"✅ <b>Lokasi {p_name} Berhasil Disimpan!</b>\n\n"
        f"📍 Koordinat: <a href=\"{maps_url}\"><code>{lat_str}, {lng_str}</code></a>\n"
        f"🎯 Estimasi Akurasi: <b>±{akurasi_str} meter</b>",
        parse_mode="HTML",
        reply_markup=markup
    )

def render_locations_menu(chat_id: int) -> tuple:
    """Helper untuk merender menu multi-profil lokasi (office, home, other)."""
    profiles = get_user_location_profiles(chat_id)
    active_key = get_active_location_profile(chat_id)

    text = (
        "📍 <b>Pengaturan Profil Lokasi GPS (Hybrid Magang)</b>\n\n"
        "Pilih profil aktif untuk absensi atau atur koordinat masing-masing lokasi:\n\n"
    )

    for key, p in profiles.items():
        is_active = (key == active_key)
        active_badge = " <b>[AKTIF ✅]</b>" if is_active else ""
        if p['is_set']:
            maps_url = f"https://www.google.com/maps?q={p['lat']},{p['lng']}"
            coord_str = f"<a href=\"{maps_url}\"><code>{p['lat']}, {p['lng']}</code></a> (±{p['akurasi']}m)"
        else:
            coord_str = "<i>Belum diatur</i>"

        text += f"• <b>{p['profile_name']}</b>{active_badge}\n  Koordinat: {coord_str}\n\n"

    text += "<i>Gunakan tombol di bawah untuk mengganti profil aktif atau mengubah koordinat:</i>"

    markup = types.InlineKeyboardMarkup()

    # Baris 1: Switch Profil Aktif
    switch_btns = []
    for key, p in profiles.items():
        is_active = (key == active_key)
        icon = "✅" if is_active else "🔘"
        short_label = "Kantor" if key == "office" else ("Rumah/Kos" if key == "home" else "Lainnya")
        switch_btns.append(types.InlineKeyboardButton(f"{icon} {short_label}", callback_data=f"log_loc_switch_{key}"))
    markup.row(*switch_btns)

    # Baris 2: Edit Koordinat Masing-Masing Profil
    edit_btns = [
        types.InlineKeyboardButton("✏️ Atur Kantor", callback_data="log_loc_edit_office"),
        types.InlineKeyboardButton("✏️ Atur Rumah", callback_data="log_loc_edit_home"),
        types.InlineKeyboardButton("✏️ Atur Lain", callback_data="log_loc_edit_other")
    ]
    markup.row(*edit_btns)

    markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
    return text, markup

def handle_manual_logbook_input(message, bot, target_date: str):
    """Handler penerima teks aktivitas saat user klik 'Isi Logbook'."""
    text = message.text.strip() if message.text else ""
    if not text or text.startswith('/'):
        bot.send_message(message.chat.id, "❌ Pengisian logbook dibatalkan atau format tidak valid.")
        return

    chat_id = message.chat.id
    ts = int(time.time())
    idempotency_key = f"manual_{chat_id}_{target_date}_{ts}"

    try:
        draft, is_new = create_or_get_draft(
            chat_id=chat_id,
            idempotency_key=idempotency_key,
            date=target_date,
            projects=["Logbook Harian"],
            commits_summary=text,
            raw_metadata=[],
            jam_masuk="07:10",
            jam_pulang="16:25"
        )

        # Selesaikan state pengingat hari ini
        complete_reminder_for_today(chat_id, target_date)

        draft_text = format_draft_message(draft)
        loc = get_draft_submission_location(draft)
        prof_key = loc.get('profile_key') or 'office'
        markup = build_draft_keyboard(draft['id'], prof_key)

        bot.send_message(
            chat_id,
            "✅ <b>Draf Logbook Berhasil Dibuat!</b>\n\n"
            "Silakan periksa dan lakukan konfirmasi untuk mengirim ke DERMAGA:\n\n" + draft_text,
            parse_mode="HTML",
            reply_markup=markup
        )
    except Exception as e:
        bot.send_message(chat_id, f"❌ Terjadi kesalahan saat membuat draf logbook: {e}")

def cancel_reminder_for_cli(bot, chat_id: int, target_date: str):
    """Membatalkan siklus pengingat hari ini dan menonaktifkan tombol pengingat lama saat draf CLI diterima."""
    try:
        complete_reminder_for_today(chat_id, target_date)
        state = get_or_create_reminder_state(chat_id, target_date)
        last_msg_id = state.get('last_message_id')
        if last_msg_id:
            try:
                bot.edit_message_reply_markup(chat_id, last_msg_id, reply_markup=None)
            except Exception:
                pass
    except Exception as e:
        print(f"[LOGBOOK-REMINDER] Gagal membatalkan pengingat untuk CLI: {e}")

# --- HELPER HARI PENGINGAT LOGBOOK ---

DAY_NAMES = {
    0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis",
    4: "Jumat", 5: "Sabtu", 6: "Minggu"
}

def parse_days_to_set(days_str: str) -> set:
    """Mengubah string koma (contoh: '0,1,2,3,4') menjadi set integer 0..6."""
    if not days_str:
        return set()
    return {int(x.strip()) for x in str(days_str).split(',') if x.strip().isdigit() and 0 <= int(x.strip()) <= 6}

def format_reminder_days_display(days_str: str) -> str:
    """Mengubah kode hari menjadi label representatif yang mudah dibaca."""
    active = parse_days_to_set(days_str)
    if not active:
        return "🔴 Nonaktif"
    if active == {0, 1, 2, 3, 4}:
        return "Senin - Jumat"
    if active == {0, 1, 2, 3, 4, 5}:
        return "Senin - Sabtu"
    if active == {0, 1, 2, 3, 4, 5, 6}:
        return "Setiap Hari"
    sorted_days = sorted(list(active))
    return ", ".join(DAY_NAMES[d] for d in sorted_days)

def build_days_checklist_keyboard(days_str: str):
    """Membuat keyboard inline checklist toggle hari interaktif beserta tombol preset."""
    active = parse_days_to_set(days_str)
    markup = types.InlineKeyboardMarkup()

    # Baris 1: Senin, Selasa, Rabu
    row1 = []
    for d in [0, 1, 2]:
        icon = "✅" if d in active else "⬜"
        row1.append(types.InlineKeyboardButton(f"{icon} {DAY_NAMES[d]}", callback_data=f"log_daytg_{d}"))
    markup.row(*row1)

    # Baris 2: Kamis, Jumat, Sabtu
    row2 = []
    for d in [3, 4, 5]:
        icon = "✅" if d in active else "⬜"
        row2.append(types.InlineKeyboardButton(f"{icon} {DAY_NAMES[d]}", callback_data=f"log_daytg_{d}"))
    markup.row(*row2)

    # Baris 3: Minggu
    icon_sun = "✅" if 6 in active else "⬜"
    markup.row(types.InlineKeyboardButton(f"{icon_sun} Minggu", callback_data="log_daytg_6"))

    # Baris 4: Preset Hari Kerja
    markup.row(
        types.InlineKeyboardButton("⚡ Senin - Jumat", callback_data="log_dayps_weekdays"),
        types.InlineKeyboardButton("⚡ Senin - Sabtu", callback_data="log_dayps_6days")
    )

    # Baris 5: Preset Setiap Hari & Matikan
    markup.row(
        types.InlineKeyboardButton("⚡ Setiap Hari", callback_data="log_dayps_all"),
        types.InlineKeyboardButton("❌ Matikan Semua", callback_data="log_dayps_none")
    )

    # Baris 6: Selesai / Kembali ke Menu
    markup.row(types.InlineKeyboardButton("💾 Selesai & Kembali", callback_data="log_menu_back"))
    return markup

# --- MANAJEMEN SESI EDIT LOGBOOK INTERAKTIF ---

_edit_sessions = {}

MONTH_NAMES = {
    '01': 'Januari', '02': 'Februari', '03': 'Maret', '04': 'April',
    '05': 'Mei', '06': 'Juni', '07': 'Juli', '08': 'Agustus',
    '09': 'September', '10': 'Oktober', '11': 'November', '12': 'Desember'
}

MONTH_SHORT = {
    '01': 'Jan', '02': 'Feb', '03': 'Mar', '04': 'Apr',
    '05': 'Mei', '06': 'Jun', '07': 'Jul', '08': 'Agu',
    '09': 'Sep', '10': 'Okt', '11': 'Nov', '12': 'Des'
}

def format_month_name(ym: str) -> str:
    """Mengubah format YYYY-MM menjadi nama bulan (contoh: 2026-11 -> November 2026)."""
    try:
        parts = ym.split('-')
        if len(parts) == 2:
            return f"{MONTH_NAMES.get(parts[1], parts[1])} {parts[0]}"
    except Exception:
        pass
    return ym

def format_short_date(tanggal_iso: str) -> str:
    """Mengubah format YYYY-MM-DD menjadi label pendek (contoh: 2026-11-04 -> 04 Nov)."""
    try:
        parts = tanggal_iso.split('-')
        if len(parts) == 3:
            return f"{parts[2]} {MONTH_SHORT.get(parts[1], parts[1])}"
    except Exception:
        pass
    return tanggal_iso

def group_entries_by_month(entries: list) -> dict:
    """Mengelompokkan entri logbook DERMAGA berdasarkan YYYY-MM."""
    grouped = {}
    for e in entries:
        tgl = e.get('tanggal_iso', '')
        ym = tgl[:7] if (len(tgl) >= 7 and '-' in tgl) else 'Lainnya'
        if ym not in grouped:
            grouped[ym] = []
        grouped[ym].append(e)

    # Urutkan tanggal di setiap bulan secara ascending
    for ym in grouped:
        grouped[ym].sort(key=lambda x: x.get('tanggal_iso', ''))

    return grouped

def build_month_calendar_keyboard(chat_id: int, current_month: str, months_list: list, month_entries: list):
    """Membuat keyboard inline grid 3 kolom untuk tanggal logbook dan navigasi bulan."""
    markup = types.InlineKeyboardMarkup()

    # 1. Grid tanggal (3 tombol per baris)
    row = []
    for entry in month_entries:
        web_id = entry.get('web_id')
        tgl_short = format_short_date(entry.get('tanggal_iso', ''))
        btn = types.InlineKeyboardButton(f"📅 {tgl_short}", callback_data=f"log_edpick_{web_id}")
        row.append(btn)
        if len(row) == 3:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)

    # 2. Baris Navigasi Bulan
    nav_row = []
    if current_month in months_list:
        curr_idx = months_list.index(current_month)
        # Bulan sebelumnya (older month pada list descending: curr_idx + 1)
        if curr_idx + 1 < len(months_list):
            prev_m = months_list[curr_idx + 1]
            nav_row.append(types.InlineKeyboardButton("⬅️ Bulan Sebelumnya", callback_data=f"log_edmonth_{prev_m}"))
        # Bulan berikutnya (newer month pada list descending: curr_idx - 1)
        if curr_idx - 1 >= 0:
            next_m = months_list[curr_idx - 1]
            nav_row.append(types.InlineKeyboardButton("Bulan Berikutnya ➡️", callback_data=f"log_edmonth_{next_m}"))
    if nav_row:
        markup.row(*nav_row)

    # 3. Tombol Kembali
    markup.row(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
    return markup

def send_month_view(bot, chat_id: int, current_month: str, old_message_id: int = None):
    """Menampilkan daftar tanggal logbook bulan terpilih dengan menghapus pesan lama."""
    session = _edit_sessions.get(chat_id)
    if not session or not session.get('by_month'):
        text, markup = render_logbook_menu(chat_id)
        if old_message_id:
            try:
                bot.delete_message(chat_id, old_message_id)
            except Exception:
                pass
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
        return

    month_name = format_month_name(current_month)
    month_entries = session['by_month'].get(current_month, [])
    markup = build_month_calendar_keyboard(chat_id, current_month, session['months'], month_entries)

    text = (
        f"📅 <b>Pilih Tanggal Logbook untuk Diedit</b>\n\n"
        f"Bulan: <b>{month_name}</b> ({len(month_entries)} entri tercatat)\n\n"
        f"Silakan pilih tanggal yang ingin Anda ubah di bawah:"
    )

    if old_message_id:
        try:
            bot.delete_message(chat_id, old_message_id)
        except Exception:
            pass

    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

def render_edit_detail_message(session: dict) -> tuple:
    """Format tampilan detail logbook terpilih beserta tombol aksi edit per bagian."""
    orig = session.get('original', {})

    tgl = session.get('tanggal', '-')
    web_id = session.get('web_id', '-')
    masuk = session.get('jam_masuk', '07:10')
    pulang = session.get('jam_pulang', '16:25')
    desk = html.escape(session.get('deskripsi', '-'))

    masuk_changed = (masuk != orig.get('jam_masuk'))
    pulang_changed = (pulang != orig.get('jam_pulang'))
    desk_changed = (session.get('deskripsi') != orig.get('deskripsi'))
    any_changed = masuk_changed or pulang_changed or desk_changed

    masuk_badge = " <i>(diubah)</i>" if masuk_changed else ""
    pulang_badge = " <i>(diubah)</i>" if pulang_changed else ""
    desk_badge = " <i>(diubah)</i>" if desk_changed else ""

    text = (
        f"📝 <b>Detail Logbook Terpilih</b>\n\n"
        f"🗓 <b>Tanggal:</b> <code>{tgl}</code> (ID: <code>#{web_id}</code>)\n"
        f"⏰ <b>Jam Masuk:</b> <code>{masuk}</code>{masuk_badge}\n"
        f"⏰ <b>Jam Pulang:</b> <code>{pulang}</code>{pulang_badge}\n"
        f"📋 <b>Pekerjaan / Aktivitas:</b>{desk_badge}\n"
        f"{desk}\n\n"
    )

    if any_changed:
        text += "💡 <i>Terdapat perubahan yang belum disimpan. Klik 'Simpan Perubahan' untuk mengonfirmasi ke DERMAGA.</i>"
    else:
        text += "Silakan pilih bagian yang ingin Anda ubah di bawah:"

    markup = types.InlineKeyboardMarkup()
    btn_masuk = types.InlineKeyboardButton("⏰ Ubah Jam Masuk", callback_data="log_edact_masuk")
    btn_pulang = types.InlineKeyboardButton("⏰ Ubah Jam Pulang", callback_data="log_edact_pulang")
    markup.row(btn_masuk, btn_pulang)

    btn_desk = types.InlineKeyboardButton("📝 Ubah Pekerjaan", callback_data="log_edact_desk")
    markup.row(btn_desk)

    btn_save = types.InlineKeyboardButton("💾 Simpan Perubahan" if any_changed else "💾 Simpan (Belum Ada Perubahan)", callback_data="log_edact_save")
    markup.row(btn_save)

    btn_back_dates = types.InlineKeyboardButton("⬅️ Pilih Tanggal Lain", callback_data="log_edact_backmonth")
    btn_cancel = types.InlineKeyboardButton("❌ Batal", callback_data="log_edact_cancel")
    markup.row(btn_back_dates, btn_cancel)

    return text, markup

def send_detail_view(bot, chat_id: int, old_message_id: int = None):
    """Menampilkan detail logbook yang sedang diedit dengan menghapus pesan lama."""
    session = _edit_sessions.get(chat_id)
    if not session or not session.get('web_id'):
        text, markup = render_logbook_menu(chat_id)
        if old_message_id:
            try:
                bot.delete_message(chat_id, old_message_id)
            except Exception:
                pass
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
        return

    text, markup = render_edit_detail_message(session)
    if old_message_id:
        try:
            bot.delete_message(chat_id, old_message_id)
        except Exception:
            pass

    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

def handle_input_edit_masuk(message, bot):
    """Step handler input teks jam masuk baru."""
    chat_id = message.chat.id
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception:
        pass

    session = _edit_sessions.get(chat_id)
    prompt_id = session.pop('prompt_msg_id', None) if session else None

    if not session:
        bot.send_message(chat_id, "❌ Sesi edit telah berakhir. Silakan buka menu /logbook.")
        return

    val = message.text.strip() if message.text else ""
    if not val or val.startswith('/'):
        bot.send_message(chat_id, "❌ Pengubahan jam masuk dibatalkan.")
        send_detail_view(bot, chat_id, old_message_id=prompt_id)
        return

    if not validate_time_format(val):
        bot.send_message(chat_id, "❌ Format jam tidak valid. Harap gunakan format 24 jam <code>HH:MM</code> (contoh: <code>07:15</code>).", parse_mode="HTML")
        send_detail_view(bot, chat_id, old_message_id=prompt_id)
        return

    h, m = val.split(':')
    norm_time = f"{int(h):02d}:{int(m):02d}"
    session['jam_masuk'] = norm_time
    send_detail_view(bot, chat_id, old_message_id=prompt_id)

def handle_input_edit_pulang(message, bot):
    """Step handler input teks jam pulang baru."""
    chat_id = message.chat.id
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception:
        pass

    session = _edit_sessions.get(chat_id)
    prompt_id = session.pop('prompt_msg_id', None) if session else None

    if not session:
        bot.send_message(chat_id, "❌ Sesi edit telah berakhir. Silakan buka menu /logbook.")
        return

    val = message.text.strip() if message.text else ""
    if not val or val.startswith('/'):
        bot.send_message(chat_id, "❌ Pengubahan jam pulang dibatalkan.")
        send_detail_view(bot, chat_id, old_message_id=prompt_id)
        return

    if not validate_time_format(val):
        bot.send_message(chat_id, "❌ Format jam tidak valid. Harap gunakan format 24 jam <code>HH:MM</code> (contoh: <code>16:25</code>).", parse_mode="HTML")
        send_detail_view(bot, chat_id, old_message_id=prompt_id)
        return

    h, m = val.split(':')
    norm_time = f"{int(h):02d}:{int(m):02d}"
    session['jam_pulang'] = norm_time
    send_detail_view(bot, chat_id, old_message_id=prompt_id)

def handle_input_edit_deskripsi(message, bot):
    """Step handler input teks deskripsi pekerjaan baru."""
    chat_id = message.chat.id
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception:
        pass

    session = _edit_sessions.get(chat_id)
    prompt_id = session.pop('prompt_msg_id', None) if session else None

    if not session:
        bot.send_message(chat_id, "❌ Sesi edit telah berakhir. Silakan buka menu /logbook.")
        return

    val = message.text.strip() if message.text else ""
    if not val or val.startswith('/'):
        bot.send_message(chat_id, "❌ Pengubahan deskripsi dibatalkan.")
        send_detail_view(bot, chat_id, old_message_id=prompt_id)
        return

    session['deskripsi'] = val
    send_detail_view(bot, chat_id, old_message_id=prompt_id)

def render_logbook_menu(chat_id: int, user_id: int = None) -> tuple:
    """Helper untuk merender tampilan menu utama /logbook beserta Inline Keyboard."""
    user_meta = get_user_by_chat_id(chat_id)
    admin = is_admin(chat_id) or (user_id and is_admin(user_id))

    markup = types.InlineKeyboardMarkup(row_width=2)

    if not user_meta and not admin:
        text = (
            "📖 <b>Pusat Kendali Logbook DERMAGA</b>\n\n"
            "⚠️ <b>Akun Anda belum terdaftar.</b>\n\n"
            "Untuk mulai menggunakan otomatisasi logbook harian, daftarkan akun DERMAGA Anda:\n"
            "👉 <code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code>\n\n"
            "<i>Catatan: Pesan yang berisi password akan langsung dihapus otomatis oleh bot demi keamanan.</i>"
        )
        markup.add(types.InlineKeyboardButton("🔄 Refresh Status", callback_data="log_menu_refresh"))
        return text, markup

    drafts = get_recent_drafts(chat_id=chat_id, limit=5) if user_meta else []
    username_str = user_meta['username'] if user_meta else "(Admin Mode)"
    token_str = (user_meta['api_token'][:8] + "..." + user_meta['api_token'][-6:]) if (user_meta and user_meta.get('api_token')) else "-"
    reminder_time_str = user_meta.get('reminder_time', '16:05') if user_meta else '16:05'
    reminder_days_str = user_meta.get('reminder_days', '0,1,2,3,4') if user_meta else '0,1,2,3,4'
    reminder_days_display = format_reminder_days_display(reminder_days_str)
    loc = get_user_location(chat_id) if user_meta else {'lat': '-7.5815', 'lng': '112.6247', 'akurasi': '15', 'profile_name': '🏢 Kantor (WFO)'}
    lat_str = loc['lat']
    lng_str = loc['lng']
    akurasi_str = loc['akurasi']
    prof_name = loc.get('profile_name', '🏢 Kantor (WFO)')
    maps_url = f"https://www.google.com/maps?q={lat_str},{lng_str}"

    text = (
        f"📖 <b>Pusat Kendali Logbook DERMAGA</b>\n"
        f"👤 Akun DERMAGA: <code>{username_str}</code>\n"
        f"📍 Lokasi Aktif: <b>{prof_name}</b> (<a href=\"{maps_url}\"><code>{lat_str}, {lng_str}</code></a>)\n"
        f"⏰ Jam Pengingat: <b>{reminder_time_str} WIB</b>\n"
        f"🗓 Hari Pengingat: <b>{reminder_days_display}</b>\n"
        f"🔑 Token CLI: <code>{token_str}</code>\n\n"
        f"<b>Riwayat Draf Anda Terakhir:</b>\n"
    )

    if not drafts:
        text += "<i>Belum ada draf logbook tercatat untuk akun Anda.</i>\n"
    else:
        status_emojis = {
            'pending': '⏳ Pending',
            'approved': '👍 Disetujui',
            'submitted': '✅ Berhasil Submit',
            'skipped': '⏩ Dilewati',
            'cancelled': '❌ Dibatalkan',
            'failed': '⚠️ Gagal Submit'
        }
        for d in drafts:
            st = status_emojis.get(d['status'], d['status'])
            text += f"• #{d['id']} | <code>{d['date']}</code> | {st}\n"

    if admin:
        total_users = len(get_all_users())
        text += f"\n👑 <b>Admin Panel:</b>\n• Total Pengguna Terdaftar: <b>{total_users}</b>\n"

    text += "\nSilakan pilih menu di bawah ini:"

    # Tombol interaktif utama
    btn_cek = types.InlineKeyboardButton("📋 Cek Logbook", callback_data="log_menu_cek")
    btn_edit = types.InlineKeyboardButton("✏️ Edit Logbook", callback_data="log_menu_edit")
    btn_token = types.InlineKeyboardButton("🔑 Token CLI", callback_data="log_menu_token")
    btn_refresh = types.InlineKeyboardButton("🔄 Refresh", callback_data="log_menu_refresh")
    btn_set_jam = types.InlineKeyboardButton("⏰ Jam Pengingat", callback_data="log_menu_set_jam")
    btn_set_hari = types.InlineKeyboardButton("🗓 Hari Pengingat", callback_data="log_menu_set_hari")
    btn_set_lokasi = types.InlineKeyboardButton("📍 Lokasi GPS", callback_data="log_menu_set_lokasi")
    btn_hapus = types.InlineKeyboardButton("🗑️ Hapus Akun", callback_data="log_menu_hapus")
    markup.add(btn_cek, btn_edit)
    markup.add(btn_token, btn_refresh)
    markup.add(btn_set_jam, btn_set_hari)
    markup.add(btn_set_lokasi, btn_hapus)

    if admin:
        btn_admin = types.InlineKeyboardButton("👥 Daftar Pengguna (Admin)", callback_data="log_menu_admin_users")
        markup.add(btn_admin)

    return text, markup

def init_logbook(bot):
    """Inisialisasi modul logbook, database, command Telegram, dan callback."""
    setup_database()
    print("[+] Module Logbook: Database & services ready (Multi-User enabled).")

    @bot.message_handler(commands=['logbook'])
    def cmd_logbook(message):
        from_id = getattr(message, 'from_user', None).id if getattr(message, 'from_user', None) else None
        text, markup = render_logbook_menu(message.chat.id, from_id)
        bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

    @bot.message_handler(commands=['daftar_logbook', 'login_logbook', 'set_dermaga_auth'])
    def cmd_daftar_logbook(message):
        # 1. Hapus pesan sensitif dari obrolan
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass

        parts = message.text.split()
        if len(parts) < 3:
            bot.send_message(
                message.chat.id,
                "❌ Format salah.\n"
                "Gunakan: <code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code>\n\n"
                "<i>Contoh:</i> <code>/daftar_logbook 2341720117 Rahasia123</code>",
                parse_mode="HTML"
            )
            return

        username = parts[1].strip()
        password = parts[2].strip()

        loading = bot.send_message(
            message.chat.id,
            f"⏳ <i>Sedang menguji autentikasi akun <code>{username}</code> ke portal DERMAGA...</i>",
            parse_mode="HTML"
        )

        ok, msg = test_dermaga_login(username, password)
        if not ok:
            bot.edit_message_text(
                f"❌ <b>Verifikasi DERMAGA Gagal!</b>\n\n{msg}\n\n"
                f"Silakan periksa kembali username/NIM dan password Anda.",
                message.chat.id,
                loading.message_id,
                parse_mode="HTML"
            )
            return

        try:
            token = register_user_credential(message.chat.id, username, password)
            success_text = (
                f"🎉 <b>Pendaftaran Logbook DERMAGA Berhasil!</b>\n\n"
                f"👤 Akun: <code>{username}</code>\n"
                f"🔑 <b>API Token CLI Anda:</b>\n"
                f"<code>{token}</code>\n\n"
                f"📦 <b>Download Logbook CLI:</b>\n"
                f"• <a href=\"https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-windows-x64.zip\">Windows (ZIP)</a> | <a href=\"https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-linux-x64.zip\">Linux (ZIP)</a>\n\n"
                f"📋 <b>Konfigurasi di Laptop / CLI Anda:</b>\n"
                f"Ekstrak ZIP, salin file <code>config.example.json</code> menjadi <code>config.json</code>, lalu sesuaikan field <code>api_token</code>:\n"
                f"<pre>"
                f'{{\n'
                f'  "vps_endpoint": "{get_logbook_public_url()}",\n'
                f'  "api_token": "{token}",\n'
                f'  "location": "office"\n'
                f'}}'
                f"</pre>\n"
                f"💡 <i>Field <code>location</code> bersifat opsional: gunakan <code>office</code> (WFO), <code>home</code> (WFH), atau <code>other</code>. Jika tidak disertakan, bot otomatis menggunakan profil aktif Anda.</i>"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📖 Buka Menu Logbook", callback_data="log_menu_back"))
            bot.edit_message_text(success_text, message.chat.id, loading.message_id, parse_mode="HTML", reply_markup=markup)
            print(f"[LOGBOOK] User {message.chat.id} ({username}) berhasil terdaftar/update.")
        except Exception as e:
            bot.edit_message_text(f"❌ Terjadi kesalahan saat menyimpan akun: {e}", message.chat.id, loading.message_id)

    @bot.message_handler(commands=['token_logbook'])
    def cmd_token_logbook(message):
        user = get_user_by_chat_id(message.chat.id)
        if not user:
            bot.send_message(
                message.chat.id,
                "⚠️ Akun Anda belum terdaftar.\n"
                "Gunakan <code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code> untuk mendaftar.",
                parse_mode="HTML"
            )
            return

        token = user['api_token']
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Buat Ulang Token", callback_data="log_regen_token"))
        markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))

        text = (
            f"🔑 <b>API Token CLI Logbook Anda</b>\n\n"
            f"👤 Akun: <code>{user['username']}</code>\n"
            f"Token:\n<code>{token}</code>\n\n"
            f"📦 <b>Download Logbook CLI:</b>\n"
            f"• <a href=\"https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-windows-x64.zip\">Windows (ZIP)</a> | <a href=\"https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-linux-x64.zip\">Linux (ZIP)</a>\n\n"
            f"📋 <b>Konfigurasi di Laptop:</b>\n"
            f"Ekstrak ZIP, salin file <code>config.example.json</code> menjadi <code>config.json</code>, lalu sesuaikan field <code>api_token</code>:\n"
            f"<pre>"
            f'{{\n'
            f'  "vps_endpoint": "{get_logbook_public_url()}",\n'
            f'  "api_token": "{token}",\n'
            f'  "location": "office"\n'
            f'}}'
            f"</pre>\n"
            f"💡 <i>Field <code>location</code> bersifat opsional: gunakan <code>office</code> (WFO), <code>home</code> (WFH), atau <code>other</code>. Jika tidak disertakan, bot otomatis menggunakan profil aktif Anda.</i>"
        )
        bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

    @bot.message_handler(commands=['cek_logbook'])
    def cmd_cek_logbook(message):
        user = get_user_by_chat_id(message.chat.id)
        if not user:
            bot.send_message(
                message.chat.id,
                "⚠️ Akun DERMAGA Anda belum terdaftar di bot ini.\n"
                "Silakan daftar terlebih dahulu menggunakan:\n"
                "<code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code>",
                parse_mode="HTML"
            )
            return

        loading = bot.send_message(message.chat.id, "⏳ <i>Sedang mengambil data tabel logbook dari DERMAGA...</i>", parse_mode="HTML")
        try:
            entries = fetch_dermaga_table(chat_id=message.chat.id)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))

            if not entries:
                bot.edit_message_text(
                    f"ℹ️ Belum ada entri logbook yang tercatat di tabel DERMAGA akun <code>{user['username']}</code>.",
                    message.chat.id,
                    loading.message_id,
                    parse_mode="HTML",
                    reply_markup=markup
                )
                return

            text = f"📋 <b>Daftar Logbook DERMAGA ({len(entries)} Entri) - {user['username']}:</b>\n\n"
            for e in entries[:10]:
                desc = html.escape(e['pekerjaan'])
                if len(desc) > 160:
                    desc = desc[:157] + "..."
                text += (
                    f"📅 <b>{e['tanggal_text']}</b> (ID: <code>#{e['web_id'] or '-'}</code>)\n"
                    f"⏱️ <code>{e['jam']}</code> | Ket: <b>{e['keterangan']}</b> | Status: <b>{e['status_verif']}</b>\n"
                    f"📝 <i>{desc}</i>\n\n"
                )

            if len(entries) > 10:
                text += f"<i>...dan {len(entries) - 10} entri lainnya di DERMAGA.</i>"

            bot.edit_message_text(text, message.chat.id, loading.message_id, parse_mode="HTML", reply_markup=markup)
        except Exception as err:
            bot.edit_message_text(f"❌ Gagal mengambil data DERMAGA: {err}", message.chat.id, loading.message_id)

    @bot.message_handler(commands=['set_jam_logbook', 'jam_logbook'])
    def cmd_set_jam_logbook(message):
        user = get_user_by_chat_id(message.chat.id)
        if not user:
            bot.send_message(
                message.chat.id,
                "⚠️ Akun Anda belum terdaftar.\n"
                "Gunakan <code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code> untuk mendaftar.",
                parse_mode="HTML"
            )
            return

        parts = message.text.split()
        if len(parts) < 2:
            current_time = user.get('reminder_time', '16:05')
            bot.send_message(
                message.chat.id,
                f"⏰ <b>Pengaturan Jam Pengingat Logbook</b>\n\n"
                f"Jam saat ini: <b>{current_time} WIB</b>\n\n"
                f"Format pengubahan:\n"
                f"<code>/set_jam_logbook HH:MM</code>\n"
                f"<i>Contoh:</i> <code>/set_jam_logbook 16:30</code>",
                parse_mode="HTML"
            )
            return

        time_str = parts[1].strip()
        if not validate_time_format(time_str):
            bot.send_message(
                message.chat.id,
                "❌ Format jam tidak valid. Harap gunakan format 24 jam <code>HH:MM</code> (antara 00:00 s/d 23:59).\nContoh: <code>16:30</code>",
                parse_mode="HTML"
            )
            return

        h, m = time_str.split(':')
        norm_time = f"{int(h):02d}:{int(m):02d}"
        update_user_reminder_time(message.chat.id, norm_time)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📖 Kembali ke Menu Logbook", callback_data="log_menu_back"))
        bot.send_message(
            message.chat.id,
            f"✅ <b>Jam Pengingat Berhasil Diubah!</b>\n\n"
            f"Setiap hari pada pukul <b>{norm_time} WIB</b>, bot akan memeriksa dan mengingatkan pengisian logbook Anda.",
            parse_mode="HTML",
            reply_markup=markup
        )

    @bot.message_handler(commands=['set_hari_logbook', 'hari_logbook'])
    def cmd_set_hari_logbook(message):
        user = get_user_by_chat_id(message.chat.id)
        if not user:
            bot.send_message(
                message.chat.id,
                "⚠️ Akun Anda belum terdaftar.\n"
                "Gunakan <code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code> untuk mendaftar.",
                parse_mode="HTML"
            )
            return

        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            current_days = user.get('reminder_days', '0,1,2,3,4')
            text = (
                f"🗓 <b>Pengaturan Hari Pengingat Logbook</b>\n\n"
                f"Jadwal aktif saat ini: <b>{format_reminder_days_display(current_days)}</b>\n\n"
                f"<b>Pilihan Preset:</b>\n"
                f"• <code>/set_hari_logbook senin-jumat</code> (Hari kerja standard)\n"
                f"• <code>/set_hari_logbook senin-sabtu</code> (6 hari kerja)\n"
                f"• <code>/set_hari_logbook setiap-hari</code> (Semua hari termasuk akhir pekan)\n"
                f"• <code>/set_hari_logbook nonaktif</code> (Matikan pengingat)\n\n"
                f"<i>Atau gunakan tombol checklist interaktif di bawah:</i>"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🗓 Buka Checklist Hari", callback_data="log_menu_set_hari"))
            markup.add(types.InlineKeyboardButton("📖 Kembali ke Menu Logbook", callback_data="log_menu_back"))
            bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)
            return

        arg = parts[1].strip().lower().replace("_", "-")
        DAY_ALIASES = {
            "senin": 0, "sen": 0, "mon": 0, "monday": 0,
            "selasa": 1, "sel": 1, "tue": 1, "tuesday": 1,
            "rabu": 2, "rab": 2, "wed": 2, "wednesday": 2,
            "kamis": 3, "kam": 3, "thu": 3, "thursday": 3,
            "jumat": 4, "jum": 4, "fri": 4, "friday": 4,
            "sabtu": 5, "sab": 5, "sat": 5, "saturday": 5,
            "minggu": 6, "min": 6, "sun": 6, "sunday": 6
        }

        if arg in ("senin-jumat", "weekday", "weekdays", "kerja"):
            new_days = "0,1,2,3,4"
        elif arg in ("senin-sabtu", "6hari", "6-hari"):
            new_days = "0,1,2,3,4,5"
        elif arg in ("setiap-hari", "semua", "all", "daily"):
            new_days = "0,1,2,3,4,5,6"
        elif arg in ("nonaktif", "off", "mati", "none", "kosong"):
            new_days = ""
        else:
            tokens = [t.strip() for t in arg.replace(" ", ",").split(",") if t.strip()]
            matched = set()
            for t in tokens:
                if t in DAY_ALIASES:
                    matched.add(DAY_ALIASES[t])
                elif t.isdigit() and 0 <= int(t) <= 6:
                    matched.add(int(t))
            if matched:
                new_days = ",".join(str(d) for d in sorted(list(matched)))
            else:
                bot.send_message(
                    message.chat.id,
                    "❌ Pilihan hari tidak dikenali.\n"
                    "Gunakan: <code>senin-jumat</code>, <code>senin-sabtu</code>, <code>setiap-hari</code>, <code>nonaktif</code>, "
                    "atau sebutkan nama hari dipisah koma (contoh: <code>senin,rabu,jumat</code>).",
                    parse_mode="HTML"
                )
                return

        update_user_reminder_days(message.chat.id, new_days)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📖 Kembali ke Menu Logbook", callback_data="log_menu_back"))
        bot.send_message(
            message.chat.id,
            f"✅ <b>Hari Pengingat Berhasil Diubah!</b>\n\n"
            f"Jadwal pengingat Anda sekarang: <b>{format_reminder_days_display(new_days)}</b>.",
            parse_mode="HTML",
            reply_markup=markup
        )

    @bot.message_handler(commands=['set_lokasi_logbook', 'lokasi_logbook', 'set_gps_logbook'])
    def cmd_set_lokasi_logbook(message):
        user = get_user_by_chat_id(message.chat.id)
        if not user:
            bot.send_message(
                message.chat.id,
                "⚠️ Akun Anda belum terdaftar.\n"
                "Gunakan <code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code> untuk mendaftar.",
                parse_mode="HTML"
            )
            return

        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            param = parts[1].strip()
            target_profile = get_active_location_profile(message.chat.id)
            tokens = param.split()
            if tokens and tokens[0].lower() in ('office', 'kantor', 'wfo'):
                target_profile = 'office'
                param = " ".join(tokens[1:])
            elif tokens and tokens[0].lower() in ('home', 'rumah', 'kos', 'wfh'):
                target_profile = 'home'
                param = " ".join(tokens[1:])
            elif tokens and tokens[0].lower() in ('other', 'lain', 'klien'):
                target_profile = 'other'
                param = " ".join(tokens[1:])

            parsed = parse_coordinates_input(param)
            if not parsed:
                bot.send_message(
                    message.chat.id,
                    "❌ Format koordinat tidak valid.\n"
                    "Gunakan: <code>/set_lokasi_logbook [kantor|rumah|lain] &lt;latitude&gt; &lt;longitude&gt; [akurasi]</code>\n"
                    "Contoh: <code>/set_lokasi_logbook -7.9467 112.6156</code> atau <code>/set_lokasi_logbook rumah -7.9467 112.6156</code>",
                    parse_mode="HTML"
                )
                return

            lat, lng, akurasi = parsed
            lat_str = f"{lat:.6f}"
            lng_str = f"{lng:.6f}"
            akurasi_str = f"{int(round(akurasi))}"
            save_location_profile(message.chat.id, target_profile, lat_str, lng_str, akurasi_str)
            p_name = PROFILE_DEFINITIONS.get(target_profile, target_profile)
            maps_url = f"https://www.google.com/maps?q={lat_str},{lng_str}"

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📍 Buka Menu Lokasi GPS", callback_data="log_menu_set_lokasi"))
            markup.add(types.InlineKeyboardButton("📖 Kembali ke Menu Logbook", callback_data="log_menu_back"))
            bot.send_message(
                message.chat.id,
                f"✅ <b>Lokasi {p_name} Berhasil Disimpan!</b>\n\n"
                f"📍 Koordinat: <a href=\"{maps_url}\"><code>{lat_str}, {lng_str}</code></a>\n"
                f"🎯 Estimasi Akurasi: <b>±{akurasi_str} meter</b>",
                parse_mode="HTML",
                reply_markup=markup
            )
            return

        text, markup = render_locations_menu(message.chat.id)
        bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

    @bot.message_handler(content_types=['location'])
    def handle_direct_location(message):
        user = get_user_by_chat_id(message.chat.id)
        if not user:
            return
        handle_set_lokasi_input(message, bot)

    @bot.message_handler(commands=['hapus_akun_logbook'])
    def cmd_hapus_akun(message):
        user = get_user_by_chat_id(message.chat.id)
        if not user:
            bot.send_message(message.chat.id, "ℹ️ Anda belum terdaftar di sistem logbook.")
            return

        delete_user_credential(message.chat.id)
        bot.send_message(
            message.chat.id,
            f"✅ Kredensial dan API Token untuk akun <code>{user['username']}</code> telah dihapus dari sistem bot.",
            parse_mode="HTML"
        )

    @bot.message_handler(commands=['admin_logbook'])
    def cmd_admin_logbook(message):
        if not check_message_admin(message):
            bot.send_message(message.chat.id, "⛔ Akses ditolak. Hanya untuk Admin.")
            return

        users = get_all_users()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))

        if not users:
            bot.send_message(message.chat.id, "ℹ️ Belum ada pengguna logbook yang terdaftar.", reply_markup=markup)
            return

        text = f"👥 <b>Daftar Pengguna Logbook Terdaftar ({len(users)} User):</b>\n\n"
        for u in users:
            status = "🟢 Aktif" if u['is_active'] else "🔴 Nonaktif"
            token_snippet = u['api_token'][:6] + "..." + u['api_token'][-4:]
            text += (
                f"• 👤 <b>{u['username']}</b>\n"
                f"  Chat ID: <code>{u['chat_id']}</code>\n"
                f"  Token: <code>{token_snippet}</code> | Status: {status}\n"
                f"  Terdaftar: <code>{u['created_at']}</code>\n\n"
            )
        bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('log_'))
    def callback_logbook(call):
        data = call.data

        # --- MENU CALLBACKS (IN-PLACE NAVIGATION) ---
        if data in ("log_menu_refresh", "log_menu_back"):
            bot.answer_callback_query(call.id)
            text, markup = render_logbook_menu(call.message.chat.id, call.from_user.id)
            try:
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            except Exception:
                pass
            return

        elif data == "log_menu_cek":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.message.chat.id)
            if not user:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                bot.edit_message_text("⚠️ Akun DERMAGA Anda belum terdaftar.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                return

            try:
                bot.edit_message_text("⏳ <i>Sedang mengambil data tabel logbook dari DERMAGA...</i>", call.message.chat.id, call.message.message_id, parse_mode="HTML")
            except Exception:
                pass

            try:
                entries = fetch_dermaga_table(chat_id=call.message.chat.id)
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))

                if not entries:
                    text = f"ℹ️ Belum ada entri logbook yang tercatat di tabel DERMAGA akun <code>{user['username']}</code>."
                else:
                    text = f"📋 <b>Daftar Logbook DERMAGA ({len(entries)} Entri) - {user['username']}:</b>\n\n"
                    for e in entries[:10]:
                        desc = html.escape(e['pekerjaan'])
                        if len(desc) > 160:
                            desc = desc[:157] + "..."
                        text += (
                            f"📅 <b>{e['tanggal_text']}</b> (ID: <code>#{e['web_id'] or '-'}</code>)\n"
                            f"⏱️ <code>{e['jam']}</code> | Ket: <b>{e['keterangan']}</b> | Status: <b>{e['status_verif']}</b>\n"
                            f"📝 <i>{desc}</i>\n\n"
                        )
                    if len(entries) > 10:
                        text += f"<i>...dan {len(entries) - 10} entri lainnya di DERMAGA.</i>"

                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            except Exception as err:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                bot.edit_message_text(f"❌ Gagal mengambil data DERMAGA: {err}", call.message.chat.id, call.message.message_id, reply_markup=markup)
            return

        elif data == "log_menu_token":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.message.chat.id)
            if not user:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                bot.edit_message_text("⚠️ Akun Anda belum terdaftar.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                return

            token_val = user.get('api_token', '')
            text = (
                f"🔑 <b>API Token CLI Logbook Anda</b>\n\n"
                f"👤 Akun: <code>{user['username']}</code>\n"
                f"Token:\n<code>{token_val}</code>\n\n"
                f"📦 <b>Download Logbook CLI:</b>\n"
                f"• <a href=\"https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-windows-x64.zip\">Windows (ZIP)</a> | <a href=\"https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-linux-x64.zip\">Linux (ZIP)</a>\n\n"
                f"📋 <b>Konfigurasi di Laptop:</b>\n"
                f"Ekstrak ZIP, salin file <code>config.example.json</code> menjadi <code>config.json</code>, lalu sesuaikan field <code>api_token</code>:\n"
                f"<pre>"
                f'{{\n'
                f'  "vps_endpoint": "{get_logbook_public_url()}",\n'
                f'  "api_token": "{token_val}",\n'
                f'  "location": "office"\n'
                f'}}'
                f"</pre>\n"
                f"💡 <i>Field <code>location</code> bersifat opsional: gunakan <code>office</code> (WFO), <code>home</code> (WFH), atau <code>other</code>. Jika tidak disertakan, bot otomatis menggunakan profil aktif Anda.</i>"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔄 Buat Ulang Token", callback_data="log_regen_token"))
            markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            return

        elif data == "log_regen_token":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.from_user.id)
            if not user:
                bot.send_message(call.message.chat.id, "❌ Akun tidak ditemukan.")
                return

            new_token = regenerate_api_token(call.from_user.id)
            text = (
                f"🔄 <b>API Token Berhasil Dibuat Ulang!</b>\n\n"
                f"👤 Akun: <code>{user['username']}</code>\n"
                f"Token Baru:\n<code>{new_token}</code>\n\n"
                f"⚠️ Jangan lupa untuk memperbarui field <code>api_token</code> pada file <code>config.json</code> di laptop Anda."
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            return

        elif data == "log_menu_set_jam":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.message.chat.id)
            if not user:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                bot.edit_message_text("⚠️ Akun Anda belum terdaftar.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                return

            current_jam = user.get('reminder_time', '16:05')
            text = (
                f"⏰ <b>Atur Jam Pengingat Logbook</b>\n\n"
                f"Jam saat ini: <b>{current_jam} WIB</b>\n\n"
                f"Silakan ketik jam pengingat baru yang Anda inginkan (format 24 jam: <code>HH:MM</code>).\n"
                f"<i>Contoh:</i> <code>16:30</code> atau <code>17:00</code>\n\n"
                f"<i>Kirimkan balasan pesan dengan format di atas atau klik Batal:</i>"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("❌ Batal", callback_data="log_menu_back"))
            msg = bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
            bot.register_next_step_handler(msg, handle_set_jam_input, bot)
            return

        elif data == "log_menu_set_lokasi":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.message.chat.id)
            if not user:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                bot.edit_message_text("⚠️ Akun Anda belum terdaftar.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                return

            text, markup = render_locations_menu(call.message.chat.id)
            try:
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            except Exception:
                bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
            return

        elif data.startswith('log_loc_switch_'):
            key = data.split('_')[3]
            profiles = get_user_location_profiles(call.message.chat.id)
            target_p = profiles.get(key)
            if not target_p:
                bot.answer_callback_query(call.id, "Profil tidak ditemukan.")
                return

            if not target_p['is_set']:
                bot.answer_callback_query(call.id)
                p_name = target_p['profile_name']
                text = (
                    f"⚠️ <b>Profil {p_name} Belum Memiliki Koordinat!</b>\n\n"
                    f"Silakan kirimkan koordinat tempat ini agar dapat diaktifkan:\n"
                    f"1. 📎 <b>Pin Lokasi Telegram</b> (ikon 📎 ➔ Location)\n"
                    f"2. ✍️ <b>Teks Koordinat</b> (contoh: <code>-7.9467, 112.6156</code>)\n"
                    f"3. 🔗 <b>Link Google Maps</b>\n\n"
                    f"<i>Kirimkan sekarang atau klik Batal di bawah:</i>"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("❌ Batal", callback_data="log_menu_set_lokasi"))
                msg = bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
                bot.register_next_step_handler(msg, handle_set_profile_lokasi_input, bot, key)
                return

            set_active_location_profile(call.message.chat.id, key)
            bot.answer_callback_query(call.id, f"Profil aktif diubah ke {target_p['profile_name']}")
            text, markup = render_locations_menu(call.message.chat.id)
            try:
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            except Exception:
                bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
            return

        elif data.startswith('log_loc_edit_'):
            bot.answer_callback_query(call.id)
            key = data.split('_')[3]
            p_name = PROFILE_DEFINITIONS.get(key, key)
            loc = get_user_location(call.message.chat.id, profile_key=key)
            status_loc = f"<a href=\"https://www.google.com/maps?q={loc['lat']},{loc['lng']}\"><code>{loc['lat']}, {loc['lng']}</code></a> (±{loc['akurasi']}m)" if loc.get('lat') and loc.get('lat') != '-7.5815' else "<i>Belum disetel</i>"

            text = (
                f"📍 <b>Atur Koordinat untuk {p_name}</b>\n\n"
                f"Lokasi saat ini: {status_loc}\n\n"
                f"Silakan kirimkan koordinat baru:\n"
                f"1. 📎 <b>Pin Lokasi Telegram</b> (ikon 📎 ➔ Location)\n"
                f"2. ✍️ <b>Teks Koordinat</b> (contoh: <code>-7.9467, 112.6156</code>)\n"
                f"3. 🔗 <b>Link Google Maps</b>\n\n"
                f"<i>Kirimkan sekarang atau klik Batal di bawah:</i>"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("❌ Batal", callback_data="log_menu_set_lokasi"))
            msg = bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
            bot.register_next_step_handler(msg, handle_set_profile_lokasi_input, bot, key)
            return

        elif data == "log_menu_set_hari":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.message.chat.id)
            if not user:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                bot.edit_message_text("⚠️ Akun Anda belum terdaftar.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                return

            days_str = get_user_reminder_days(call.message.chat.id)
            days_display = format_reminder_days_display(days_str)
            text = (
                f"🗓 <b>Atur Hari Pengingat Logbook</b>\n\n"
                f"Hari aktif saat ini: <b>{days_display}</b>\n\n"
                f"Klik tombol hari di bawah untuk mengaktifkan (✅) atau menonaktifkan (⬜), "
                f"atau pilih salah satu tombol preset cepat:"
            )
            markup = build_days_checklist_keyboard(days_str)
            try:
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            except Exception:
                bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
            return

        elif data.startswith('log_daytg_'):
            bot.answer_callback_query(call.id)
            try:
                target_day = int(data.split('_')[2])
            except (IndexError, ValueError):
                return
            days_str = get_user_reminder_days(call.message.chat.id)
            active_set = parse_days_to_set(days_str)
            if target_day in active_set:
                active_set.remove(target_day)
            else:
                active_set.add(target_day)

            sorted_days = sorted(list(active_set))
            new_days_str = ",".join(str(d) for d in sorted_days)
            update_user_reminder_days(call.message.chat.id, new_days_str)

            days_display = format_reminder_days_display(new_days_str)
            text = (
                f"🗓 <b>Atur Hari Pengingat Logbook</b>\n\n"
                f"Hari aktif saat ini: <b>{days_display}</b>\n\n"
                f"Klik tombol hari di bawah untuk mengaktifkan (✅) atau menonaktifkan (⬜), "
                f"atau pilih salah satu tombol preset cepat:"
            )
            markup = build_days_checklist_keyboard(new_days_str)
            try:
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            except Exception:
                pass
            return

        elif data.startswith('log_dayps_'):
            bot.answer_callback_query(call.id)
            preset = data.split('_')[2]
            if preset == "weekdays":
                new_days_str = "0,1,2,3,4"
            elif preset == "6days":
                new_days_str = "0,1,2,3,4,5"
            elif preset == "all":
                new_days_str = "0,1,2,3,4,5,6"
            elif preset == "none":
                new_days_str = ""
            else:
                new_days_str = "0,1,2,3,4"

            update_user_reminder_days(call.message.chat.id, new_days_str)

            days_display = format_reminder_days_display(new_days_str)
            text = (
                f"🗓 <b>Atur Hari Pengingat Logbook</b>\n\n"
                f"Hari aktif saat ini: <b>{days_display}</b>\n\n"
                f"Klik tombol hari di bawah untuk mengaktifkan (✅) atau menonaktifkan (⬜), "
                f"atau pilih salah satu tombol preset cepat:"
            )
            markup = build_days_checklist_keyboard(new_days_str)
            try:
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            except Exception:
                pass
            return

        elif data == "log_menu_hapus":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.message.chat.id)
            if not user:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                bot.edit_message_text("ℹ️ Anda belum terdaftar di sistem logbook.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                return

            text = (
                f"⚠️ <b>Konfirmasi Hapus Akun Logbook</b>\n\n"
                f"Apakah Anda yakin ingin menghapus kredensial DERMAGA akun <code>{user['username']}</code> dan API Token Anda dari bot?\n\n"
                f"<i>Tindakan ini tidak dapat dibatalkan. Riwayat draf logbook lama Anda juga akan terhapus.</i>"
            )
            markup = types.InlineKeyboardMarkup(row_width=2)
            btn_confirm = types.InlineKeyboardButton("⚠️ Ya, Hapus Akun", callback_data="log_confirm_hapus_akun")
            btn_cancel = types.InlineKeyboardButton("❌ Batal", callback_data="log_menu_back")
            markup.add(btn_confirm, btn_cancel)
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            return

        elif data == "log_confirm_hapus_akun":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.message.chat.id)
            if user:
                delete_user_credential(call.message.chat.id)
                text = f"✅ Akun <code>{user['username']}</code> dan token Anda berhasil dihapus dari sistem bot."
            else:
                text = "ℹ️ Akun tidak ditemukan atau sudah dihapus."
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            return

        elif data == "log_menu_admin_users":
            bot.answer_callback_query(call.id)
            if not is_admin(call.from_user.id) and not (call.message and is_admin(call.message.chat.id)):
                bot.answer_callback_query(call.id, "⛔ Akses ditolak. Hanya untuk Admin.", show_alert=True)
                return

            users = get_all_users()
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))

            if not users:
                text = "👥 <b>Admin Panel Logbook</b>\n\n<i>Belum ada pengguna logbook yang terdaftar.</i>"
            else:
                text = f"👥 <b>Daftar Pengguna Logbook Terdaftar ({len(users)} User):</b>\n\n"
                for u in users:
                    status = "🟢 Aktif" if u['is_active'] else "🔴 Nonaktif"
                    token_snippet = u['api_token'][:6] + "..." + u['api_token'][-4:]
                    text += (
                        f"• 👤 <b>{u['username']}</b>\n"
                        f"  Chat ID: <code>{u['chat_id']}</code>\n"
                        f"  Token: <code>{token_snippet}</code> | Status: {status}\n"
                        f"  Terdaftar: <code>{u['created_at']}</code>\n\n"
                    )
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            return

        # --- EDIT LOGBOOK INTERAKTIF CALLBACKS ---
        elif data == "log_menu_edit":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.message.chat.id)
            if not user:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                bot.edit_message_text("⚠️ Akun DERMAGA Anda belum terdaftar.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                return

            try:
                bot.edit_message_text("⏳ <i>Sedang mengambil riwayat logbook dari portal DERMAGA...</i>", call.message.chat.id, call.message.message_id, parse_mode="HTML")
            except Exception:
                pass

            try:
                entries = fetch_dermaga_table(chat_id=call.message.chat.id)
                if not entries:
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                    bot.edit_message_text(
                        f"ℹ️ Belum ada entri logbook yang tercatat di akun DERMAGA <code>{user['username']}</code> untuk diedit.",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode="HTML",
                        reply_markup=markup
                    )
                    return

                editable_entries = [e for e in entries if e.get('web_id')]
                if not editable_entries:
                    editable_entries = entries

                grouped = group_entries_by_month(editable_entries)
                months_list = sorted(grouped.keys(), reverse=True)
                current_month = months_list[0] if months_list else datetime.now().strftime('%Y-%m')

                _edit_sessions[call.message.chat.id] = {
                    'all_entries': editable_entries,
                    'by_month': grouped,
                    'months': months_list,
                    'selected_month': current_month
                }

                send_month_view(bot, call.message.chat.id, current_month, old_message_id=call.message.message_id)
            except Exception as err:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                bot.edit_message_text(f"❌ Gagal mengambil data DERMAGA: {err}", call.message.chat.id, call.message.message_id, reply_markup=markup)
            return

        elif data.startswith('log_edmonth_'):
            bot.answer_callback_query(call.id)
            target_month = data.split('_')[2]
            session = _edit_sessions.get(call.message.chat.id)
            if not session or not session.get('by_month'):
                text, markup = render_logbook_menu(call.message.chat.id, call.from_user.id)
                try:
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                except Exception:
                    pass
                bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
                return
            session['selected_month'] = target_month
            send_month_view(bot, call.message.chat.id, target_month, old_message_id=call.message.message_id)
            return

        elif data.startswith('log_edpick_'):
            bot.answer_callback_query(call.id)
            web_id = data.split('_')[2]
            session = _edit_sessions.get(call.message.chat.id)
            if not session or not session.get('all_entries'):
                bot.send_message(call.message.chat.id, "❌ Sesi edit telah berakhir. Silakan buka kembali menu /logbook.")
                return

            selected_entry = None
            for e in session['all_entries']:
                if str(e.get('web_id')) == str(web_id):
                    selected_entry = e
                    break

            if not selected_entry:
                bot.send_message(call.message.chat.id, "❌ Entri logbook tidak ditemukan.")
                return

            session['web_id'] = str(selected_entry['web_id'])
            session['tanggal'] = str(selected_entry.get('tanggal_iso', ''))
            session['jam_masuk'] = str(selected_entry.get('jam_masuk') or '07:10')
            session['jam_pulang'] = str(selected_entry.get('jam_pulang') or '16:25')
            session['deskripsi'] = str(selected_entry.get('pekerjaan') or '')
            session['keterangan'] = str(selected_entry.get('keterangan') or 'hadir')
            session['original'] = {
                'jam_masuk': session['jam_masuk'],
                'jam_pulang': session['jam_pulang'],
                'deskripsi': session['deskripsi']
            }

            send_detail_view(bot, call.message.chat.id, old_message_id=call.message.message_id)
            return

        elif data == "log_edact_masuk":
            bot.answer_callback_query(call.id)
            session = _edit_sessions.get(call.message.chat.id)
            if not session:
                bot.send_message(call.message.chat.id, "❌ Sesi edit telah berakhir.")
                return

            prompt_msg = bot.send_message(
                call.message.chat.id,
                f"⏰ <b>Ubah Jam Masuk (Tanggal {session['tanggal']})</b>\n\n"
                f"Jam masuk saat ini: <code>{session['jam_masuk']}</code>\n"
                f"Silakan ketik jam masuk baru (format 24 jam <code>HH:MM</code>, contoh: <code>07:15</code>):",
                parse_mode="HTML"
            )
            session['prompt_msg_id'] = prompt_msg.message_id
            bot.register_next_step_handler(prompt_msg, handle_input_edit_masuk, bot)
            return

        elif data == "log_edact_pulang":
            bot.answer_callback_query(call.id)
            session = _edit_sessions.get(call.message.chat.id)
            if not session:
                bot.send_message(call.message.chat.id, "❌ Sesi edit telah berakhir.")
                return

            prompt_msg = bot.send_message(
                call.message.chat.id,
                f"⏰ <b>Ubah Jam Pulang (Tanggal {session['tanggal']})</b>\n\n"
                f"Jam pulang saat ini: <code>{session['jam_pulang']}</code>\n"
                f"Silakan ketik jam pulang baru (format 24 jam <code>HH:MM</code>, contoh: <code>16:30</code>):",
                parse_mode="HTML"
            )
            session['prompt_msg_id'] = prompt_msg.message_id
            bot.register_next_step_handler(prompt_msg, handle_input_edit_pulang, bot)
            return

        elif data == "log_edact_desk":
            bot.answer_callback_query(call.id)
            session = _edit_sessions.get(call.message.chat.id)
            if not session:
                bot.send_message(call.message.chat.id, "❌ Sesi edit telah berakhir.")
                return

            prompt_msg = bot.send_message(
                call.message.chat.id,
                f"📝 <b>Ubah Deskripsi Pekerjaan (Tanggal {session['tanggal']})</b>\n\n"
                f"Deskripsi saat ini:\n<i>{html.escape(session['deskripsi'])}</i>\n\n"
                f"Silakan ketikkan deskripsi pekerjaan baru yang ingin Anda simpan:",
                parse_mode="HTML"
            )
            session['prompt_msg_id'] = prompt_msg.message_id
            bot.register_next_step_handler(prompt_msg, handle_input_edit_deskripsi, bot)
            return

        elif data == "log_edact_save":
            bot.answer_callback_query(call.id)
            session = _edit_sessions.get(call.message.chat.id)
            if not session or not session.get('web_id'):
                bot.send_message(call.message.chat.id, "❌ Sesi edit tidak ditemukan.")
                return

            orig = session.get('original', {})
            masuk_changed = (session['jam_masuk'] != orig.get('jam_masuk'))
            pulang_changed = (session['jam_pulang'] != orig.get('jam_pulang'))
            desk_changed = (session['deskripsi'] != orig.get('deskripsi'))
            if not (masuk_changed or pulang_changed or desk_changed):
                bot.answer_callback_query(call.id, "Belum ada perubahan data yang dilakukan.", show_alert=True)
                return

            tgl = session.get('tanggal', '-')
            web_id = session.get('web_id', '-')
            masuk = session.get('jam_masuk', '07:10')
            pulang = session.get('jam_pulang', '16:25')
            desk = html.escape(session.get('deskripsi', '-'))

            confirm_text = (
                f"📖 <b>Konfirmasi Perubahan Logbook DERMAGA</b>\n\n"
                f"🗓 <b>Tanggal:</b> <code>{tgl}</code> (ID: <code>#{web_id}</code>)\n"
                f"⏰ <b>Jam Kerja:</b> <code>{masuk} - {pulang}</code>\n"
                f"📦 <b>Proyek:</b> <b>Update Logbook</b>\n\n"
                f"📝 <b>Ringkasan Aktivitas Terbaru:</b>\n"
                f"{desk}\n\n"
                f"Silakan konfirmasi untuk memperbarui data pada portal DERMAGA:"
            )

            markup = types.InlineKeyboardMarkup(row_width=3)
            btn_confirm = types.InlineKeyboardButton("✅ Konfirmasi", callback_data="log_edact_confirmsave")
            btn_reedit = types.InlineKeyboardButton("✏️ Ubah", callback_data="log_edact_reedit")
            btn_cancel = types.InlineKeyboardButton("❌ Batal", callback_data="log_edact_cancel")
            markup.add(btn_confirm, btn_reedit, btn_cancel)

            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass

            bot.send_message(call.message.chat.id, confirm_text, parse_mode="HTML", reply_markup=markup)
            return

        elif data == "log_edact_confirmsave":
            bot.answer_callback_query(call.id)
            session = _edit_sessions.pop(call.message.chat.id, None)
            if not session or not session.get('web_id'):
                bot.send_message(call.message.chat.id, "❌ Sesi edit tidak ditemukan atau sudah kadaluarsa.")
                return

            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            except Exception:
                pass

            loading = bot.send_message(
                call.message.chat.id,
                f"⏳ Sedang memperbarui logbook tanggal <code>{session['tanggal']}</code> (ID: #{session['web_id']}) di DERMAGA...",
                parse_mode="HTML"
            )

            draft_payload = {
                'chat_id': call.message.chat.id,
                'date': session['tanggal'],
                'commits_summary': session['deskripsi'],
                'jam_masuk': session['jam_masuk'],
                'jam_pulang': session['jam_pulang']
            }

            res = submit_logbook_to_dermaga(draft_payload, override_id=session['web_id'])

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📖 Buka Menu Logbook", callback_data="log_menu_back"))

            if res['status'] == 'SUCCESS':
                success_text = (
                    f"🎉 <b>Logbook Berhasil Diperbarui!</b>\n\n"
                    f"🗓 Tanggal: <code>{session['tanggal']}</code> (ID: <code>#{res['web_id']}</code>)\n"
                    f"⏰ Jam: <code>{session['jam_masuk']} - {session['jam_pulang']}</code>\n"
                    f"📝 Data di portal DERMAGA telah terverifikasi berhasil diperbarui."
                )
                bot.edit_message_text(success_text, call.message.chat.id, loading.message_id, parse_mode="HTML", reply_markup=markup)
            else:
                err_msg = res.get('message', 'Terjadi kesalahan')
                bot.edit_message_text(f"❌ <b>Gagal Memperbarui Logbook:</b>\n{err_msg}", call.message.chat.id, loading.message_id, parse_mode="HTML", reply_markup=markup)
            return

        elif data == "log_edact_reedit":
            bot.answer_callback_query(call.id)
            send_detail_view(bot, call.message.chat.id, old_message_id=call.message.message_id)
            return

        elif data == "log_edact_backmonth":
            bot.answer_callback_query(call.id)
            session = _edit_sessions.get(call.message.chat.id)
            if not session or not session.get('selected_month'):
                text, markup = render_logbook_menu(call.message.chat.id, call.from_user.id)
                try:
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                except Exception:
                    pass
                bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
                return
            send_month_view(bot, call.message.chat.id, session['selected_month'], old_message_id=call.message.message_id)
            return

        elif data == "log_edact_cancel":
            bot.answer_callback_query(call.id)
            _edit_sessions.pop(call.message.chat.id, None)
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            text, markup = render_logbook_menu(call.message.chat.id, call.from_user.id)
            bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
            return

        # --- REMINDER CALLBACKS (FILL / STOP) ---
        elif data.startswith('log_remind_fill'):
            bot.answer_callback_query(call.id)
            parts = data.split('_')
            target_date = parts[3] if len(parts) > 3 else datetime.now().strftime('%Y-%m-%d')
            prompt_msg = bot.send_message(
                call.message.chat.id,
                f"✍️ <b>Input Logbook Tanggal {target_date}</b>\n\n"
                f"Silakan ketikkan deskripsi pekerjaan/aktivitas Anda hari ini:",
                parse_mode="HTML"
            )
            bot.register_next_step_handler(prompt_msg, handle_manual_logbook_input, bot, target_date)
            return

        elif data.startswith('log_remind_stop'):
            bot.answer_callback_query(call.id)
            parts = data.split('_')
            target_date = parts[3] if len(parts) > 3 else datetime.now().strftime('%Y-%m-%d')
            stop_reminder_for_today(call.message.chat.id, target_date)
            user_time = get_user_reminder_time(call.message.chat.id)
            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            except Exception:
                pass
            bot.send_message(
                call.message.chat.id,
                f"🔕 <b>Pengingat Dihentikan untuk Hari Ini</b>\n\n"
                f"Bot tidak akan melakukan pengecekan atau mengirim pengingat logbook lagi untuk tanggal <code>{target_date}</code>.\n"
                f"Anda akan diingatkan kembali besok pada jam <b>{user_time} WIB</b>.",
                parse_mode="HTML"
            )
            return

        # --- DRAFT CALLBACKS (SUBMIT / OVERRIDE / SKIP / EDIT / CANCEL / LOCATION SWITCH) ---
        draft_id = None
        if data.startswith(('log_confirm_', 'log_skip_', 'log_edit_', 'log_cancel_')):
            draft_id = int(data.split('_')[2])
        elif data.startswith('log_over_'):
            draft_id = int(data.split('_')[2])
        elif data.startswith('log_draft_loc_'):
            parts = data.split('_')
            draft_id = int(parts[3])

        if not draft_id:
            bot.answer_callback_query(call.id, "Data callback tidak valid.", show_alert=True)
            return

        draft = get_draft(draft_id)
        if not draft:
            bot.answer_callback_query(call.id, "Draf tidak ditemukan.", show_alert=True)
            return

        # Cek otorisasi user: hanya pemilik draft atau bot admin yang diizinkan
        is_owner = (draft.get('chat_id') and call.from_user.id == draft.get('chat_id'))
        is_bot_admin = is_admin(call.from_user.id) or (call.message and is_admin(call.message.chat.id))

        if not (is_owner or is_bot_admin):
            bot.answer_callback_query(call.id, "⛔ Akses ditolak. Anda bukan pemilik draf ini.", show_alert=True)
            return

        bot.answer_callback_query(call.id)

        # 1. Konfirmasi Submit
        if data.startswith('log_confirm_'):
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            bot.send_message(call.message.chat.id, f"⏳ Sedang memproses submit logbook #{draft_id} ke DERMAGA...")

            res = submit_logbook_to_dermaga(draft)

            if res['status'] == 'EXISTS':
                # Tanggal sudah ada entri di website -> Beri pilihan Timpa / Biarkan
                web_id = res['web_id']
                existing_desc = html.escape(res.get('existing_deskripsi') or '-')
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                btn_over = types.InlineKeyboardButton("🔄 Timpa / Update", callback_data=f"log_over_{draft_id}_{web_id}")
                btn_skip = types.InlineKeyboardButton("⏩ Biarkan (Skip)", callback_data=f"log_skip_{draft_id}")
                markup.add(btn_over, btn_skip)

                msg_warning = (
                    f"⚠️ <b>Logbook Hari Ini Sudah Ada di DERMAGA!</b>\n\n"
                    f"Entri tanggal <code>{draft['date']}</code> sudah terdaftar dengan ID: <code>{web_id}</code>.\n\n"
                    f"<b>Deskripsi saat ini di website:</b>\n"
                    f"<i>{existing_desc}</i>\n\n"
                    f"Pilih tindakan yang ingin diambil:"
                )
                bot.send_message(call.message.chat.id, msg_warning, parse_mode="HTML", reply_markup=markup)

            elif res['status'] == 'SUCCESS':
                update_draft_status(draft_id, 'submitted')
                if draft.get('chat_id') and draft.get('date'):
                    complete_reminder_for_today(draft['chat_id'], draft['date'])
                bot.send_message(call.message.chat.id, f"🎉 <b>Sukses!</b> {res['message']}", parse_mode="HTML")
            else:
                err_msg = res.get('message', 'Terjadi kesalahan')
                update_draft_status(draft_id, 'failed', error_message=err_msg)
                
                # Sediakan tombol coba lagi
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔄 Coba Submit Ulang", callback_data=f"log_confirm_{draft_id}"))
                bot.send_message(call.message.chat.id, f"❌ <b>Gagal Submit:</b> {err_msg}", parse_mode="HTML", reply_markup=markup)

        # 2. Timpa entri yang ada di website
        elif data.startswith('log_over_'):
            parts = data.split('_')
            web_id = parts[3]

            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            bot.send_message(call.message.chat.id, f"⏳ Sedang menimpa logbook ID <code>{web_id}</code> di DERMAGA...", parse_mode="HTML")

            res = submit_logbook_to_dermaga(draft, override_id=web_id)
            if res['status'] == 'SUCCESS':
                update_draft_status(draft_id, 'submitted')
                if draft.get('chat_id') and draft.get('date'):
                    complete_reminder_for_today(draft['chat_id'], draft['date'])
                bot.send_message(call.message.chat.id, f"✅ <b>Logbook berhasil diperbarui</b> di portal DERMAGA!", parse_mode="HTML")
            else:
                err_msg = res.get('message', 'Gagal memperbarui logbook')
                update_draft_status(draft_id, 'failed', error_message=err_msg)
                bot.send_message(call.message.chat.id, f"❌ <b>Gagal Memperbarui:</b> {err_msg}", parse_mode="HTML")

        # 3. Biarkan entri lama (Skip)
        elif data.startswith('log_skip_'):
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            update_draft_status(draft_id, 'skipped')
            if draft.get('chat_id') and draft.get('date'):
                complete_reminder_for_today(draft['chat_id'], draft['date'])
            bot.send_message(call.message.chat.id, f"⏩ Draf logbook #{draft_id} ditandai selesai (dilewati). Data di DERMAGA tidak diubah.")

        # 4. Ubah draf
        elif data.startswith('log_edit_'):
            prompt_msg = bot.send_message(
                call.message.chat.id,
                f"✏️ <b>Edit Draf #{draft_id}</b>\nSilakan ketik atau tempel teks ringkasan logbook baru:",
                parse_mode="HTML"
            )
            bot.register_next_step_handler(prompt_msg, handle_edit_input, bot, draft_id)

        # 5. Batalkan draf
        elif data.startswith('log_cancel_'):
            update_draft_status(draft_id, 'cancelled')
            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            except Exception:
                pass
            bot.send_message(call.message.chat.id, f"❌ Draf logbook #{draft_id} telah <b>dibatalkan</b>.", parse_mode="HTML")

        # 6. Ganti lokasi submit draf (Switch WFO / WFH / Lain)
        elif data.startswith('log_draft_loc_'):
            parts = data.split('_')
            target_profile = parts[4]

            # Cek apakah koordinat target_profile sudah disetel
            profiles = get_user_location_profiles(draft['chat_id'])
            target_p = profiles.get(target_profile)
            if not target_p or not target_p['is_set']:
                p_name = PROFILE_DEFINITIONS.get(target_profile, target_profile)
                bot.answer_callback_query(call.id, f"⚠️ Profil {p_name} belum disetel koordinatnya! Atur dulu di menu Lokasi GPS.", show_alert=True)
                return

            update_draft_location_profile(draft_id, target_profile)
            updated_draft = get_draft(draft_id)
            new_text = format_draft_message(updated_draft)
            new_markup = build_draft_keyboard(draft_id, target_profile)
            try:
                bot.edit_message_text(new_text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=new_markup)
            except Exception:
                pass
            bot.answer_callback_query(call.id, f"Lokasi draf diubah ke: {target_p['profile_name']}")
            return

def jalankan_server(bot):
    """Runner thread untuk HTTP Server receiver yang meneruskan draf baru ke Telegram."""
    def on_new_draft(draft):
        # Prioritas penuh logbook_cli: batalkan pengingat hari ini dan bersihkan tombol pengingat sebelumnya
        if draft.get('chat_id') and draft.get('date'):
            cancel_reminder_for_cli(bot, draft['chat_id'], draft['date'])
        send_draft_confirmation(bot, draft['id'])

    run_http_server(on_draft_cb=on_new_draft)

def jalankan_scheduler(bot):
    """Runner thread untuk scheduler background pengingat logbook."""
    jalankan_logbook_scheduler(bot)
