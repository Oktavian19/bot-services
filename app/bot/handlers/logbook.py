"""
Router Aiogram komprehensif untuk modul Logbook DERMAGA Polinema.
Menangani pendaftaran kredensial, draf CLI, persetujuan pengiriman ke DERMAGA, GPS lokasi, dan kalender.
"""

from datetime import datetime
import html
import time
from typing import Optional
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from app.bot.keyboards.logbook import (
    get_back_to_logbook_keyboard,
    get_draft_approval_keyboard,
    get_locations_menu_keyboard,
    get_logbook_hub_keyboard,
    get_reminder_days_checklist_keyboard,
    get_settings_menu_keyboard,
)
from app.core.config import get_settings
from app.core.logger import logger
from app.database.logbook_repo import (
    PROFILE_DEFINITIONS,
    complete_reminder_for_today,
    create_or_get_draft,
    delete_user_credential,
    get_active_location_profile,
    get_all_users,
    get_draft,
    get_recent_drafts,
    get_user_by_chat_id,
    get_user_location,
    get_user_location_profiles,
    get_user_reminder_days,
    get_user_reminder_time,
    regenerate_api_token,
    register_user_credential,
    save_location_profile,
    set_active_location_profile,
    stop_reminder_for_today,
    update_draft_location_profile,
    update_draft_status,
    update_draft_summary,
    update_user_location,
    update_user_reminder_days,
    update_user_reminder_time,
)
from app.services.logbook_service import (
    fetch_dermaga_table,
    format_draft_message,
    format_reminder_days_display,
    parse_coordinates_input,
    submit_dermaga_entry,
    test_dermaga_login,
)

router = Router(name="logbook_router")


# --- FSM STATES ---

class LogbookManualFillFSM(StatesGroup):
    waiting_for_text = State()


class LogbookEditSummaryFSM(StatesGroup):
    waiting_for_summary = State()


class LogbookSetJamFSM(StatesGroup):
    waiting_for_time = State()


class LogbookSetLocFSM(StatesGroup):
    waiting_for_location = State()


# --- HUB /LOGBOOK ---

async def render_hub_view(chat_id: int, is_admin: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    """Menyusun teks menu utama logbook dan tombol navigasi."""
    user = await get_user_by_chat_id(chat_id)
    if not user:
        text = (
            "📖 <b>Pusat Kendali Logbook DERMAGA Polinema</b>\n\n"
            "⚠️ Akun DERMAGA Anda belum terhubung di bot ini.\n\n"
            "Gunakan perintah:\n"
            "<code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code>\n"
            "<i>(Pesan otomatis dihapus demi keamanan).</i>"
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Daftar / Login Akun", callback_data="log_menu_account")]
        ])
        return text, markup

    username = user["username"]
    token = user.get("api_token", "-")
    short_token = f"{token[:8]}...{token[-4:]}" if token and len(token) > 12 else token
    reminder_time = user.get("reminder_time", "16:05")
    reminder_days = user.get("reminder_days", "0,1,2,3,4")
    active_prof = user.get("active_profile", "office")
    prof_info = PROFILE_DEFINITIONS.get(active_prof, {})
    prof_name = prof_info.get("default_name", active_prof.title())

    recent_drafts = await get_recent_drafts(chat_id, limit=3)
    drafts_text = ""
    if recent_drafts:
        drafts_text = "\n<b>Draf Logbook Terbaru:</b>\n"
        for d in recent_drafts:
            status_icon = "⏳" if d["status"] == "draft" else "✅"
            drafts_text += f"• {status_icon} <code>{d['date']}</code>: {d['summary'][:40]}...\n"

    text = (
        f"📖 <b>Pusat Kendali Logbook DERMAGA</b>\n\n"
        f"👤 <b>Pengguna:</b> <code>{username}</code>\n"
        f"🔑 <b>API Token:</b> <code>{short_token}</code>\n"
        f"⏰ <b>Jam Pengingat:</b> <b>{reminder_time} WIB</b>\n"
        f"🗓 <b>Jadwal Pengingat:</b> <b>{format_reminder_days_display(reminder_days)}</b>\n"
        f"📍 <b>Profil Lokasi Aktif:</b> <b>{prof_name}</b>\n"
        f"{drafts_text}\n"
        f"Silakan pilih menu di bawah ini:"
    )
    markup = get_logbook_hub_keyboard(is_admin_user=is_admin)
    return text, markup


