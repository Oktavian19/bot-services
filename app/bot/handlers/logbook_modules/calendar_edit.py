"""
Sub-router Logbook untuk mengubah field entri kalender lampau dan menyimpannya ke DERMAGA.
"""

import html
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from app.bot.handlers.logbook_modules.account import render_hub_view
from app.bot.handlers.logbook_modules.calendar_nav import (
    _calendar_edit_sessions,
    _send_edit_detail_view,
    _send_month_calendar_view,
)
from app.bot.handlers.logbook_modules.shared import (
    LogbookEditPastFSM,
    edit_or_answer,
    normalize_time_hhmm,
)
from app.bot.handlers.logbook_modules.views import render_edit_confirm_text
from app.bot.keyboards.logbook import get_back_to_logbook_keyboard
from app.database.logbook_repo import get_user_location
from app.services.logbook_service import submit_dermaga_entry

router = Router(name="logbook_calendar_edit_router")


async def _prompt_edit_field(
    callback: CallbackQuery,
    state: FSMContext,
    fsm_state: State,
    prompt_text: str,
    cancel_label: str = "❌ Batal Ubah Jam",
) -> None:
    """Helper bersama untuk memulai pengubahan field jam atau deskripsi pada sesi edit kalender."""
    await callback.answer()
    chat_id = callback.from_user.id
    if chat_id not in _calendar_edit_sessions:
        if callback.message:
            await callback.message.answer("❌ Sesi edit telah berakhir.")
        return

    await state.set_state(fsm_state)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cancel_label, callback_data="log_edact_reedit")]
    ])
    if callback.message:
        await callback.message.edit_text(prompt_text, parse_mode="HTML", reply_markup=markup)


