"""
Router Aiogram komprehensif untuk modul Logbook DERMAGA Polinema.
Menangani pendaftaran kredensial, draf CLI, persetujuan pengiriman ke DERMAGA, GPS lokasi, dan kalender.
"""

from datetime import datetime
import html
import json
import time
from typing import Any, Optional
from zoneinfo import ZoneInfo
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from app.bot.keyboards.logbook import (
    get_back_to_logbook_keyboard,
    get_draft_approval_keyboard,
    get_edit_detail_keyboard,
    get_locations_menu_keyboard,
    get_logbook_hub_keyboard,
    get_month_calendar_keyboard,
    get_reminder_days_checklist_keyboard,
    get_settings_menu_keyboard,
    get_verification_detail_keyboard,
    get_verification_weeks_keyboard,
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
    check_monitoring_today,
    fetch_dermaga_table,
    format_draft_message,
    format_month_name,
    format_reminder_days_display,
    format_short_date,
    get_cached_weeks_and_parties,
    group_entries_by_month,
    parse_coordinates_input,
    submit_dermaga_entry,
    test_dermaga_login,
    validate_time_format,
)

router = Router(name="logbook_router")


# --- FSM STATES ---

class LogbookManualFillFSM(StatesGroup):
    waiting_for_text = State()
    waiting_for_edit_text = State()


class LogbookEditSummaryFSM(StatesGroup):
    waiting_for_summary = State()


class LogbookSetJamFSM(StatesGroup):
    waiting_for_time = State()


class LogbookSetLocFSM(StatesGroup):
    waiting_for_location = State()


class LogbookEditPastFSM(StatesGroup):
    waiting_for_masuk = State()
    waiting_for_pulang = State()
    waiting_for_deskripsi = State()


# Sesi penyimpanan state in-memory untuk navigasi kalender dan edit entri lampau
_calendar_edit_sessions: dict[int, dict] = {}


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


# --- TOKEN & AKUN LOGBOOK ---

@router.message(Command("token_logbook"))
@router.callback_query(F.data.in_({"log_menu_token", "log_menu_account"}))
async def cmd_token_logbook(event: Message | CallbackQuery) -> None:
    """Menampilkan detail akun dan token API CLI logbook."""
    settings = get_settings()
    chat_id = event.chat.id if isinstance(event, Message) else event.from_user.id
    target_msg = event if isinstance(event, Message) else event.message

    if isinstance(event, CallbackQuery):
        await event.answer()

    user = await get_user_by_chat_id(chat_id)
    if not user:
        warn_text = "⚠️ Akun Anda belum terdaftar. Gunakan <code>/daftar_logbook</code> terlebih dahulu."
        if isinstance(event, CallbackQuery) and event.message:
            await event.message.edit_text(warn_text, parse_mode="HTML", reply_markup=get_back_to_logbook_keyboard())
        else:
            await target_msg.answer(warn_text, parse_mode="HTML")
        return

    token = user.get("api_token", "-")
    public_url = settings.LOGBOOK_PUBLIC_URL

    text = (
        f"🔑 <b>Akun & API Token CLI Logbook Anda</b>\n\n"
        f"👤 <b>Username:</b> <code>{user['username']}</code>\n"
        f"🔑 <b>API Token:</b>\n<code>{token}</code>\n\n"
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
        [InlineKeyboardButton(text="🗑 Hapus Akun & Data", callback_data="log_menu_hapus")],
        [InlineKeyboardButton(text="⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back")],
    ])
    if isinstance(event, CallbackQuery) and event.message:
        try:
            await event.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
            return
        except Exception:
            pass
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


# --- LINK VERIFIKASI PEMBIMBING & DOSEN ---

def render_verification_weeks_text(weeks_data: dict[str, Any]) -> str:
    """Menyusun teks HTML pengantar daftar kartu minggu untuk pengambilan link verifikasi."""
    pending = []
    completed = []
    for k, w in sorted(weeks_data.items(), reverse=True):
        v = w.get("verif")
        if not v:
            continue
        if v.get("link_supervisor") or v.get("link_dosen"):
            pending.append(w)
        elif v.get("pdf"):
            completed.append(w)

    text = "🔗 <b>Pusat Link Verifikasi Logbook DERMAGA</b>\n\n"
    if pending:
        text += (
            f"⏳ <b>{len(pending)} Minggu Menunggu Verifikasi:</b>\n"
            "Tautan siap dibagikan kepada Pembimbing Lapangan dan Dosen Pembimbing.\n\n"
        )
        for p in pending:
            text += f"• <b>{p.get('label', 'Minggu')}</b> (<code>{p.get('rentang', '-')}</code>)\n"
        text += "\n<i>Ketuk kartu minggu di bawah untuk mengambil dan menyalin link verifikasi:</i>"
    elif completed:
        text += (
            "✅ <b>Tidak ada minggu yang sedang menunggu verifikasi saat ini.</b>\n"
            "Semua minggu yang telah diajukan sudah selesai diverifikasi secara lengkap.\n\n"
            "<i>Anda dapat melihat riwayat minggu sebelumnya atau mengunduh PDF di bawah ini:</i>"
        )
    else:
        text += (
            "ℹ️ <b>Belum ada logbook mingguan yang diajukan untuk verifikasi.</b>\n\n"
            "<i>Setelah Anda menandatangani draf mingguan di portal DERMAGA, "
            "link verifikasi untuk Supervisor dan Dosen Pembimbing akan otomatis muncul di sini.</i>"
        )

    return text


