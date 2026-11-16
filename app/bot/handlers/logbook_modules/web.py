"""
Sub-router Logbook untuk melihat tabel entri DERMAGA dan mengambil link verifikasi mingguan.
"""

import html
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from app.bot.handlers.logbook_modules.shared import unpack_event
from app.bot.handlers.logbook_modules.views import (
    render_verification_detail_text,
    render_verification_weeks_text,
)
from app.bot.keyboards.logbook import (
    get_back_to_logbook_keyboard,
    get_verification_detail_keyboard,
    get_verification_weeks_keyboard,
)
from app.core.logger import logger
from app.services.logbook_service import fetch_dermaga_table, get_cached_weeks_and_parties

router = Router(name="logbook_web_router")


# --- CEK TABEL DERMAGA ---

@router.message(Command("cek_logbook"))
@router.callback_query(F.data == "log_menu_cek")
async def cmd_cek_logbook(event: Message | CallbackQuery) -> None:
    """Mengambil live table logbook dari web DERMAGA."""
    chat_id, target_msg = await unpack_event(event)
    if not target_msg:
        return

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
                f"📅 <b>{html.escape(str(e['tanggal_text']))}</b> (ID: <code>#{html.escape(str(e['web_id'] or '-'))}</code>)\n"
                f"⏱️ <code>{html.escape(str(e['jam']))}</code> | Ket: <b>{html.escape(str(e['keterangan']))}</b> | Status: <b>{html.escape(str(e['status_verif']))}</b>\n"
                f"📝 <i>{desc}</i>\n\n"
            )
        if len(entries) > 10:
            text += f"<i>...dan {len(entries) - 10} entri lainnya di DERMAGA.</i>"

        await loading.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception as err:
        await loading.edit_text(f"❌ Gagal mengambil data DERMAGA: {err}", reply_markup=get_back_to_logbook_keyboard())


# --- LINK VERIFIKASI PEMBIMBING & DOSEN ---

@router.message(Command("link_verif", "link_verifikasi"))
@router.callback_query(F.data.in_({"log_menu_link_verif", "log_verif_refresh"}))
async def cmd_link_verifikasi(event: Message | CallbackQuery) -> None:
    """Menampilkan daftar kartu minggu untuk mengambil link verifikasi Supervisor & Dosen."""
    chat_id = event.chat.id if isinstance(event, Message) else event.from_user.id
    target_msg = event if isinstance(event, Message) else event.message
    force_refresh = isinstance(event, CallbackQuery) and event.data == "log_verif_refresh"

    if isinstance(event, CallbackQuery):
        await event.answer("Memperbarui data DERMAGA..." if force_refresh else "Memuat data verifikasi...")
    if not target_msg:
        return

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
        weeks_data, _ = await get_cached_weeks_and_parties(chat_id, force_refresh=force_refresh)
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