async def show_logbook_hub(target: Message, chat_id: int, is_admin: bool = False) -> None:
    """Menampilkan hub logbook ke chat Telegram."""
    text, markup = await render_hub_view(chat_id, is_admin)
    await target.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(Command("logbook"))
async def cmd_logbook(message: Message, is_admin: bool = False) -> None:
    """Command /logbook."""
    await show_logbook_hub(message, message.chat.id, is_admin)


@router.callback_query(F.data == "cb_logbook")
@router.callback_query(F.data == "log_menu_back")
@router.callback_query(F.data == "log_menu_refresh")
async def cb_logbook_nav(callback: CallbackQuery, is_admin: bool = False) -> None:
    """Navigasi callback ke menu utama logbook."""
    await callback.answer()
    if callback.message:
        text, markup = await render_hub_view(callback.from_user.id, is_admin)
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)


# --- PENDAFTARAN AKUN DERMAGA ---

@router.message(Command("daftar_logbook", "login_logbook", "set_dermaga_auth"))
async def cmd_daftar_logbook(message: Message) -> None:
    """Pendaftaran kredensial DERMAGA dan penerbitan API token CLI."""
    settings = get_settings()

    # Hapus pesan perintah asli yang memuat password untuk melindungi kredensial
    try:
        await message.delete()
    except Exception:
        pass

    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer(
            "❌ Format salah.\n"
            "Gunakan: <code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code>\n\n"
            "<i>Contoh:</i> <code>/daftar_logbook 2341720117 Rahasia123</code>",
            parse_mode="HTML"
        )
        return

    username = parts[1].strip()
    password = parts[2].strip()

    loading = await message.answer(
        f"⏳ <i>Sedang menguji autentikasi akun <code>{username}</code> ke portal DERMAGA...</i>",
        parse_mode="HTML"
    )

    ok, msg = await test_dermaga_login(username, password)
    if not ok:
        await loading.edit_text(
            f"❌ <b>Verifikasi DERMAGA Gagal!</b>\n\n{msg}\n\n"
            f"Silakan periksa kembali username/NIM dan password Anda.",
            parse_mode="HTML"
        )
        return

    try:
        token = await register_user_credential(message.chat.id, username, password)
        public_url = settings.LOGBOOK_PUBLIC_URL

        success_text = (
            f"🎉 <b>Pendaftaran Logbook DERMAGA Berhasil!</b>\n\n"
            f"👤 Akun: <code>{username}</code>\n"
            f"🔑 <b>API Token CLI Anda:</b>\n"
            f"<code>{token}</code>\n\n"
            f"📋 <b>Konfigurasi di Laptop / CLI Anda:</b>\n"
            f"Salin file <code>config.example.json</code> menjadi <code>config.json</code>, lalu sesuaikan:\n"
            f"<pre>"
            f"{{\n"
            f'  "vps_endpoint": "{public_url}",\n'
            f'  "api_token": "{token}",\n'
            f'  "location": "office"\n'
            f"}}"
            f"</pre>"
        )
        markup = get_back_to_logbook_keyboard()
        await loading.edit_text(success_text, parse_mode="HTML", reply_markup=markup)
        logger.info(f"[LOGBOOK] User {message.chat.id} ({username}) berhasil terdaftar/update.")
    except Exception as e:
        await loading.edit_text(f"❌ Terjadi kesalahan saat menyimpan akun: {e}")


# --- TOKEN LOGBOOK ---

@router.message(Command("token_logbook"))
@router.callback_query(F.data == "log_menu_token")
async def cmd_token_logbook(event: Message | CallbackQuery) -> None:
    """Menampilkan token API CLI logbook."""
    settings = get_settings()
    chat_id = event.chat.id if isinstance(event, Message) else event.from_user.id
    target_msg = event if isinstance(event, Message) else event.message

    if isinstance(event, CallbackQuery):
        await event.answer()

    user = await get_user_by_chat_id(chat_id)
    if not user:
        await target_msg.answer(
            "⚠️ Akun Anda belum terdaftar. Gunakan <code>/daftar_logbook</code> terlebih dahulu.",
            parse_mode="HTML"
        )
        return

    token = user.get("api_token", "-")
    public_url = settings.LOGBOOK_PUBLIC_URL

    text = (
        f"🔑 <b>API Token CLI Logbook Anda</b>\n\n"
        f"👤 Akun: <code>{user['username']}</code>\n"
        f"Token:\n<code>{token}</code>\n\n"
        f"📋 <b>Konfigurasi di config.json:</b>\n"
        f"<pre>"
        f"{{\n"
        f'  "vps_endpoint": "{public_url}",\n'
        f'  "api_token": "{token}",\n'
        f'  "location": "office"\n'
        f"}}"
        f"</pre>"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Buat Ulang Token", callback_data="log_regen_token")],
        [InlineKeyboardButton(text="⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back")],
    ])
    await target_msg.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data == "log_regen_token")