def render_verification_detail_text(week_info: dict[str, Any], parties: dict[str, str]) -> str:
    """Menyusun teks HTML detail link verifikasi dan status tanda tangan kartu minggu terpilih."""
    label = week_info.get("label", "-")
    rentang = week_info.get("rentang", "-")
    verif = week_info.get("verif") or {}

    ttd_mhs = verif.get("mahasiswa")
    ttd_spv = verif.get("supervisor")
    ttd_dos = verif.get("dosen")
    link_spv = verif.get("link_supervisor")
    link_dos = verif.get("link_dosen")
    pdf_url = verif.get("pdf")

    spv_name = parties.get("supervisor", "Pembimbing Lapangan")
    dos_name = parties.get("dosen", "Dosen Pembimbing")

    status_mhs = f"✅ Ditandatangani ({ttd_mhs})" if ttd_mhs else "⏳ Belum ditandatangani"
    status_spv = f"✅ Ditandatangani ({ttd_spv})" if ttd_spv else "⏳ Menunggu verifikasi"
    status_dos = f"✅ Ditandatangani ({ttd_dos})" if ttd_dos else "⏳ Menunggu verifikasi"

    text = (
        f"🔗 <b>LINK VERIFIKASI LOGBOOK DERMAGA</b>\n"
        f"🏷 <b>Minggu:</b> <b>{label}</b> (<code>{rentang}</code>)\n\n"
        f"📋 <b>Status Tanda Tangan:</b>\n"
        f"• Mahasiswa: {status_mhs}\n"
        f"• Supervisor: {status_spv}\n"
        f"• Dosen: {status_dos}\n\n"
    )

    has_links = False
    if link_spv:
        has_links = True
        text += (
            f"👤 <b>{html.escape(spv_name)}</b>\n"
            f"🔗 <b>Link Verifikasi:</b>\n"
            f"<code>{link_spv}</code>\n\n"
        )
    elif ttd_spv:
        text += f"👤 <b>{html.escape(spv_name)}:</b> ✅ <i>Sudah diverifikasi ({ttd_spv})</i>\n\n"

    if link_dos:
        has_links = True
        text += (
            f"🎓 <b>{html.escape(dos_name)}</b>\n"
            f"🔗 <b>Link Verifikasi:</b>\n"
            f"<code>{link_dos}</code>\n\n"
        )
    elif ttd_dos:
        text += f"🎓 <b>{html.escape(dos_name)}:</b> ✅ <i>Sudah diverifikasi ({ttd_dos})</i>\n\n"

    if has_links:
        text += (
            "💡 <i>Ketuk link di atas untuk menyalin langsung. Bagikan link ini (mis. lewat WhatsApp/email). "
            "Penerima dapat menandatangani tanpa perlu login.</i>"
        )
    elif pdf_url:
        text += (
            f"🎉 <b>Logbook minggu ini telah selesai diverifikasi lengkap!</b>\n"
            f"📄 Berkas PDF resmi telah diterbitkan oleh DERMAGA:\n"
            f"<code>{pdf_url}</code>"
        )
    else:
        text += (
            "ℹ️ <i>Link verifikasi belum aktif atau belum diterbitkan. "
            "Pastikan Anda telah menandatangani logbook mingguan di portal DERMAGA terlebih dahulu.</i>"
        )

    return text


@router.message(Command("link_verif", "link_verifikasi"))
@router.callback_query(F.data.in_({"log_menu_link_verif", "log_verif_refresh"}))
async def cmd_link_verifikasi(event: Message | CallbackQuery) -> None:
    """Menampilkan daftar kartu minggu untuk mengambil link verifikasi Supervisor & Dosen."""
    chat_id = event.chat.id if isinstance(event, Message) else event.from_user.id
    target_msg = event if isinstance(event, Message) else event.message
    force_refresh = isinstance(event, CallbackQuery) and event.data == "log_verif_refresh"

    if isinstance(event, CallbackQuery):
        await event.answer("Memuat data verifikasi..." if not force_refresh else "Memperbarui data DERMAGA...")

    load_text = (
        "🔄 <i>Sedang memperbarui status verifikasi dari portal DERMAGA...</i>"
        if force_refresh
        else "⏳ <i>Mengambil data kartu verifikasi dari portal DERMAGA...</i>"
    )
    try:
        loading = await target_msg.answer(load_text, parse_mode="HTML")
    except Exception:
        loading = None

    try:
        weeks_data, parties = await get_cached_weeks_and_parties(chat_id, force_refresh=force_refresh)
        if not weeks_data:
            err_msg = "ℹ️ Tidak ada data kartu minggu yang ditemukan di portal DERMAGA."
            if loading:
                await loading.edit_text(err_msg, reply_markup=get_back_to_logbook_keyboard())
            else:
                await target_msg.answer(err_msg, reply_markup=get_back_to_logbook_keyboard())
            return

        text = render_verification_weeks_text(weeks_data)
        markup = get_verification_weeks_keyboard(weeks_data)
        if loading:
            await loading.edit_text(text, parse_mode="HTML", reply_markup=markup)
        else:
            await target_msg.answer(text, parse_mode="HTML", reply_markup=markup)
    except Exception as err:
        logger.error(f"[LOGBOOK-VERIF] Gagal memuat link verifikasi: {err}")
        err_msg = f"❌ Gagal mengambil status verifikasi DERMAGA: {err}"
        if loading:
            await loading.edit_text(err_msg, reply_markup=get_back_to_logbook_keyboard())
        else:
            await target_msg.answer(err_msg, reply_markup=get_back_to_logbook_keyboard())


