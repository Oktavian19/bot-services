"""
Sub-router Logbook untuk pengaturan menu pengingat, jam pengingat, dan hari aktif.
"""

import html
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from app.bot.handlers.logbook_modules.shared import (
    LogbookSetJamFSM,
    edit_or_answer,
    normalize_time_hhmm,
    unpack_event,
)
from app.bot.keyboards.logbook import (
    get_back_to_logbook_keyboard,
    get_reminder_days_checklist_keyboard,
    get_settings_menu_keyboard,
)
from app.database.logbook_repo import (
    get_user_reminder_days,
    get_user_reminder_time,
    update_user_reminder_days,
    update_user_reminder_time,
)
from app.services.logbook_service import format_reminder_days_display

router = Router(name="logbook_reminder_settings_router")


@router.callback_query(F.data == "log_menu_settings")
async def cb_menu_settings(callback: CallbackQuery) -> None:
    """Menampilkan menu pengaturan pengingat jam dan hari logbook."""
    await callback.answer()
    chat_id = callback.from_user.id
    user_time = await get_user_reminder_time(chat_id)
    user_days = await get_user_reminder_days(chat_id)
    days_disp = html.escape(format_reminder_days_display(user_days))

    text = (
        "⚙️ <b>Pengaturan Pengingat Logbook</b>\n\n"
        f"⏰ <b>Jam Pengingat:</b> <code>{html.escape(str(user_time))} WIB</code>\n"
        f"🗓 <b>Hari Aktif:</b> <b>{days_disp}</b>\n\n"
        "Pilih pengaturan yang ingin Anda ubah:"
    )
    await edit_or_answer(callback.message, text, reply_markup=get_settings_menu_keyboard())


# --- PENGATURAN JAM PENGINGAT ---

@router.message(Command("set_jam_logbook", "jam_logbook"))
@router.callback_query(F.data == "log_menu_set_jam")
async def cmd_set_jam_logbook(event: Message | CallbackQuery, state: FSMContext) -> None:
    """Mengatur jam pengingat harian logbook."""
    chat_id, target_msg = await unpack_event(event)
    if not target_msg:
        return

    if isinstance(event, Message) and len((event.text or "").split()) > 1:
        norm_time = normalize_time_hhmm(event.text.split()[1])
        if norm_time:
            await update_user_reminder_time(chat_id, norm_time)
            await target_msg.answer(
                f"✅ <b>Jam Pengingat Berhasil Diubah!</b>\n\n"
                f"Setiap hari pukul <b>{norm_time} WIB</b> bot akan mengingatkan pengisian logbook.",
                parse_mode="HTML",
                reply_markup=get_back_to_logbook_keyboard(),
            )
        else:
            await target_msg.answer(
                "❌ Format jam salah. Harap gunakan format 24 jam HH:MM (contoh: 16:30)."
            )
        return

    current_time = await get_user_reminder_time(chat_id)
    await state.set_state(LogbookSetJamFSM.waiting_for_time)
    await target_msg.answer(
        f"⏰ <b>Pengaturan Jam Pengingat Logbook</b>\n\n"
        f"Jam saat ini: <b>{html.escape(str(current_time))} WIB</b>\n\n"
        "Silakan ketikkan jam pengingat baru (Format HH:MM, contoh: 16:30):",
        parse_mode="HTML",
    )


@router.message(LogbookSetJamFSM.waiting_for_time)
async def process_set_jam_input(message: Message, state: FSMContext) -> None:
    """Menerima input jam baru."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pengaturan jam pengingat dibatalkan.")
        return

    norm_time = normalize_time_hhmm(message.text)
    if not norm_time:
        await message.answer(
            "❌ Format jam tidak valid. Harap gunakan format 24 jam <code>HH:MM</code> (contoh: 16:05):",
            parse_mode="HTML",
        )
        return

    await state.clear()
    await update_user_reminder_time(message.chat.id, norm_time)
    await message.answer(
        f"✅ <b>Jam Pengingat Berhasil Disimpan!</b>\n\n"
        f"Mulai hari ini, Anda akan diingatkan pada pukul <b>{norm_time} WIB</b>.",
        parse_mode="HTML",
        reply_markup=get_back_to_logbook_keyboard(),
    )


# --- PENGATURAN HARI PENGINGAT ---

async def _render_reminder_days_view(target_msg: Message, days_str: str, edit: bool = False) -> None:
    """Menyusun dan menampilkan checklist jadwal hari pengingat logbook."""
    text = (
        "🗓 <b>Pengaturan Hari Pengingat Logbook</b>\n\n"
        f"Jadwal aktif saat ini: <b>{html.escape(format_reminder_days_display(days_str))}</b>\n\n"
        "Pilih hari atau gunakan preset di bawah ini:"
    )
    markup = get_reminder_days_checklist_keyboard(days_str)
    if edit:
        try:
            await target_msg.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
    else:
        await target_msg.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(Command("set_hari_logbook", "hari_logbook"))
@router.callback_query(F.data == "log_menu_set_hari")
async def cmd_set_hari_logbook(event: Message | CallbackQuery) -> None:
    """Membuka checklist hari pengingat aktif."""
    chat_id, target_msg = await unpack_event(event)
    if not target_msg:
        return
    current_days = await get_user_reminder_days(chat_id)
    await _render_reminder_days_view(target_msg, current_days, edit=False)


@router.callback_query(F.data.startswith("log_daytg_"))
async def cb_toggle_reminder_day(callback: CallbackQuery) -> None:
    """Toggle status hari tertentu di checklist."""
    await callback.answer()
    day_idx = int(callback.data.split("_")[2])
    chat_id = callback.from_user.id
    current_days_str = await get_user_reminder_days(chat_id)
    days = {int(x.strip()) for x in current_days_str.split(",") if x.strip().isdigit()}

    days.remove(day_idx) if day_idx in days else days.add(day_idx)
    new_days_str = ",".join(str(d) for d in sorted(days))
    await update_user_reminder_days(chat_id, new_days_str)

    if callback.message:
        await _render_reminder_days_view(callback.message, new_days_str, edit=True)


@router.callback_query(F.data.startswith("log_dayps_"))
async def cb_preset_reminder_day(callback: CallbackQuery) -> None:
    """Terapkan preset hari pengingat."""
    await callback.answer()
    preset = callback.data.split("_")[2]
    chat_id = callback.from_user.id

    preset_map = {"weekdays": "0,1,2,3,4", "all": "0,1,2,3,4,5,6"}
    new_days = preset_map.get(preset, "")
    await update_user_reminder_days(chat_id, new_days)

    if callback.message:
        await _render_reminder_days_view(callback.message, new_days, edit=True)
