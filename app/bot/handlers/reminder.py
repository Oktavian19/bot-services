"""
Router Aiogram untuk modul Reminder Agenda (Pengingat).
Menggunakan Aiogram FSM (Finite State Machine) untuk alur percakapan pembuatan & pengeditan reminder.
"""

from datetime import datetime
from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from app.bot.keyboards.reminder import (
    get_reminder_edit_list_keyboard,
    get_reminder_hub_keyboard,
    get_reminder_manage_keyboard,
)
from app.core.logger import logger
from app.database.reminder_repo import (
    delete_reminder,
    get_active_reminders_by_chat,
    insert_reminder,
    update_reminder_field,
)
from app.services.reminder_service import format_reminders_list_text

router = Router(name="reminder_router")


# --- FSM STATES ---

class ReminderCreateFSM(StatesGroup):
    waiting_for_message = State()
    waiting_for_date = State()
    waiting_for_prep_days = State()
    waiting_for_time = State()


class ReminderEditFSM(StatesGroup):
    waiting_for_value = State()


# --- COMMAND /REMINDER & HUB ---

async def show_reminder_hub(message_or_event: Message, chat_id: int) -> None:
    """Menampilkan hub daftar pengingat aktif."""
    logger.info(f"[REMINDER] User {chat_id} mengakses hub pengingat.")
    reminders = await get_active_reminders_by_chat(chat_id)
    text = format_reminders_list_text(reminders)
    markup = get_reminder_hub_keyboard()
    await message_or_event.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(Command("reminder"))
async def cmd_reminder(message: Message) -> None:
    """Command /reminder."""
    await show_reminder_hub(message, message.chat.id)


@router.callback_query(F.data == "cb_reminder")
async def cb_reminder_handler(callback: CallbackQuery) -> None:
    """Callback tombol Pengingat di menu utama."""
    await callback.answer()
    if callback.message:
        await show_reminder_hub(callback.message, callback.from_user.id)


# --- EDIT LIST COMMAND ---

async def show_edit_menu(message_or_event: Message, chat_id: int) -> None:
    """Menampilkan pilihan pengingat untuk diedit atau dihapus."""
    reminders = await get_active_reminders_by_chat(chat_id)
    if not reminders:
        await message_or_event.answer("ℹ️ Anda tidak memiliki pengingat yang aktif saat ini.")
        return
    markup = get_reminder_edit_list_keyboard(reminders)
    await message_or_event.answer("Pilih pengingat yang ingin Anda kelola:", reply_markup=markup)


@router.message(Command("edit_reminder"))
async def cmd_edit_reminder(message: Message) -> None:
    """Command /edit_reminder."""
    await show_edit_menu(message, message.chat.id)


# --- WIZARD TAMBAH PENGINGAT (FSM) ---

@router.message(Command("add_reminder"))
@router.callback_query(F.data == "rmd_hub_add")
async def start_add_reminder(event: Message | CallbackQuery, state: FSMContext) -> None:
    """Memulai wizard pembuatan pengingat baru."""
    if isinstance(event, CallbackQuery):
        await event.answer()
        target_msg = event.message
    else:
        target_msg = event

    await state.clear()
    await state.set_state(ReminderCreateFSM.waiting_for_message)
    await target_msg.answer("Siap! Pengingat untuk acara apa? (Kirimkan pesan utamanya):")


@router.message(ReminderCreateFSM.waiting_for_message)
async def process_msg_step(message: Message, state: FSMContext) -> None:
    """Menerima isi pesan utama pengingat."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pembuatan pengingat dibatalkan.")
        return

    await state.update_data(message=message.text)
    await state.set_state(ReminderCreateFSM.waiting_for_date)
    await message.answer(
        "Pesan dicatat. Kapan tanggal target atau hari-H nya?\n"
        "(Format: DD-MM-YYYY, contoh: 15-06-2026)"
    )


@router.message(ReminderCreateFSM.waiting_for_date)
async def process_date_step(message: Message, state: FSMContext) -> None:
    """Menerima tanggal target Hari-H."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pembuatan pengingat dibatalkan.")
        return

    date_text = message.text.strip()
    try:
        parsed_date = datetime.strptime(date_text, "%d-%m-%Y")
        db_ready_date = parsed_date.strftime("%Y-%m-%d")
        await state.update_data(target_date=db_ready_date, display_date=date_text)
        await state.set_state(ReminderCreateFSM.waiting_for_prep_days)
        await message.answer(
            f"Berapa hari sebelum tanggal {date_text} saya harus mulai mengingatkan Anda?\n"
            f"(Ketik angkanya saja, misal: 3)"
        )
    except ValueError:
        await message.answer("⚠️ Format salah. Silakan gunakan format DD-MM-YYYY (contoh: 15-06-2026):")