@router.callback_query(F.data.startswith("log_verif_") & (F.data != "log_verif_refresh"))
async def cb_verif_week_detail(callback: CallbackQuery) -> None:
    """Menampilkan rincian link verifikasi untuk kartu minggu terpilih."""
    await callback.answer()
    if not callback.message:
        return

    awal = callback.data.split("log_verif_", 1)[1]
    if awal in {"refresh", "back"}:
        return

    chat_id = callback.from_user.id
    try:
        weeks_data, parties = await get_cached_weeks_and_parties(chat_id, force_refresh=False)
        week_info = weeks_data.get(awal)
        if not week_info:
            await callback.message.edit_text(
                "❌ Data minggu tidak ditemukan atau sesi telah berakhir. Silakan refresh kembali.",
                reply_markup=get_back_to_logbook_keyboard(),
            )
            return

        text = render_verification_detail_text(week_info, parties)
        markup = get_verification_detail_keyboard(week_info, parties)
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception as err:
        logger.error(f"[LOGBOOK-VERIF] Gagal memuat detail minggu {awal}: {err}")
        await callback.message.edit_text(
            f"❌ Terjadi kesalahan saat membaca data minggu: {err}",
            reply_markup=get_back_to_logbook_keyboard(),
        )


# --- KALENDER & EDIT LOGBOOK ---

def _render_edit_detail_text(session: dict) -> str:
    """Menyusun teks tampilan detail entri logbook yang sedang diedit."""
    orig = session.get("original", {})
    tgl = session.get("tanggal", "-")
    web_id = session.get("web_id", "-")
    masuk = session.get("jam_masuk", "07:10")
    pulang = session.get("jam_pulang", "16:25")
    desk = html.escape(session.get("deskripsi", "-"))

    masuk_badge = " <i>(diubah)</i>" if masuk != orig.get("jam_masuk") else ""
    pulang_badge = " <i>(diubah)</i>" if pulang != orig.get("jam_pulang") else ""
    desk_badge = " <i>(diubah)</i>" if session.get("deskripsi") != orig.get("deskripsi") else ""

    text = (
        f"📝 <b>Detail Logbook Terpilih</b>\n\n"
        f"🗓 <b>Tanggal:</b> <code>{tgl}</code> (ID: <code>#{web_id}</code>)\n"
        f"⏰ <b>Jam Masuk:</b> <code>{masuk}</code>{masuk_badge}\n"
        f"⏰ <b>Jam Pulang:</b> <code>{pulang}</code>{pulang_badge}\n"
        f"📋 <b>Pekerjaan / Aktivitas:</b>{desk_badge}\n"
        f"<blockquote>{desk}</blockquote>\n\n"
    )
    any_changed = bool(masuk_badge or pulang_badge or desk_badge)
    if any_changed:
        text += "💡 <i>Terdapat perubahan yang belum disimpan. Klik 'Simpan Perubahan' untuk mengonfirmasi ke DERMAGA.</i>"
    else:
        text += "<i>Pilih field di bawah jika Anda ingin mengubah jam kerja atau deskripsi pekerjaan:</i>"
    return text


async def _send_month_calendar_view(chat_id: int, target_message: Message, current_month: str) -> None:
    session = _calendar_edit_sessions.get(chat_id)
    if not session or not session.get("by_month"):
        text, markup = await render_hub_view(chat_id)
        try:
            await target_message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            await target_message.answer(text, parse_mode="HTML", reply_markup=markup)
        return

    month_name = format_month_name(current_month)
    month_entries = session["by_month"].get(current_month, [])
    markup = get_month_calendar_keyboard(current_month, session["months"], month_entries)

    text = (
        f"📅 <b>Pilih Tanggal Logbook untuk Diedit</b>\n\n"
        f"Bulan: <b>{month_name}</b> ({len(month_entries)} entri tercatat)\n\n"
        f"Silakan pilih tanggal yang ingin Anda ubah di bawah:"
    )
    try:
        await target_message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await target_message.answer(text, parse_mode="HTML", reply_markup=markup)