async def cb_regen_token(callback: CallbackQuery) -> None:
    """Membuat ulang API token."""
    await callback.answer()
    new_token = await regenerate_api_token(callback.from_user.id)
    if callback.message:
        if new_token:
            await callback.message.answer(
                f"✅ <b>API Token Baru Berhasil Dibuat:</b>\n\n<code>{new_token}</code>\n\n"
                f"<i>Jangan lupa memperbarui file config.json di laptop Anda.</i>",
                parse_mode="HTML"
            )
        else:
            await callback.message.answer("⚠️ Gagal membuat ulang token.")


# --- CEK TABEL DERMAGA ---

@router.message(Command("cek_logbook"))
@router.callback_query(F.data == "log_menu_cek")
async def cmd_cek_logbook(event: Message | CallbackQuery) -> None:
    """Mengambil live table logbook dari web DERMAGA."""
    chat_id = event.chat.id if isinstance(event, Message) else event.from_user.id
    target_msg = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()

    loading = await target_msg.answer("⏳ <i>Sedang mengambil data tabel logbook dari DERMAGA...</i>", parse_mode="HTML")
    try:
        entries = await fetch_dermaga_table(chat_id)
        markup = get_back_to_logbook_keyboard()

        if not entries:
            await loading.edit_text("ℹ️ Belum ada entri logbook yang tercatat di tabel DERMAGA.", reply_markup=markup)
            return

        text = f"📋 <b>Daftar Logbook DERMAGA ({len(entries)} Entri):</b>\n\n"
        for e in entries[:10]:
            desc = html.escape(e["pekerjaan"])
            if len(desc) > 160:
                desc = desc[:157] + "..."
            text += (
                f"📅 <b>{e['tanggal_text']}</b> (ID: <code>#{e['web_id'] or '-'}</code>)\n"
                f"⏱️ <code>{e['jam']}</code> | Ket: <b>{e['keterangan']}</b> | Status: <b>{e['status_verif']}</b>\n"
                f"📝 <i>{desc}</i>\n\n"
            )
        if len(entries) > 10:
            text += f"<i>...dan {len(entries) - 10} entri lainnya di DERMAGA.</i>"

        await loading.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception as err:
        await loading.edit_text(f"❌ Gagal mengambil data DERMAGA: {err}", reply_markup=get_back_to_logbook_keyboard())


# --- PENGATURAN JAM PENGINGAT ---

@router.message(Command("set_jam_logbook", "jam_logbook"))
@router.callback_query(F.data == "log_menu_set_jam")
async def cmd_set_jam_logbook(event: Message | CallbackQuery, state: FSMContext) -> None:
    """Mengatur jam pengingat harian logbook."""
    chat_id = event.chat.id if isinstance(event, Message) else event.from_user.id
    target_msg = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()

    if isinstance(event, Message) and len(event.text.split()) > 1:
        time_str = event.text.split()[1].strip()
        try:
            h, m = time_str.split(":")
            norm_time = f"{int(h):02d}:{int(m):02d}"
            await update_user_reminder_time(chat_id, norm_time)
            await target_msg.answer(
                f"✅ <b>Jam Pengingat Berhasil Diubah!</b>\n\nSetiap hari pukul <b>{norm_time} WIB</b> bot akan mengingatkan pengisian logbook.",
                parse_mode="HTML",
                reply_markup=get_back_to_logbook_keyboard()
            )
            return
        except Exception:
            await target_msg.answer("❌ Format jam salah. Harap gunakan format 24 jam HH:MM (contoh: 16:30).")
            return

    current_time = await get_user_reminder_time(chat_id)
    await state.set_state(LogbookSetJamFSM.waiting_for_time)
    await target_msg.answer(
        f"⏰ <b>Pengaturan Jam Pengingat Logbook</b>\n\n"
        f"Jam saat ini: <b>{current_time} WIB</b>\n\n"
        f"Silakan ketikkan jam pengingat baru (Format HH:MM, contoh: 16:30):"
    )