@router.message(ReminderCreateFSM.waiting_for_prep_days)
async def process_prep_days_step(message: Message, state: FSMContext) -> None:
    """Menerima jumlah hari persiapan (H-x)."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pembuatan pengingat dibatalkan.")
        return

    prep_text = message.text.strip()
    if not prep_text.isdigit():
        await message.answer("⚠️ Harap masukkan angka saja (contoh: 3):")
        return

    await state.update_data(prep_days=int(prep_text))
    await state.set_state(ReminderCreateFSM.waiting_for_time)
    await message.answer(
        "Di jam berapa saya me-referensi pengingat ini setiap harinya?\n"
        "(Format: HH:MM, contoh: 07:00)"
    )


@router.message(ReminderCreateFSM.waiting_for_time)
async def process_time_step(message: Message, state: FSMContext) -> None:
    """Menerima jam pengingat harian dan menyimpan ke database."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pembuatan pengingat dibatalkan.")
        return

    time_text = message.text.strip()
    try:
        datetime.strptime(time_text, "%H:%M")
        data = await state.get_data()
        await state.clear()

        msg_content = data["message"]
        target_date = data["target_date"]
        prep_days = data["prep_days"]
        display_date = data.get("display_date", target_date)

        await insert_reminder(message.chat.id, msg_content, target_date, time_text, prep_days)

        await message.answer(
            f"✅ <b>Pengingat berhasil diatur!</b>\n\n"
            f"<b>Pesan:</b> '{msg_content}'\n"
            f"<b>Waktu:</b> Setiap jam {time_text} WIB, mulai H-{prep_days} sebelum tanggal {display_date}.",
            parse_mode="HTML"
        )
        logger.info(f"[REMINDER] Pengingat baru disimpan untuk User {message.chat.id}.")

    except ValueError:
        await message.answer("⚠️ Format waktu salah. Gunakan format HH:MM (contoh: 07:00):")


# --- CALLBACK ROUTER REMINDER ---

@router.callback_query(F.data.startswith("rmd_"))
async def handle_reminder_callbacks(callback: CallbackQuery, state: FSMContext) -> None:
    """Router callback interaktif untuk seluruh tombol berprefix 'rmd_'."""
    await callback.answer()
    data = callback.data or ""
    chat_id = callback.from_user.id
    msg = callback.message

    if data == "rmd_hub_edit":
        if msg:
            await show_edit_menu(msg, chat_id)
        return

    if data == "rmd_ccl_0":
        await state.clear()
        if msg:
            try:
                await msg.edit_text("✅ Operasi dibatalkan.")
            except Exception:
                await msg.answer("✅ Operasi dibatalkan.")
        return

    # Callback berparameter ID (rmd_sel_<id>, rmd_del_<id>, dsb.)
    if len(data) <= 8:
        return

    action = data[:7]  # 'rmd_sel', 'rmd_del', 'rmd_msg', 'rmd_dat', 'rmd_tim', 'rmd_prp'
    try:
        reminder_id = int(data[8:])
    except ValueError:
        return

    if action == "rmd_sel":
        markup = get_reminder_manage_keyboard(reminder_id)
        if msg:
            await msg.edit_text("Pilih bagian mana yang ingin diubah atau dihapus:", reply_markup=markup)

    elif action == "rmd_del":
        await delete_reminder(reminder_id)
        if msg:
            await msg.edit_text("🗑️ <b>Pengingat berhasil dihapus!</b>", parse_mode="HTML")

    elif action in ("rmd_msg", "rmd_dat", "rmd_tim", "rmd_prp"):
        field_map = {
            "rmd_msg": ("message", "Kirimkan pesan baru untuk pengingat ini:"),
            "rmd_dat": ("target_date", "Kirimkan tanggal baru (Format: DD-MM-YYYY):"),
            "rmd_tim": ("notify_time", "Kirimkan jam baru (Format: HH:MM):"),
            "rmd_prp": ("prep_days", "Berapa hari sebelumnya bot harus mengingatkan? (Ketik angka saja):"),
        }
        field_name, prompt = field_map[action]
        await state.set_state(ReminderEditFSM.waiting_for_value)
        await state.update_data(edit_reminder_id=reminder_id, edit_field=field_name)
        if msg:
            await msg.answer(prompt)


# --- FSM EDIT REMINDER VALUE ---

@router.message(ReminderEditFSM.waiting_for_value)
async def process_edit_value(message: Message, state: FSMContext) -> None:
    """Menerima dan memvalidasi nilai baru saat mengedit field pengingat."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Perubahan dibatalkan.")
        return

    data = await state.get_data()
    reminder_id = data.get("edit_reminder_id")
    field = data.get("edit_field")
    await state.clear()

    if not reminder_id or not field:
        await message.answer("⚠️ Sesi edit tidak valid. Silakan ulangi.")
        return

    new_val = message.text.strip()
    try:
        if field == "target_date":
            parsed_date = datetime.strptime(new_val, "%d-%m-%Y")
            new_val = parsed_date.strftime("%Y-%m-%d")
        elif field == "notify_time":
            datetime.strptime(new_val, "%H:%M")
        elif field == "prep_days":
            if not new_val.isdigit():
                raise ValueError("Bukan angka")
            new_val = int(new_val)

        await update_reminder_field(reminder_id, field, new_val)
        await message.answer("✅ <b>Pengingat berhasil diperbarui!</b>", parse_mode="HTML")
        logger.info(f"[REMINDER] Field '{field}' pada ID {reminder_id} diperbarui.")

    except ValueError:
        if field == "target_date":
            await message.answer("⚠️ Format tanggal salah. Pembaruan dibatalkan. (Gunakan DD-MM-YYYY).")
        elif field == "notify_time":
            await message.answer("⚠️ Format jam salah. Pembaruan dibatalkan. (Gunakan HH:MM).")
        elif field == "prep_days":
            await message.answer("⚠️ Harap masukkan angka saja. Pembaruan dibatalkan.")