async def _send_edit_detail_view(chat_id: int, target_message: Message) -> None:
    session = _calendar_edit_sessions.get(chat_id)
    if not session or not session.get("web_id"):
        text, markup = await render_hub_view(chat_id)
        try:
            await target_message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            await target_message.answer(text, parse_mode="HTML", reply_markup=markup)
        return

    orig = session.get("original", {})
    any_changed = (
        session["jam_masuk"] != orig.get("jam_masuk")
        or session["jam_pulang"] != orig.get("jam_pulang")
        or session["deskripsi"] != orig.get("deskripsi")
    )
    text = _render_edit_detail_text(session)
    markup = get_edit_detail_keyboard(any_changed)
    try:
        await target_message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await target_message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data == "log_menu_edit")
async def cb_menu_edit(callback: CallbackQuery) -> None:
    """Membuka tampilan kalender dan entri logbook untuk diedit."""
    await callback.answer()
    chat_id = callback.from_user.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        if callback.message:
            await callback.message.edit_text(
                "⚠️ Akun DERMAGA Anda belum terdaftar. Gunakan <code>/daftar_logbook</code> terlebih dahulu.",
                parse_mode="HTML",
                reply_markup=get_back_to_logbook_keyboard()
            )
        return

    if callback.message:
        await callback.message.edit_text(
            "⏳ <i>Sedang mengambil riwayat logbook dari portal DERMAGA...</i>",
            parse_mode="HTML"
        )

    try:
        entries = await fetch_dermaga_table(chat_id)
        if not entries:
            if callback.message:
                await callback.message.edit_text(
                    f"ℹ️ Belum ada entri logbook yang tercatat di akun DERMAGA <code>{user['username']}</code> untuk diedit.",
                    parse_mode="HTML",
                    reply_markup=get_back_to_logbook_keyboard()
                )
            return

        grouped = group_entries_by_month(entries)
        months_list = sorted(grouped.keys(), reverse=True)
        current_month = months_list[0] if months_list else datetime.now().strftime("%Y-%m")

        _calendar_edit_sessions[chat_id] = {
            "all_entries": entries,
            "by_month": grouped,
            "months": months_list,
            "selected_month": current_month,
        }

        if callback.message:
            await _send_month_calendar_view(chat_id, callback.message, current_month)

    except Exception as err:
        logger.error(f"[LOGBOOK-CALENDAR] Gagal memuat entri kalender: {err}")
        if callback.message:
            await callback.message.edit_text(
                f"❌ Gagal mengambil data DERMAGA: {err}",
                reply_markup=get_back_to_logbook_keyboard()
            )


@router.callback_query(F.data.startswith("log_edmonth_"))
async def cb_calendar_change_month(callback: CallbackQuery) -> None:
    """Mengubah bulan pada tampilan kalender."""
    await callback.answer()
    chat_id = callback.from_user.id
    target_month = callback.data.split("_")[2]
    session = _calendar_edit_sessions.get(chat_id)
    if not session or not session.get("by_month"):
        if callback.message:
            text, markup = await render_hub_view(chat_id)
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        return

    session["selected_month"] = target_month
    if callback.message:
        await _send_month_calendar_view(chat_id, callback.message, target_month)


@router.callback_query(F.data.startswith("log_edpick_"))
async def cb_calendar_pick_entry(callback: CallbackQuery) -> None:
    """Memilih entri logbook tanggal tertentu untuk diedit."""
    await callback.answer()
    chat_id = callback.from_user.id
    web_id = callback.data.split("_")[2]
    session = _calendar_edit_sessions.get(chat_id)
    if not session or not session.get("all_entries"):
        if callback.message:
            await callback.message.answer("❌ Sesi edit telah berakhir. Silakan buka kembali menu /logbook.")
        return

    selected_entry = None
    for e in session["all_entries"]:
        if str(e.get("web_id")) == str(web_id):
            selected_entry = e
            break

    if not selected_entry:
        if callback.message:
            await callback.message.answer("❌ Entri logbook tidak ditemukan.")
        return

    session["web_id"] = str(selected_entry["web_id"])
    session["tanggal"] = str(selected_entry.get("tanggal_iso", "")) or str(selected_entry.get("tanggal_text", ""))
    session["jam_masuk"] = str(selected_entry.get("jam_masuk") or "07:10")
    session["jam_pulang"] = str(selected_entry.get("jam_pulang") or "16:25")
    session["deskripsi"] = str(selected_entry.get("pekerjaan") or "")
    session["keterangan"] = str(selected_entry.get("keterangan") or "hadir")
    session["original"] = {
        "jam_masuk": session["jam_masuk"],
        "jam_pulang": session["jam_pulang"],
        "deskripsi": session["deskripsi"],
    }

    if callback.message:
        await _send_edit_detail_view(chat_id, callback.message)


@router.callback_query(F.data == "log_edact_masuk")
async def cb_edact_masuk(callback: CallbackQuery, state: FSMContext) -> None:
    """Memicu pengubahan jam masuk entri lampau."""
    await callback.answer()
    chat_id = callback.from_user.id
    session = _calendar_edit_sessions.get(chat_id)
    if not session:
        if callback.message:
            await callback.message.answer("❌ Sesi edit telah berakhir.")
        return

    await state.set_state(LogbookEditPastFSM.waiting_for_masuk)
    text = (
        f"⏰ <b>Ubah Jam Masuk (Tanggal {session['tanggal']})</b>\n\n"
        f"Jam masuk saat ini: <code>{session['jam_masuk']}</code>\n"
        f"Silakan ketik jam masuk baru (Format 24 jam <code>HH:MM</code>, contoh: <code>07:15</code>):"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal Ubah Jam", callback_data="log_edact_reedit")]
    ])
    if callback.message:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)