@router.message(LogbookSetJamFSM.waiting_for_time)
async def process_set_jam_input(message: Message, state: FSMContext) -> None:
    """Menerima input jam baru."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pengaturan jam pengingat dibatalkan.")
        return

    time_str = message.text.strip()
    try:
        parts = time_str.split(":")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError()
        norm_time = f"{h:02d}:{m:02d}"
        await state.clear()
        await update_user_reminder_time(message.chat.id, norm_time)
        await message.answer(
            f"✅ <b>Jam Pengingat Berhasil Disimpan!</b>\n\n"
            f"Mulai hari ini, Anda akan diingatkan pada pukul <b>{norm_time} WIB</b>.",
            parse_mode="HTML",
            reply_markup=get_back_to_logbook_keyboard()
        )
    except Exception:
        await message.answer("❌ Format jam tidak valid. Harap gunakan format 24 jam <code>HH:MM</code> (contoh: 16:05):", parse_mode="HTML")


# --- PENGATURAN HARI PENGINGAT ---

@router.message(Command("set_hari_logbook", "hari_logbook"))
@router.callback_query(F.data == "log_menu_set_hari")
async def cmd_set_hari_logbook(event: Message | CallbackQuery) -> None:
    """Membuka checklist hari pengingat aktif."""
    chat_id = event.chat.id if isinstance(event, Message) else event.from_user.id
    target_msg = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()

    current_days = await get_user_reminder_days(chat_id)
    text = (
        f"🗓 <b>Pengaturan Hari Pengingat Logbook</b>\n\n"
        f"Jadwal aktif saat ini: <b>{format_reminder_days_display(current_days)}</b>\n\n"
        f"Pilih hari atau gunakan preset di bawah ini:"
    )
    markup = get_reminder_days_checklist_keyboard(current_days)
    await target_msg.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("log_daytg_"))
async def cb_toggle_reminder_day(callback: CallbackQuery) -> None:
    """Toggle status hari tertentu di checklist."""
    await callback.answer()
    day_idx = int(callback.data.split("_")[2])
    chat_id = callback.from_user.id
    current_days_str = await get_user_reminder_days(chat_id)
    days = set(int(x.strip()) for x in current_days_str.split(",") if x.strip().isdigit())

    if day_idx in days:
        days.remove(day_idx)
    else:
        days.add(day_idx)

    new_days_str = ",".join(str(d) for d in sorted(list(days)))
    await update_user_reminder_days(chat_id, new_days_str)

    text = (
        f"🗓 <b>Pengaturan Hari Pengingat Logbook</b>\n\n"
        f"Jadwal aktif saat ini: <b>{format_reminder_days_display(new_days_str)}</b>\n\n"
        f"Pilih hari atau gunakan preset di bawah ini:"
    )
    markup = get_reminder_days_checklist_keyboard(new_days_str)
    if callback.message:
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass


@router.callback_query(F.data.startswith("log_dayps_"))
async def cb_preset_reminder_day(callback: CallbackQuery) -> None:
    """Terapkan preset hari pengingat."""
    await callback.answer()
    preset = callback.data.split("_")[2]
    chat_id = callback.from_user.id

    if preset == "weekdays":
        new_days = "0,1,2,3,4"
    elif preset == "all":
        new_days = "0,1,2,3,4,5,6"
    else:
        new_days = ""

    await update_user_reminder_days(chat_id, new_days)
    text = (
        f"🗓 <b>Pengaturan Hari Pengingat Logbook</b>\n\n"
        f"Jadwal aktif saat ini: <b>{format_reminder_days_display(new_days)}</b>\n\n"
        f"Pilih hari atau gunakan preset di bawah ini:"
    )
    markup = get_reminder_days_checklist_keyboard(new_days)
    if callback.message:
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass


# --- PENGATURAN LOKASI GPS ---

@router.message(Command("set_lokasi_logbook", "lokasi_logbook", "set_gps_logbook"))
@router.callback_query(F.data == "log_menu_set_lokasi")
async def cmd_set_lokasi(event: Message | CallbackQuery) -> None:
    """Menampilkan menu profil lokasi GPS magang."""
    chat_id = event.chat.id if isinstance(event, Message) else event.from_user.id
    target_msg = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()

    profiles = await get_user_location_profiles(chat_id)
    active_profile = await get_active_location_profile(chat_id)

    text = "📍 <b>Pengaturan Profil Lokasi GPS Magang</b>\n\n"
    for p in profiles:
        p_key = p["profile_key"]
        p_def = PROFILE_DEFINITIONS.get(p_key, {})
        icon = p_def.get("icon", "📍")
        label = p_def.get("label", p_key.title())
        is_active = (p_key == active_profile)
        status_tag = " <b>[AKTIF]</b>" if is_active else ""
        maps_url = f"https://www.google.com/maps?q={p['latitude']},{p['longitude']}"
        text += (
            f"{icon} <b>{label}</b>{status_tag}\n"
            f"   Koordinat: <a href=\"{maps_url}\"><code>{p['latitude']}, {p['longitude']}</code></a> (±{p['accuracy']}m)\n\n"
        )
    text += "Klik tombol di bawah untuk berganti profil aktif atau mengatur koordinat baru:"
    markup = get_locations_menu_keyboard(profiles, active_profile)
    await target_msg.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("log_loc_switch_"))
async def cb_switch_location_profile(callback: CallbackQuery) -> None:
    """Ganti profil lokasi aktif."""
    await callback.answer()
    p_key = callback.data.split("_")[3]
    await set_active_location_profile(callback.from_user.id, p_key)
    profiles = await get_user_location_profiles(callback.from_user.id)
    markup = get_locations_menu_keyboard(profiles, p_key)
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=markup)
        except Exception:
            pass


@router.callback_query(F.data.startswith("log_loc_edit_"))
async def cb_start_edit_location(callback: CallbackQuery, state: FSMContext) -> None:
    """Minta input koordinat baru untuk profil lokasi."""
    await callback.answer()
    p_key = callback.data.split("_")[3]
    p_def = PROFILE_DEFINITIONS.get(p_key, {})
    await state.set_state(LogbookSetLocFSM.waiting_for_location)
    await state.update_data(target_profile=p_key)
    if callback.message:
        await callback.message.answer(
            f"📍 <b>Atur Lokasi {p_def.get('label', p_key)}</b>\n\n"
            f"Silakan kirimkan salah satu di bawah ini:\n"
            f"• 📎 Share pin lokasi langsung dari Telegram (Live Location)\n"
            f"• Angka koordinat: <code>-7.9467, 112.6156</code>\n"
            f"• Tautan Google Maps tempat magang.",
            parse_mode="HTML"
        )


@router.message(LogbookSetLocFSM.waiting_for_location)
async def process_location_input(message: Message, state: FSMContext) -> None:
    """Menerima kiriman koordinat GPS teks atau URL Google Maps."""
    data = await state.get_data()
    p_key = data.get("target_profile", "office")

    # 1. Jika via location pin
    if message.location:
        lat_str = f"{message.location.latitude:.6f}"
        lng_str = f"{message.location.longitude:.6f}"
        acc_str = f"{int(round(message.location.horizontal_accuracy or 15.0))}"
        await state.clear()
        await save_location_profile(message.chat.id, p_key, lat_str, lng_str, acc_str)
        maps_url = f"https://www.google.com/maps?q={lat_str},{lng_str}"
        await message.answer(
            f"✅ <b>Lokasi GPS Berhasil Diperbarui!</b>\n\n"
            f"📍 Koordinat: <a href=\"{maps_url}\"><code>{lat_str}, {lng_str}</code></a> (±{acc_str}m)",
            parse_mode="HTML",
            reply_markup=get_back_to_logbook_keyboard()
        )
        return

    # 2. Jika via teks
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pengaturan lokasi dibatalkan.")
        return

    parsed = parse_coordinates_input(message.text)
    if not parsed:
        await message.answer("❌ Format koordinat tidak dikenali. Masukkan contoh: <code>-7.9467, 112.6156</code>", parse_mode="HTML")
        return

    lat, lng, acc = parsed
    lat_str = f"{lat:.6f}"
    lng_str = f"{lng:.6f}"
    acc_str = f"{int(round(acc))}"

    await state.clear()
    await save_location_profile(message.chat.id, p_key, lat_str, lng_str, acc_str)
    maps_url = f"https://www.google.com/maps?q={lat_str},{lng_str}"
    await message.answer(
        f"✅ <b>Lokasi GPS Berhasil Diperbarui!</b>\n\n"
        f"📍 Koordinat: <a href=\"{maps_url}\"><code>{lat_str}, {lng_str}</code></a> (±{acc_str}m)",
        parse_mode="HTML",
        reply_markup=get_back_to_logbook_keyboard()
    )


# --- DRAF AKSI (PERSETUJUAN & PENGIRIMAN KE DERMAGA) ---

@router.callback_query(F.data.startswith("log_confirm_"))
async def cb_confirm_draft(callback: CallbackQuery) -> None:
    """Menyetujui dan mengirim draf logbook ke portal DERMAGA."""
    await callback.answer()
    draft_id = int(callback.data.split("_")[2])
    draft = await get_draft(draft_id)

    if not draft:
        if callback.message:
            await callback.message.answer("❌ Draf tidak ditemukan.")
        return

    if callback.message:
        await callback.message.edit_text("⏳ <i>Sedang mengirimkan logbook dan absensi ke DERMAGA...</i>", parse_mode="HTML")

    chat_id = callback.from_user.id
    date = draft["date"]
    summary = draft["summary"]
    jam_masuk = draft.get("jam_masuk", "07:10")
    jam_pulang = draft.get("jam_pulang", "16:25")
    prof_key = draft.get("selected_profile", "office")

    lat, lng, acc = await get_user_location(chat_id, prof_key)
    ok, msg = await submit_dermaga_entry(chat_id, date, summary, jam_masuk, jam_pulang, lat, lng, acc)

    if ok:
        await update_draft_status(draft_id, "submitted")
        await complete_reminder_for_today(chat_id, date)
        balasan = (
            f"🎉 <b>Logbook Berhasil Disubmit ke DERMAGA!</b>\n\n"
            f"📅 Tanggal: <code>{date}</code>\n"
            f"⏱ Jam: <code>{jam_masuk} - {jam_pulang}</code>\n"
            f"📍 Lokasi: <code>{lat}, {lng}</code> (±{acc}m)\n\n"
            f"✅ Absensi dan entri logbook telah tercatat aman di sistem kampus."
        )
    else:
        balasan = f"❌ <b>Gagal submit ke DERMAGA:</b>\n{msg}"

    if callback.message:
        await callback.message.answer(balasan, parse_mode="HTML", reply_markup=get_back_to_logbook_keyboard())


@router.callback_query(F.data.startswith("log_draft_loc_"))
async def cb_draft_toggle_location(callback: CallbackQuery) -> None:
    """Mengganti profil lokasi pengiriman pada draf."""
    await callback.answer()
    parts = callback.data.split("_")
    draft_id = int(parts[3])
    next_prof = parts[4]

    await update_draft_location_profile(draft_id, next_prof)
    draft = await get_draft(draft_id)

    if callback.message and draft:
        text = format_draft_message(draft, next_prof)
        markup = get_draft_approval_keyboard(draft_id, next_prof)
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass


@router.callback_query(F.data.startswith("log_cancel_"))
async def cb_cancel_draft(callback: CallbackQuery) -> None:
    """Membatalkan draf."""
    await callback.answer()
    draft_id = int(callback.data.split("_")[2])
    await update_draft_status(draft_id, "cancelled")
    if callback.message:
        await callback.message.edit_text("❌ Draf logbook dibatalkan.", reply_markup=get_back_to_logbook_keyboard())


@router.callback_query(F.data.startswith("log_edit_"))
async def cb_start_edit_draft_summary(callback: CallbackQuery, state: FSMContext) -> None:
    """Minta teks baru untuk merevisi ringkasan draf."""
    await callback.answer()
    draft_id = int(callback.data.split("_")[2])
    await state.set_state(LogbookEditSummaryFSM.waiting_for_summary)
    await state.update_data(edit_draft_id=draft_id)
    if callback.message:
        await callback.message.answer("Ketikkan teks ringkasan baru untuk logbook ini:")


@router.message(LogbookEditSummaryFSM.waiting_for_summary)
async def process_edit_draft_summary(message: Message, state: FSMContext) -> None:
    """Menerima dan memperbarui ringkasan draf."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Revisi dibatalkan.")
        return

    data = await state.get_data()
    draft_id = data.get("edit_draft_id")
    await state.clear()

    await update_draft_summary(draft_id, message.text.strip())
    draft = await get_draft(draft_id)
    if draft:
        text = format_draft_message(draft)
        markup = get_draft_approval_keyboard(draft_id, draft.get("selected_profile", "office"))
        await message.answer(
            "✅ <b>Ringkasan berhasil diperbarui!</b>\nBerikut draf yang siap dikonfirmasi ulang:\n\n" + text,
            parse_mode="HTML",
            reply_markup=markup
        )