async def _process_edit_time_input(
    message: Message,
    state: FSMContext,
    field_key: str,
    cancel_label: str,
    example: str,
) -> None:
    """Helper bersama memvalidasi input jam masuk/pulang dan memperbarui sesi edit kalender."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer(f"❌ Pengubahan {cancel_label} dibatalkan.")
        return

    norm_val = normalize_time_hhmm(message.text)
    if not norm_val:
        await message.answer(
            f"❌ Format tidak valid. Harap gunakan format 24 jam <code>HH:MM</code> (contoh: {example}):",
            parse_mode="HTML",
        )
        return

    await state.clear()
    session = _calendar_edit_sessions.get(message.chat.id)
    if session:
        session[field_key] = norm_val
        await _send_edit_detail_view(message.chat.id, message)
    else:
        await message.answer("❌ Sesi edit telah berakhir. Silakan buka menu /logbook.")


@router.callback_query(F.data == "log_edact_masuk")
async def cb_edact_masuk(callback: CallbackQuery, state: FSMContext) -> None:
    """Memicu pengubahan jam masuk entri lampau."""
    s = _calendar_edit_sessions.get(callback.from_user.id) or {}
    text = (
        f"⏰ <b>Ubah Jam Masuk (Tanggal {s.get('tanggal', '-')})</b>\n\n"
        f"Jam masuk saat ini: <code>{s.get('jam_masuk', '07:10')}</code>\n"
        "Silakan ketik jam masuk baru (Format 24 jam <code>HH:MM</code>, contoh: <code>07:15</code>):"
    )
    await _prompt_edit_field(callback, state, LogbookEditPastFSM.waiting_for_masuk, text)


@router.message(LogbookEditPastFSM.waiting_for_masuk)
async def process_edit_masuk_input(message: Message, state: FSMContext) -> None:
    """Menerima input jam masuk baru untuk entri lampau."""
    await _process_edit_time_input(message, state, "jam_masuk", "jam masuk", "07:15")


@router.callback_query(F.data == "log_edact_pulang")
async def cb_edact_pulang(callback: CallbackQuery, state: FSMContext) -> None:
    """Memicu pengubahan jam pulang entri lampau."""
    s = _calendar_edit_sessions.get(callback.from_user.id) or {}
    text = (
        f"⏰ <b>Ubah Jam Pulang (Tanggal {s.get('tanggal', '-')})</b>\n\n"
        f"Jam pulang saat ini: <code>{s.get('jam_pulang', '16:25')}</code>\n"
        "Silakan ketik jam pulang baru (Format 24 jam <code>HH:MM</code>, contoh: <code>16:30</code>):"
    )
    await _prompt_edit_field(callback, state, LogbookEditPastFSM.waiting_for_pulang, text)


@router.message(LogbookEditPastFSM.waiting_for_pulang)
async def process_edit_pulang_input(message: Message, state: FSMContext) -> None:
    """Menerima input jam pulang baru untuk entri lampau."""
    await _process_edit_time_input(message, state, "jam_pulang", "jam pulang", "16:30")


@router.callback_query(F.data == "log_edact_desk")
async def cb_edact_desk(callback: CallbackQuery, state: FSMContext) -> None:
    """Memicu pengubahan deskripsi pekerjaan entri lampau."""
    s = _calendar_edit_sessions.get(callback.from_user.id) or {}
    text = (
        f"📝 <b>Ubah Deskripsi Pekerjaan (Tanggal {s.get('tanggal', '-')})</b>\n\n"
        f"Deskripsi saat ini:\n<blockquote>{html.escape(s.get('deskripsi', '-'))}</blockquote>\n\n"
        "Silakan ketikkan teks deskripsi pekerjaan baru yang ingin disimpan:"
    )
    await _prompt_edit_field(
        callback,
        state,
        LogbookEditPastFSM.waiting_for_deskripsi,
        text,
        cancel_label="❌ Batal Ubah Deskripsi",
    )


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
    if not any(session.get(k) != orig.get(k) for k in ("jam_masuk", "jam_pulang", "deskripsi")):
        await callback.answer("Belum ada perubahan data yang dilakukan.", show_alert=True)
        return

    await callback.answer()
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Konfirmasi Simpan", callback_data="log_edact_confirmsave")],
        [InlineKeyboardButton(text="✏️ Ubah Kembali", callback_data="log_edact_reedit")],
        [InlineKeyboardButton(text="❌ Batal", callback_data="log_edact_cancel")],
    ])
    if callback.message:
        await callback.message.edit_text(render_edit_confirm_text(session), parse_mode="HTML", reply_markup=markup)


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
            f"⏳ <i>Sedang memperbarui logbook tanggal <code>{html.escape(str(session['tanggal']))}</code> "
            f"(ID: #{html.escape(str(session['web_id']))}) di DERMAGA...</i>",
            parse_mode="HTML",
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
            f"🗓 Tanggal: <code>{html.escape(str(session['tanggal']))}</code> "
            f"(ID: <code>#{html.escape(str(session['web_id']))}</code>)\n"
            f"⏰ Jam: <code>{html.escape(str(session['jam_masuk']))} - {html.escape(str(session['jam_pulang']))} WIB</code>\n\n"
            "📝 Data di portal DERMAGA telah terverifikasi berhasil diperbarui."
        )
    else:
        balasan = f"❌ <b>Gagal Memperbarui Logbook:</b>\n{html.escape(str(msg))}"

    if callback.message:
        await callback.message.answer(balasan, parse_mode="HTML", reply_markup=get_back_to_logbook_keyboard())


@router.callback_query(F.data == "log_edact_reedit")
async def cb_edact_reedit(callback: CallbackQuery, is_admin: bool = False) -> None:
    """Kembali ke tampilan detail edit entri."""
    await callback.answer()
    if callback.message:
        await _send_edit_detail_view(callback.from_user.id, callback.message, is_admin)


@router.callback_query(F.data == "log_edact_backmonth")
async def cb_edact_backmonth(callback: CallbackQuery, is_admin: bool = False) -> None:
    """Kembali ke pemilihan tanggal kalender bulan terpilih."""
    await callback.answer()
    chat_id = callback.from_user.id
    session = _calendar_edit_sessions.get(chat_id) or {}
    if callback.message:
        await _send_month_calendar_view(chat_id, callback.message, session.get("selected_month", ""), is_admin)


@router.callback_query(F.data == "log_edact_cancel")
async def cb_edact_cancel(callback: CallbackQuery, is_admin: bool = False) -> None:
    """Membatalkan sesi edit entri lampau dan kembali ke menu utama logbook."""
    await callback.answer()
    _calendar_edit_sessions.pop(callback.from_user.id, None)
    if callback.message:
        text, markup = await render_hub_view(callback.from_user.id, is_admin)
        await edit_or_answer(callback.message, text, reply_markup=markup)