@router.message(LogbookEditPastFSM.waiting_for_masuk)
async def process_edit_masuk_input(message: Message, state: FSMContext) -> None:
    """Menerima input jam masuk baru untuk entri lampau."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pengubahan jam masuk dibatalkan.")
        return

    val = message.text.strip()
    if not validate_time_format(val):
        await message.answer("❌ Format tidak valid. Harap gunakan format 24 jam <code>HH:MM</code> (contoh: 07:15):", parse_mode="HTML")
        return

    h, m = val.split(":")
    norm_val = f"{int(h):02d}:{int(m):02d}"
    await state.clear()

    session = _calendar_edit_sessions.get(message.chat.id)
    if session:
        session["jam_masuk"] = norm_val
        await _send_edit_detail_view(message.chat.id, message)
    else:
        await message.answer("❌ Sesi edit telah berakhir. Silakan buka menu /logbook.")


@router.callback_query(F.data == "log_edact_pulang")
async def cb_edact_pulang(callback: CallbackQuery, state: FSMContext) -> None:
    """Memicu pengubahan jam pulang entri lampau."""
    await callback.answer()
    chat_id = callback.from_user.id
    session = _calendar_edit_sessions.get(chat_id)
    if not session:
        if callback.message:
            await callback.message.answer("❌ Sesi edit telah berakhir.")
        return

    await state.set_state(LogbookEditPastFSM.waiting_for_pulang)
    text = (
        f"⏰ <b>Ubah Jam Pulang (Tanggal {session['tanggal']})</b>\n\n"
        f"Jam pulang saat ini: <code>{session['jam_pulang']}</code>\n"
        f"Silakan ketik jam pulang baru (Format 24 jam <code>HH:MM</code>, contoh: <code>16:30</code>):"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal Ubah Jam", callback_data="log_edact_reedit")]
    ])
    if callback.message:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)


@router.message(LogbookEditPastFSM.waiting_for_pulang)
async def process_edit_pulang_input(message: Message, state: FSMContext) -> None:
    """Menerima input jam pulang baru untuk entri lampau."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pengubahan jam pulang dibatalkan.")
        return

    val = message.text.strip()
    if not validate_time_format(val):
        await message.answer("❌ Format tidak valid. Harap gunakan format 24 jam <code>HH:MM</code> (contoh: 16:30):", parse_mode="HTML")
        return

    h, m = val.split(":")
    norm_val = f"{int(h):02d}:{int(m):02d}"
    await state.clear()

    session = _calendar_edit_sessions.get(message.chat.id)
    if session:
        session["jam_pulang"] = norm_val
        await _send_edit_detail_view(message.chat.id, message)
    else:
        await message.answer("❌ Sesi edit telah berakhir. Silakan buka menu /logbook.")


@router.callback_query(F.data == "log_edact_desk")
async def cb_edact_desk(callback: CallbackQuery, state: FSMContext) -> None:
    """Memicu pengubahan deskripsi pekerjaan entri lampau."""
    await callback.answer()
    chat_id = callback.from_user.id
    session = _calendar_edit_sessions.get(chat_id)
    if not session:
        if callback.message:
            await callback.message.answer("❌ Sesi edit telah berakhir.")
        return

    await state.set_state(LogbookEditPastFSM.waiting_for_deskripsi)
    text = (
        f"📝 <b>Ubah Deskripsi Pekerjaan (Tanggal {session['tanggal']})</b>\n\n"
        f"Deskripsi saat ini:\n<blockquote>{html.escape(session['deskripsi'])}</blockquote>\n\n"
        f"Silakan ketikkan teks deskripsi pekerjaan baru yang ingin disimpan:"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal Ubah Deskripsi", callback_data="log_edact_reedit")]
    ])
    if callback.message:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)


