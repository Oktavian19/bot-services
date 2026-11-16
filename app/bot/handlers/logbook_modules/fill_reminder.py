"""
Sub-router Logbook untuk pengisian/edit hari ini dan respons aksi tombol pengingat.
"""

from datetime import datetime
import html
import time
from zoneinfo import ZoneInfo
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from app.bot.handlers.logbook_modules.shared import LogbookManualFillFSM
from app.bot.keyboards.logbook import get_back_to_logbook_keyboard, get_draft_approval_keyboard
from app.core.config import get_settings
from app.database.logbook_repo import (
    complete_reminder_for_today,
    create_or_get_draft,
    get_user_by_chat_id,
    get_user_reminder_time,
    get_weekly_reminder_state,
    stop_reminder_for_today,
    stop_weekly_reminder,
)
from app.services.logbook_service import check_monitoring_today, format_draft_message

router = Router(name="logbook_fill_reminder_router")


# --- PENGISIAN & EDIT LOGBOOK HARI INI ---

async def _trigger_isi_logbook(chat_id: int, target_message: Message, state: FSMContext) -> None:
    """Logika alur pengisian logbook hari ini: cek DERMAGA, konfirmasi edit jika sudah ada, atau buat baru."""
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await target_message.answer(
            "⚠️ <b>Akun Belum Terdaftar!</b>\n\n"
            "Anda belum menghubungkan akun DERMAGA ke bot ini.\n"
            "Gunakan perintah:\n"
            "<code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code>\n"
            "<i>Contoh:</i> <code>/daftar_logbook 2341720117 Rahasia123</code>\n"
            "<i>(Ketik tanpa tanda &lt; &gt;)</i>",
            parse_mode="HTML",
        )
        return

    settings = get_settings()
    today_str = datetime.now(ZoneInfo(settings.TIMEZONE)).strftime("%Y-%m-%d")

    status_msg = await target_message.answer(
        f"⏳ <i>Memeriksa status logbook hari ini (<code>{today_str}</code>) di portal DERMAGA...</i>",
        parse_mode="HTML",
    )

    result = await check_monitoring_today(chat_id, today_str)
    if result.get("exists") and result.get("entry"):
        entry = result["entry"]
        web_id = entry.get("web_id", "-")
        masuk = html.escape(str(entry.get("masuk", "07:10")))
        pulang = html.escape(str(entry.get("pulang", "16:25")))
        deskripsi = html.escape(entry.get("deskripsi") or "-")

        confirm_markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Ya, Edit Logbook Hari Ini", callback_data=f"log_isi_edit_{web_id}")],
            [InlineKeyboardButton(text="❌ Batal", callback_data="log_menu_back")],
        ])
        teks_konfirmasi = (
            f"⚠️ <b>Logbook Hari Ini Sudah Terisi!</b>\n\n"
            f"Entri tanggal <code>{today_str}</code> sudah tercatat di sistem DERMAGA.\n\n"
            f"🆔 <b>ID Entri:</b> <code>#{html.escape(str(web_id))}</code>\n"
            f"⏱ <b>Jam Kerja:</b> <code>{masuk} - {pulang} WIB</code>\n"
            f"📋 <b>Aktivitas Saat Ini:</b>\n"
            f"<blockquote>{deskripsi}</blockquote>\n\n"
            "Apakah Anda ingin mengedit / memperbarui logbook hari ini?"
        )
        await status_msg.edit_text(teks_konfirmasi, parse_mode="HTML", reply_markup=confirm_markup)
        return

    await state.set_state(LogbookManualFillFSM.waiting_for_text)
    await state.update_data(target_date=today_str, is_edit=False, override_id=None)
    prompt_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal", callback_data="log_menu_back")]
    ])
    prompt_text = (
        f"✍️ <b>Pengisian Logbook Hari Ini</b>\n"
        f"📅 Tanggal: <code>{today_str}</code>\n\n"
        "Silakan ketikkan deskripsi pekerjaan / aktivitas Anda hari ini:\n"
        "<i>(Ketik pesan biasa di chat ini atau klik Batal)</i>"
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
    today_str = datetime.now(ZoneInfo(settings.TIMEZONE)).strftime("%Y-%m-%d")

    await state.set_state(LogbookManualFillFSM.waiting_for_edit_text)
    await state.update_data(target_date=today_str, is_edit=True, override_id=web_id)

    prompt_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal", callback_data="log_menu_back")]
    ])
    prompt_text = (
        f"✏️ <b>Edit Logbook Hari Ini (<code>{today_str}</code>)</b>\n"
        f"🆔 ID Entri: <code>#{html.escape(str(web_id))}</code>\n\n"
        "Silakan ketikkan deskripsi pekerjaan / aktivitas baru untuk menimpa entri lama:\n"
        "<i>(Ketik pesan biasa di chat ini atau klik Batal)</i>"
    )
    if callback.message:
        await callback.message.edit_text(prompt_text, parse_mode="HTML", reply_markup=prompt_markup)


# --- MANUAL ISI & AKSI PENGINGAT ---

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
    default_today = datetime.now(ZoneInfo(settings.TIMEZONE)).strftime("%Y-%m-%d")
    target_date = data.get("target_date", default_today)
    is_edit = data.get("is_edit", False)
    override_id = data.get("override_id")
    await state.clear()

    chat_id = message.chat.id
    idempotency_key = f"manual_{chat_id}_{target_date}_{int(time.time())}"
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
        reply_markup=markup,
    )


@router.callback_query(F.data.startswith("log_remind_stop_"))
async def cb_remind_stop(callback: CallbackQuery) -> None:
    """Hentikan pengingat harian untuk hari ini."""
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
            f"Bot tidak akan mengirim pengingat logbook lagi untuk tanggal <code>{html.escape(target_date)}</code>.\n"
            f"Anda akan diingatkan kembali besok pada jam <b>{html.escape(str(user_time))} WIB</b>.",
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("log_stop_week_"))
async def cb_stop_weekly_reminder(callback: CallbackQuery) -> None:
    """Menghentikan pengingat tanda tangan logbook untuk minggu tertentu."""
    await callback.answer()
    week_start = callback.data.replace("log_stop_week_", "")
    chat_id = callback.from_user.id

    await stop_weekly_reminder(chat_id, week_start)
    state = await get_weekly_reminder_state(chat_id, week_start)
    week_lbl = state.get("week_label") if state and state.get("week_label") else week_start

    if callback.message:
        await callback.message.answer(
            f"🔕 <b>Pengingat Dihentikan</b>\n\n"
            f"Bot tidak akan mengingatkan pengajuan tanda tangan untuk <b>{html.escape(str(week_lbl))}</b> lagi.",
            parse_mode="HTML",
        )
