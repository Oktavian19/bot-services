"""
Router Aiogram untuk fungsi administratif bot (Admin Panel).
"""

import html
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from app.database.logbook_repo import get_all_users
from app.services.backup_service import send_sqlite_backup_to_telegram

router = Router(name="admin_router")


def render_admin_users_list_text(users: list[dict]) -> str:
    """Menyusun teks HTML ringkasan seluruh pengguna terdaftar."""
    text = f"👥 <b>Panel Admin — Daftar Pengguna Logbook ({len(users)} Akun)</b>\n\n"
    for idx, u in enumerate(users, 1):
        username = html.escape(str(u["username"]))
        chat_id = u["chat_id"]
        total_drafts = u.get("total_drafts", 0)
        last_date = html.escape(str(u.get("last_draft_date") or "-"))
        text += (
            f"{idx}. <b>{username}</b> (Chat ID: <code>{chat_id}</code>)\n"
            f"   Total Draf: <b>{total_drafts}</b> | Terakhir: <code>{last_date}</code>\n\n"
        )
    return text


@router.message(Command("admin_logbook"))
@router.callback_query(F.data == "log_menu_admin_users")
async def cmd_admin_logbook(event: Message | CallbackQuery, is_admin: bool = False) -> None:
    """Menampilkan panel daftar user untuk administrator."""
    target_msg = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()

    if not is_admin:
        await target_msg.answer("⛔ Akses ditolak. Hanya untuk Administrator.")
        return

    users = await get_all_users()
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back")]
    ])

    if not users:
        await target_msg.answer("ℹ️ Belum ada pengguna logbook yang terdaftar.", reply_markup=markup)
        return

    text = render_admin_users_list_text(users)
    await target_msg.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(Command("backup"))
async def cmd_backup_db(message: Message, is_admin: bool = False) -> None:
    """Membuat backup arsip ZIP seluruh database SQLite dan mengirimkannya (Admin only)."""
    if not is_admin:
        await message.answer("⛔ Akses ditolak. Hanya untuk Administrator.")
        return

    loading = await message.answer(
        "⏳ <i>Sedang membuat snapshot WAL-safe seluruh database SQLite...</i>",
        parse_mode="HTML",
    )
    ok, msg = await send_sqlite_backup_to_telegram(message.bot, message.chat.id, scheduled=False)
    if ok:
        try:
            await loading.delete()
        except Exception:
            pass
    else:
        await loading.edit_text(f"❌ {html.escape(msg)}", parse_mode="HTML")