@router.message(LogbookEditPastFSM.waiting_for_deskripsi)
async def process_edit_deskripsi_input(message: Message, state: FSMContext) -> None:
    """Menerima input deskripsi pekerjaan baru untuk entri lampau."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pengubahan deskripsi dibatalkan.")
        return

    val = message.text.strip()
    await state.clear()

    session = _calendar_edit_sessions.get(message.chat.id)
    if session:
        session["deskripsi"] = val
        await _send_edit_detail_view(message.chat.id, message)
    else:
        await message.answer("❌ Sesi edit telah berakhir. Silakan buka menu /logbook.")


@router.callback_query(F.data == "log_edact_save")
async def cb_edact_save(callback: CallbackQuery) -> None:
    """Menampilkan konfirmasi sebelum menyimpan perubahan ke DERMAGA."""
    chat_id = callback.from_user.id
    session = _calendar_edit_sessions.get(chat_id)
    if not session or not session.get("web_id"):
        await callback.answer("❌ Sesi edit tidak ditemukan.", show_alert=True)
        return

    orig = session.get("original", {})
    masuk_changed = (session["jam_masuk"] != orig.get("jam_masuk"))
    pulang_changed = (session["jam_pulang"] != orig.get("jam_pulang"))
    desk_changed = (session["deskripsi"] != orig.get("deskripsi"))
    if not (masuk_changed or pulang_changed or desk_changed):
        await callback.answer("Belum ada perubahan data yang dilakukan.", show_alert=True)
        return

    await callback.answer()
    tgl = session.get("tanggal", "-")
    web_id = session.get("web_id", "-")
    masuk = session.get("jam_masuk", "07:10")
    pulang = session.get("jam_pulang", "16:25")
    desk = html.escape(session.get("deskripsi", "-"))

    confirm_text = (
        f"📖 <b>Konfirmasi Perubahan Logbook DERMAGA</b>\n\n"
        f"🗓 <b>Tanggal:</b> <code>{tgl}</code> (ID: <code>#{web_id}</code>)\n"
        f"⏰ <b>Jam Kerja:</b> <code>{masuk} - {pulang} WIB</code>\n\n"
        f"📝 <b>Ringkasan Aktivitas Terbaru:</b>\n"
        f"<blockquote>{desk}</blockquote>\n\n"
        f"Silakan konfirmasi untuk memperbarui data pada portal DERMAGA:"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Konfirmasi Simpan", callback_data="log_edact_confirmsave")],
        [InlineKeyboardButton(text="✏️ Ubah Kembali", callback_data="log_edact_reedit")],
        [InlineKeyboardButton(text="❌ Batal", callback_data="log_edact_cancel")],
    ])
    if callback.message:
        await callback.message.edit_text(confirm_text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data == "log_edact_confirmsave")
async def cb_edact_confirmsave(callback: CallbackQuery) -> None:
    """Mengeksekusi penyimpanan update entri logbook lampau ke DERMAGA."""
    await callback.answer()
    chat_id = callback.from_user.id
    session = _calendar_edit_sessions.pop(chat_id, None)
    if not session or not session.get("web_id"):
        if callback.message:
            await callback.message.answer("❌ Sesi edit telah kadaluarsa.")
        return

    if callback.message:
        await callback.message.edit_text(
            f"⏳ <i>Sedang memperbarui logbook tanggal <code>{session['tanggal']}</code> (ID: #{session['web_id']}) di DERMAGA...</i>",
            parse_mode="HTML"
        )

    lat, lng, acc = await get_user_location(chat_id)
    ok, msg = await submit_dermaga_entry(
        chat_id=chat_id,
        date=session["tanggal"],
        summary=session["deskripsi"],
        jam_masuk=session["jam_masuk"],
        jam_pulang=session["jam_pulang"],
        lat=lat,
        lng=lng,
        accuracy=acc,
        override_id=session["web_id"],
    )

    if ok:
        balasan = (
            f"🎉 <b>Logbook Berhasil Diperbarui!</b>\n\n"
            f"🗓 Tanggal: <code>{session['tanggal']}</code> (ID: <code>#{session['web_id']}</code>)\n"
            f"⏰ Jam: <code>{session['jam_masuk']} - {session['jam_pulang']} WIB</code>\n\n"
            f"📝 Data di portal DERMAGA telah terverifikasi berhasil diperbarui."
        )
    else:
        balasan = f"❌ <b>Gagal Memperbarui Logbook:</b>\n{msg}"

    if callback.message:
        await callback.message.answer(balasan, parse_mode="HTML", reply_markup=get_back_to_logbook_keyboard())


@router.callback_query(F.data == "log_edact_reedit")
async def cb_edact_reedit(callback: CallbackQuery) -> None:
    """Kembali ke tampilan detail edit entri."""
    await callback.answer()
    if callback.message:
        await _send_edit_detail_view(callback.from_user.id, callback.message)


@router.callback_query(F.data == "log_edact_backmonth")
async def cb_edact_backmonth(callback: CallbackQuery) -> None:
    """Kembali ke pemilihan tanggal kalender bulan terpilih."""
    await callback.answer()
    chat_id = callback.from_user.id
    session = _calendar_edit_sessions.get(chat_id)
    if not session or not session.get("selected_month"):
        if callback.message:
            text, markup = await render_hub_view(chat_id)
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        return

    if callback.message:
        await _send_month_calendar_view(chat_id, callback.message, session["selected_month"])


@router.callback_query(F.data == "log_edact_cancel")
async def cb_edact_cancel(callback: CallbackQuery) -> None:
    """Membatalkan sesi edit entri lampau dan kembali ke menu utama logbook."""
    await callback.answer()
    _calendar_edit_sessions.pop(callback.from_user.id, None)
    if callback.message:
        text, markup = await render_hub_view(callback.from_user.id)
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)


# --- PENGATURAN LOGBOOK ---

@router.callback_query(F.data == "log_menu_settings")
async def cb_menu_settings(callback: CallbackQuery) -> None:
    """Menampilkan menu pengaturan pengingat jam dan hari logbook."""
    await callback.answer()
    chat_id = callback.from_user.id
    user_time = await get_user_reminder_time(chat_id)
    user_days = await get_user_reminder_days(chat_id)
    days_disp = format_reminder_days_display(user_days)

    text = (
        "⚙️ <b>Pengaturan Pengingat Logbook</b>\n\n"
        f"⏰ <b>Jam Pengingat:</b> <code>{user_time} WIB</code>\n"
        f"🗓 <b>Hari Aktif:</b> <b>{days_disp}</b>\n\n"
        "Pilih pengaturan yang ingin Anda ubah:"
    )
    markup = get_settings_menu_keyboard()
    if callback.message:
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
            return
        except Exception:
            pass
        await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)


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

    # Ambil override_id jika draf ini merupakan draf edit
    override_id = None
    if draft.get("raw_metadata"):
        try:
            raw = draft["raw_metadata"]
            meta = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(meta, dict):
                override_id = meta.get("override_id")
            elif isinstance(meta, list) and meta and isinstance(meta[0], dict):
                override_id = meta[0].get("override_id")
        except Exception:
            pass

    lat, lng, acc = await get_user_location(chat_id, prof_key)
    ok, msg = await submit_dermaga_entry(
        chat_id=chat_id,
        date=date,
        summary=summary,
        jam_masuk=jam_masuk,
        jam_pulang=jam_pulang,
        lat=lat,
        lng=lng,
        accuracy=acc,
        override_id=override_id,
    )

    if ok:
        await update_draft_status(draft_id, "submitted")
        await complete_reminder_for_today(chat_id, date)
        action_title = "Diperbarui (Timpa)" if override_id else "Disubmit"
        balasan = (
            f"🎉 <b>Logbook Berhasil {action_title} ke DERMAGA!</b>\n\n"
            f"📅 Tanggal: <code>{date}</code>\n"
            f"⏱ Jam: <code>{jam_masuk} - {jam_pulang} WIB</code>\n"
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


# --- PENGISIAN & EDIT LOGBOOK HARI INI ---

async def _trigger_isi_logbook(chat_id: int, target_message: Message, state: FSMContext) -> None:
    """Logika alur pengisian logbook hari ini: cek DERMAGA, konfirmasi edit jika sudah ada, atau buat baru."""
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await target_message.answer(
            "⚠️ <b>Akun Belum Terdaftar!</b>\n\n"
            "Anda belum menghubungkan akun DERMAGA ke bot ini.\n"
            "Gunakan perintah:\n"
            "<code>/daftar_logbook <username> <password></code>",
            parse_mode="HTML"
        )
        return

    settings = get_settings()
    tz = ZoneInfo(settings.TIMEZONE)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")

    status_msg = await target_message.answer(
        f"⏳ <i>Memeriksa status logbook hari ini (<code>{today_str}</code>) di portal DERMAGA...</i>",
        parse_mode="HTML"
    )

    result = await check_monitoring_today(chat_id, today_str)

    if result.get("exists") and result.get("entry"):
        entry = result["entry"]
        web_id = entry.get("web_id", "-")
        masuk = entry.get("masuk", "07:10")
        pulang = entry.get("pulang", "16:25")
        deskripsi = html.escape(entry.get("deskripsi") or "-")

        confirm_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ Ya, Edit Logbook Hari Ini",
                        callback_data=f"log_isi_edit_{web_id}",
                    )
                ],
                [
                    InlineKeyboardButton(text="❌ Batal", callback_data="log_menu_back")
                ]
            ]
        )

        teks_konfirmasi = (
            f"⚠️ <b>Logbook Hari Ini Sudah Terisi!</b>\n\n"
            f"Entri tanggal <code>{today_str}</code> sudah tercatat di sistem DERMAGA.\n\n"
            f"🆔 <b>ID Entri:</b> <code>#{web_id}</code>\n"
            f"⏱ <b>Jam Kerja:</b> <code>{masuk} - {pulang} WIB</code>\n"
            f"📋 <b>Aktivitas Saat Ini:</b>\n"
            f"<blockquote>{deskripsi}</blockquote>\n\n"
            f"Apakah Anda ingin mengedit / memperbarui logbook hari ini?"
        )
        await status_msg.edit_text(teks_konfirmasi, parse_mode="HTML", reply_markup=confirm_markup)

    else:
        await state.set_state(LogbookManualFillFSM.waiting_for_text)
        await state.update_data(target_date=today_str, is_edit=False, override_id=None)

        prompt_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Batal", callback_data="log_menu_back")]
            ]
        )
        prompt_text = (
            f"✍️ <b>Pengisian Logbook Hari Ini</b>\n"
            f"📅 Tanggal: <code>{today_str}</code>\n\n"
            f"Silakan ketikkan deskripsi pekerjaan / aktivitas Anda hari ini:\n"
            f"<i>(Ketik pesan biasa di chat ini atau klik Batal)</i>"
        )
        await status_msg.edit_text(prompt_text, parse_mode="HTML", reply_markup=prompt_markup)


@router.message(Command("isi_logbook"))
async def cmd_isi_logbook(message: Message, state: FSMContext) -> None:
    """Command /isi_logbook untuk mengisi atau mengedit logbook hari ini."""
    await _trigger_isi_logbook(message.chat.id, message, state)


@router.callback_query(F.data == "log_menu_isi")
async def cb_menu_isi(callback: CallbackQuery, state: FSMContext) -> None:
    """Tombol Isi Logbook di menu utama."""
    await callback.answer()
    if callback.message:
        await _trigger_isi_logbook(callback.from_user.id, callback.message, state)


@router.callback_query(F.data.startswith("log_isi_edit_"))
async def cb_isi_edit_today(callback: CallbackQuery, state: FSMContext) -> None:
    """Konfirmasi user memilih 'Ya, Edit Logbook Hari Ini'."""
    await callback.answer()
    web_id = callback.data.replace("log_isi_edit_", "")
    settings = get_settings()
    tz = ZoneInfo(settings.TIMEZONE)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")

    await state.set_state(LogbookManualFillFSM.waiting_for_edit_text)
    await state.update_data(target_date=today_str, is_edit=True, override_id=web_id)

    prompt_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Batal", callback_data="log_menu_back")]
        ]
    )
    prompt_text = (
        f"✏️ <b>Edit Logbook Hari Ini (<code>{today_str}</code>)</b>\n"
        f"🆔 ID Entri: <code>#{web_id}</code>\n\n"
        f"Silakan ketikkan deskripsi pekerjaan / aktivitas baru untuk menimpa entri lama:\n"
        f"<i>(Ketik pesan biasa di chat ini atau klik Batal)</i>"
    )
    if callback.message:
        await callback.message.edit_text(prompt_text, parse_mode="HTML", reply_markup=prompt_markup)


# --- MANUAL ISI DARI PENGINGAT ---

@router.callback_query(F.data.startswith("log_remind_fill_"))
async def cb_remind_fill(callback: CallbackQuery, state: FSMContext) -> None:
    """Mulai input saat user mengklik 'Isi Logbook' pada pesan pengingat."""
    await callback.answer()
    if callback.message:
        await _trigger_isi_logbook(callback.from_user.id, callback.message, state)


@router.message(LogbookManualFillFSM.waiting_for_text)
@router.message(LogbookManualFillFSM.waiting_for_edit_text)
async def process_manual_fill_text(message: Message, state: FSMContext) -> None:
    """Menerima teks aktivitas logbook (baru maupun edit) dan membuat draf siap kirim."""
    if not message.text or message.text.startswith("/"):
        if message.text and message.text.strip().lower() == "/cancel":
            await state.clear()
            await message.answer("❌ Pengisian logbook dibatalkan.", reply_markup=get_back_to_logbook_keyboard())
            return
        await state.clear()
        return

    data = await state.get_data()
    settings = get_settings()
    tz = ZoneInfo(settings.TIMEZONE)
    default_today = datetime.now(tz).strftime("%Y-%m-%d")
    target_date = data.get("target_date", default_today)
    is_edit = data.get("is_edit", False)
    override_id = data.get("override_id")
    await state.clear()

    chat_id = message.chat.id
    ts = int(time.time())
    idempotency_key = f"manual_{chat_id}_{target_date}_{ts}"

    raw_meta = [{"override_id": override_id}] if override_id else []

    draft, _ = await create_or_get_draft(
        chat_id=chat_id,
        idempotency_key=idempotency_key,
        date=target_date,
        projects=["Logbook Harian"],
        commits_summary=message.text.strip(),
        raw_metadata=raw_meta,
        jam_masuk="07:10",
        jam_pulang="16:25",
    )
    await complete_reminder_for_today(chat_id, target_date)

    text = format_draft_message(draft)
    markup = get_draft_approval_keyboard(draft["id"], draft.get("selected_profile", "office"))
    header = "🔄 <b>Draf Edit Logbook Berhasil Disiapkan!</b>\n\n" if is_edit else "✅ <b>Draf Logbook Berhasil Dibuat!</b>\n\n"
    await message.answer(
        f"{header}Silakan periksa detailnya dan klik tombol di bawah untuk mengirim ke DERMAGA:\n\n" + text,
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


@router.callback_query(F.data.startswith("log_stop_week_"))
async def cb_stop_weekly_reminder(callback: CallbackQuery) -> None:
    """Menghentikan pengingat tanda tangan logbook untuk minggu tertentu."""
    await callback.answer()
    week_start = callback.data.replace("log_stop_week_", "")
    chat_id = callback.from_user.id

    from app.database.logbook_repo import get_weekly_reminder_state, stop_weekly_reminder
    await stop_weekly_reminder(chat_id, week_start)
    state = await get_weekly_reminder_state(chat_id, week_start)
    week_lbl = state.get("week_label") if state and state.get("week_label") else week_start

    if callback.message:
        await callback.message.answer(
            f"🔕 <b>Pengingat Dihentikan</b>\n\n"
            f"Bot tidak akan mengingatkan pengajuan tanda tangan untuk <b>{week_lbl}</b> lagi.",
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

