"""
Sub-router Logbook untuk memuat riwayat DERMAGA dan navigasi kalender bulanan.
"""

from datetime import datetime, timedelta
import html
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from app.bot.handlers.logbook_modules.account import render_hub_view
from app.bot.handlers.logbook_modules.shared import edit_or_answer
from app.bot.handlers.logbook_modules.views import render_edit_detail_text
from app.bot.keyboards.logbook import (
    get_back_to_logbook_keyboard,
    get_edit_detail_keyboard,
    get_month_calendar_keyboard,
)
from app.core.logger import logger
from app.database.logbook_repo import get_user_by_chat_id, set_placeholder_snooze
from app.services.logbook_service import fetch_dermaga_table, format_month_name, group_entries_by_month

router = Router(name="logbook_calendar_nav_router")

# Sesi penyimpanan state in-memory per user untuk navigasi kalender dan edit entri lampau
_calendar_edit_sessions: dict[int, dict] = {}


async def _send_month_calendar_view(
    chat_id: int,
    target_message: Message,
    current_month: str,
    is_admin: bool = False,
) -> None:
    """Menampilkan grid tanggal untuk bulan terpilih atau kembali ke hub bila sesi habis."""
    session = _calendar_edit_sessions.get(chat_id)
    if not session or not session.get("by_month") or not current_month:
        text, markup = await render_hub_view(chat_id, is_admin)
        await edit_or_answer(target_message, text, reply_markup=markup)
        return

    month_name = format_month_name(current_month)
    month_entries = session["by_month"].get(current_month, [])
    markup = get_month_calendar_keyboard(current_month, session["months"], month_entries)
    text = (
        f"📅 <b>Pilih Tanggal Logbook untuk Diedit</b>\n\n"
        f"Bulan: <b>{month_name}</b> ({len(month_entries)} entri tercatat)\n\n"
        "Silakan pilih tanggal yang ingin Anda ubah di bawah:"
    )
    await edit_or_answer(target_message, text, reply_markup=markup)


async def _send_edit_detail_view(
    chat_id: int,
    target_message: Message,
    is_admin: bool = False,
) -> None:
    """Menampilkan rincian field entri yang sedang diedit."""
    session = _calendar_edit_sessions.get(chat_id)
    if not session or not session.get("web_id"):
        text, markup = await render_hub_view(chat_id, is_admin)
        await edit_or_answer(target_message, text, reply_markup=markup)
        return

    orig = session.get("original", {})
    any_changed = any(
        session.get(field) != orig.get(field)
        for field in ("jam_masuk", "jam_pulang", "deskripsi")
    )
    await edit_or_answer(
        target_message,
        render_edit_detail_text(session),
        reply_markup=get_edit_detail_keyboard(any_changed),
    )


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
                reply_markup=get_back_to_logbook_keyboard(),
            )
        return

    if callback.message:
        await callback.message.edit_text(
            "⏳ <i>Sedang mengambil riwayat logbook dari portal DERMAGA...</i>",
            parse_mode="HTML",
        )

    try:
        entries = await fetch_dermaga_table(chat_id)
        if not entries:
            if callback.message:
                await callback.message.edit_text(
                    f"ℹ️ Belum ada entri logbook yang tercatat di akun DERMAGA <code>{html.escape(str(user['username']))}</code> untuk diedit.",
                    parse_mode="HTML",
                    reply_markup=get_back_to_logbook_keyboard(),
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
                reply_markup=get_back_to_logbook_keyboard(),
            )


@router.callback_query(F.data.startswith("log_edmonth_"))
async def cb_calendar_change_month(callback: CallbackQuery, is_admin: bool = False) -> None:
    """Mengubah bulan pada tampilan kalender."""
    await callback.answer()
    chat_id = callback.from_user.id
    target_month = callback.data.split("_")[2]
    session = _calendar_edit_sessions.get(chat_id)
    if not session or not session.get("by_month"):
        if callback.message:
            text, markup = await render_hub_view(chat_id, is_admin)
            await edit_or_answer(callback.message, text, reply_markup=markup)
        return

    session["selected_month"] = target_month
    if callback.message:
        await _send_month_calendar_view(chat_id, callback.message, target_month, is_admin)


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

    selected_entry = next(
        (e for e in session["all_entries"] if str(e.get("web_id")) == str(web_id)),
        None,
    )
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