# --- MANUAL ISI DARI PENGINGAT ---

@router.callback_query(F.data.startswith("log_remind_fill_"))
async def cb_remind_fill(callback: CallbackQuery, state: FSMContext) -> None:
    """Mulai input manual saat user mengklik 'Isi Logbook' pada pesan pengingat."""
    await callback.answer()
    target_date = callback.data.replace("log_remind_fill_", "")
    await state.set_state(LogbookManualFillFSM.waiting_for_text)
    await state.update_data(target_date=target_date)
    if callback.message:
        await callback.message.answer(
            f"✍️ <b>Input Logbook Tanggal {target_date}</b>\n\n"
            f"Silakan ketikkan deskripsi pekerjaan/aktivitas Anda hari ini:",
            parse_mode="HTML"
        )


@router.message(LogbookManualFillFSM.waiting_for_text)
async def process_manual_fill_text(message: Message, state: FSMContext) -> None:
    """Menerima teks aktivitas logbook manual dan membuat draf siap kirim."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pengisian logbook dibatalkan.")
        return

    data = await state.get_data()
    target_date = data.get("target_date", datetime.now().strftime("%Y-%m-%d"))
    await state.clear()

    chat_id = message.chat.id
    ts = int(time.time())
    idempotency_key = f"manual_{chat_id}_{target_date}_{ts}"

    draft, _ = await create_or_get_draft(
        chat_id=chat_id,
        idempotency_key=idempotency_key,
        date=target_date,
        projects=["Logbook Harian"],
        commits_summary=message.text.strip(),
        raw_metadata=[],
        jam_masuk="07:10",
        jam_pulang="16:25",
    )
    await complete_reminder_for_today(chat_id, target_date)

    text = format_draft_message(draft)
    markup = get_draft_approval_keyboard(draft["id"], draft.get("selected_profile", "office"))
    await message.answer(
        "✅ <b>Draf Logbook Berhasil Dibuat!</b>\n\n"
        "Silakan periksa dan lakukan konfirmasi untuk mengirim ke DERMAGA:\n\n" + text,
        parse_mode="HTML",
        reply_markup=markup
    )


@router.callback_query(F.data.startswith("log_remind_stop_"))
async def cb_remind_stop(callback: CallbackQuery) -> None:
    """Hentikan pengingat untuk hari ini."""
    await callback.answer()
    target_date = callback.data.replace("log_remind_stop_", "")
    await stop_reminder_for_today(callback.from_user.id, target_date)
    user_time = await get_user_reminder_time(callback.from_user.id)
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer(
            f"🔕 <b>Pengingat Dihentikan untuk Hari Ini</b>\n\n"
            f"Bot tidak akan mengirim pengingat logbook lagi untuk tanggal <code>{target_date}</code>.\n"
            f"Anda akan diingatkan kembali besok pada jam <b>{user_time} WIB</b>.",
            parse_mode="HTML"
        )


# --- HAPUS AKUN & ADMIN ---

@router.message(Command("hapus_akun_logbook", "hapus_akun"))
@router.callback_query(F.data == "log_menu_hapus")
async def cmd_hapus_akun_prompt(event: Message | CallbackQuery) -> None:
    """Prompt konfirmasi penghapusan akun."""
    target_msg = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ Ya, Hapus Akun Saya", callback_data="log_confirm_hapus_akun")],
        [InlineKeyboardButton(text="❌ Batal", callback_data="log_menu_back")],
    ])
    await target_msg.answer(
        "⚠️ <b>Konfirmasi Hapus Akun Logbook</b>\n\n"
        "Apakah Anda yakin ingin menghapus akun dan seluruh token CLI Anda dari sistem bot?",
        parse_mode="HTML",
        reply_markup=markup
    )


@router.callback_query(F.data == "log_confirm_hapus_akun")
async def cb_confirm_hapus_akun(callback: CallbackQuery) -> None:
    """Eksekusi hapus akun."""
    await callback.answer()
    await delete_user_credential(callback.from_user.id)
    if callback.message:
        await callback.message.edit_text("✅ Akun dan token CLI Anda berhasil dihapus dari sistem bot.")

