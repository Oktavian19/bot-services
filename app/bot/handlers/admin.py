"""
Router Aiogram untuk fungsi administratif bot (Admin Panel).
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from app.database.logbook_repo import get_all_users

router = Router(name="admin_router")


def render_admin_users_list_text(users: list[dict]) -> str:
    """Menyusun teks HTML ringkasan seluruh pengguna terdaftar."""
    text = f"👥 <b>Panel Admin — Daftar Pengguna Logbook ({len(users)} Akun)</b>\n\n"
    for idx, u in enumerate(users, 1):
        username = u["username"]
        chat_id = u["chat_id"]
        total_drafts = u.get("total_drafts", 0)
        last_date = u.get("last_draft_date") or "-"
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