@router.callback_query(F.data.startswith("log_eddirect_"))
async def cb_calendar_direct_edit(callback: CallbackQuery) -> None:
    """Membuka sesi edit langsung untuk tanggal/web_id tertentu dari notifikasi pengingat."""
    await callback.answer()
    chat_id = callback.from_user.id
    target = callback.data.removeprefix("log_eddirect_")

    if callback.message:
        await callback.message.edit_text("⏳ <i>Sedang memuat entri logbook dari DERMAGA...</i>", parse_mode="HTML")

    try:
        entries = await fetch_dermaga_table(chat_id)
        if not entries:
            if callback.message:
                await callback.message.edit_text(
                    "❌ Tidak ditemukan entri logbook di DERMAGA.",
                    reply_markup=get_back_to_logbook_keyboard(),
                )
            return

        selected_entry = None
        for e in entries:
            if str(e.get("web_id")) == target or e.get("tanggal_iso") == target or target in str(e.get("tanggal_text", "")):
                selected_entry = e
                break

        if not selected_entry:
            # Fallback ke entri paling atas jika target spesifik tidak ditemukan
            selected_entry = entries[0]

        grouped = group_entries_by_month(entries)
        months_list = sorted(grouped.keys(), reverse=True)
        tgl_iso = str(selected_entry.get("tanggal_iso", ""))
        current_month = tgl_iso[:7] if len(tgl_iso) >= 7 else (months_list[0] if months_list else datetime.now().strftime("%Y-%m"))

        _calendar_edit_sessions[chat_id] = {
            "all_entries": entries,
            "by_month": grouped,
            "months": months_list,
            "selected_month": current_month,
            "web_id": str(selected_entry.get("web_id") or ""),
            "tanggal": str(selected_entry.get("tanggal_iso", "")) or str(selected_entry.get("tanggal_text", "")),
            "jam_masuk": str(selected_entry.get("jam_masuk") or "07:10"),
            "jam_pulang": str(selected_entry.get("jam_pulang") or "16:25"),
            "deskripsi": str(selected_entry.get("pekerjaan") or ""),
            "keterangan": str(selected_entry.get("keterangan") or "hadir"),
            "original": {
                "jam_masuk": str(selected_entry.get("jam_masuk") or "07:10"),
                "jam_pulang": str(selected_entry.get("jam_pulang") or "16:25"),
                "deskripsi": str(selected_entry.get("pekerjaan") or ""),
            },
        }

        if callback.message:
            await _send_edit_detail_view(chat_id, callback.message)

    except Exception as e:
        logger.error(f"[LOGBOOK-DIRECT-EDIT] Gagal memuat entri direct edit untuk {chat_id}: {e}")
        if callback.message:
            await callback.message.edit_text(
                f"❌ Gagal memuat data DERMAGA: {e}",
                reply_markup=get_back_to_logbook_keyboard(),
            )


@router.callback_query(F.data == "log_snooze_placeholder")
async def cb_snooze_placeholder(callback: CallbackQuery) -> None:
    """Menunda pengingat entri placeholder '-' selama 2 jam."""
    await callback.answer()
    chat_id = callback.from_user.id
    now = datetime.now()
    snooze_until = (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    await set_placeholder_snooze(chat_id, snooze_until)

    text = (
        "🔕 <b>Pengingat Ditunda</b>\n\n"
        "Pengingat entri logbook <code>-</code> berhasil ditunda selama <b>2 jam</b>.\n"
        "Bot akan mengingatkan kembali jika logbook belum diperbarui setelah waktu tunda berakhir."
    )
    if callback.message:
        await callback.message.edit_text(text, parse_mode="HTML")

