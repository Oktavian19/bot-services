"""
Sub-router Logbook untuk persetujuan, pengubahan lokasi/ringkasan, dan pembatalan draf.
"""

import html
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from app.bot.handlers.logbook_modules.shared import LogbookEditSummaryFSM, extract_override_id
from app.bot.keyboards.logbook import get_back_to_logbook_keyboard, get_draft_approval_keyboard
from app.database.logbook_repo import (
    complete_reminder_for_today,
    get_draft,
    get_user_location,
    update_draft_location_profile,
    update_draft_status,
    update_draft_summary,
)
from app.services.logbook_service import format_draft_message, submit_dermaga_entry

router = Router(name="logbook_drafts_router")


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
    override_id = extract_override_id(draft.get("raw_metadata"))

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
            f"📅 Tanggal: <code>{html.escape(str(date))}</code>\n"
            f"⏱ Jam: <code>{html.escape(str(jam_masuk))} - {html.escape(str(jam_pulang))} WIB</code>\n"
            f"📍 Lokasi: <code>{lat}, {lng}</code> (±{acc}m)\n\n"
            "✅ Absensi dan entri logbook telah tercatat aman di sistem kampus."
        )
    else:
        balasan = f"❌ <b>Gagal submit ke DERMAGA:</b>\n{html.escape(str(msg))}"

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
            reply_markup=markup,
        )
