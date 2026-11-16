"""
Sub-router Logbook untuk hub utama, pendaftaran akun DERMAGA, token CLI, dan hapus akun.
"""

import html
from typing import Optional
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from app.bot.handlers.logbook_modules.shared import edit_or_answer, unpack_event
from app.bot.handlers.logbook_modules.views import (
    build_daftar_success_text,
    build_hub_text,
    build_token_info_text,
    build_unregistered_hub_text,
)
from app.bot.keyboards.logbook import get_back_to_logbook_keyboard, get_logbook_hub_keyboard
from app.core.config import get_settings
from app.core.logger import logger
from app.database.logbook_repo import (
    delete_user_credential,
    get_recent_drafts,
    get_user_by_chat_id,
    regenerate_api_token,
    register_user_credential,
)
from app.services.logbook_service import test_dermaga_login

router = Router(name="logbook_account_router")


# --- HUB /LOGBOOK ---

async def render_hub_view(chat_id: int, is_admin: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    """Menyusun teks menu utama logbook dan tombol navigasi."""
    user = await get_user_by_chat_id(chat_id)
    if not user:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Daftar / Login Akun", callback_data="log_menu_account")]
        ])
        return build_unregistered_hub_text(), markup

    recent_drafts = await get_recent_drafts(chat_id, limit=3)
    return build_hub_text(user, recent_drafts), get_logbook_hub_keyboard(is_admin_user=is_admin)


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
        await edit_or_answer(callback.message, text, reply_markup=markup)


# --- PENDAFTARAN AKUN DERMAGA ---

def _parse_daftar_logbook_args(text: str) -> Optional[tuple[str, str, Optional[str]]]:
    """
    Mem-parsing argumen perintah /daftar_logbook.
    Mengembalikan (username, password, alt_password) atau None jika argumen kurang.
    Otomatis membersihkan pembungkus <...> bila pengguna menyalin format placeholder secara harfiah.
    """
    parts = (text or "").strip().split(maxsplit=2)
    if len(parts) < 3:
        return None

    raw_username, raw_password = parts[1].strip(), parts[2].strip()
    user_wrapped = raw_username.startswith("<") and raw_username.endswith(">") and len(raw_username) > 2
    username = raw_username[1:-1].strip() if user_wrapped else raw_username

    password = raw_password
    alt_password: Optional[str] = None
    if user_wrapped and raw_password.startswith("<") and raw_password.endswith(">") and len(raw_password) > 2:
        # Prioritaskan isi di dalam <...>, simpan versi asli sebagai fallback jika memang bagian dari password
        password = raw_password[1:-1]
        alt_password = raw_password

    return (username, password, alt_password) if (username and password) else None


@router.message(Command("daftar_logbook", "login_logbook", "set_dermaga_auth"))
async def cmd_daftar_logbook(message: Message) -> None:
    """Pendaftaran kredensial DERMAGA dan penerbitan API token CLI."""
    settings = get_settings()
    try:
        await message.delete()
    except Exception:
        pass

    parsed_args = _parse_daftar_logbook_args(message.text or "")
    if not parsed_args:
        await message.answer(
            "❌ Format salah.\n"
            "Gunakan: <code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code>\n\n"
            "<i>Contoh:</i> <code>/daftar_logbook 2341720117 Rahasia123</code>\n"
            "<i>(Ketik langsung tanpa tanda kurung &lt; &gt;)</i>",
            parse_mode="HTML",
        )
        return

    username, password, alt_password = parsed_args
    loading = await message.answer(
        f"⏳ <i>Sedang menguji autentikasi akun <code>{html.escape(username)}</code> ke portal DERMAGA...</i>",
        parse_mode="HTML",
    )

    ok, msg = await test_dermaga_login(username, password)
    if not ok and alt_password is not None:
        ok_alt, msg_alt = await test_dermaga_login(username, alt_password)
        if ok_alt:
            ok, msg, password = ok_alt, msg_alt, alt_password

    if not ok:
        await loading.edit_text(
            f"❌ <b>Verifikasi DERMAGA Gagal!</b>\n\n{html.escape(str(msg))}\n\n"
            "Silakan periksa kembali username/NIM dan password Anda.\n"
            "<i>Contoh pengisian tanpa tanda &lt; &gt;:</i> <code>/daftar_logbook 2341720117 Rahasia123</code>",
            parse_mode="HTML",
        )
        return

    try:
        token = await register_user_credential(message.chat.id, username, password)
        success_text = build_daftar_success_text(username, token, settings.LOGBOOK_PUBLIC_URL)
        await loading.edit_text(success_text, parse_mode="HTML", reply_markup=get_back_to_logbook_keyboard())
        logger.info(f"[LOGBOOK] User {message.chat.id} ({username}) berhasil terdaftar/update.")
    except Exception as e:
        await loading.edit_text(f"❌ Terjadi kesalahan saat menyimpan akun: {e}")


# --- TOKEN & AKUN LOGBOOK ---

@router.message(Command("token_logbook"))
@router.callback_query(F.data.in_({"log_menu_token", "log_menu_account"}))
async def cmd_token_logbook(event: Message | CallbackQuery) -> None:
    """Menampilkan detail akun dan token API CLI logbook."""
    settings = get_settings()
    chat_id, target_msg = await unpack_event(event)
    if not target_msg:
        return

    user = await get_user_by_chat_id(chat_id)
    if not user:
        warn_text = (
            "⚠️ Akun Anda belum terdaftar. Gunakan <code>/daftar_logbook</code> terlebih dahulu.\n"
            "<i>Contoh:</i> <code>/daftar_logbook 2341720117 Rahasia123</code>"
        )
        if isinstance(event, CallbackQuery):
            await edit_or_answer(target_msg, warn_text, reply_markup=get_back_to_logbook_keyboard())
        else:
            await target_msg.answer(warn_text, parse_mode="HTML")
        return

    text = build_token_info_text(str(user["username"]), user.get("api_token", "-"), settings.LOGBOOK_PUBLIC_URL)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Buat Ulang Token", callback_data="log_regen_token")],
        [InlineKeyboardButton(text="🗑 Hapus Akun & Data", callback_data="log_menu_hapus")],
        [InlineKeyboardButton(text="⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back")],
    ])
    if isinstance(event, CallbackQuery):
        await edit_or_answer(target_msg, text, reply_markup=markup)
    else:
        await target_msg.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data == "log_regen_token")
async def cb_regen_token(callback: CallbackQuery) -> None:
    """Membuat ulang API token."""
    await callback.answer()
    new_token = await regenerate_api_token(callback.from_user.id)
    if not callback.message:
        return
    if new_token:
        await callback.message.answer(
            f"✅ <b>API Token Baru Berhasil Dibuat:</b>\n\n<code>{html.escape(str(new_token))}</code>\n\n"
            "<i>Jangan lupa memperbarui file config.json di laptop Anda.</i>",
            parse_mode="HTML",
        )
    else:
        await callback.message.answer("⚠️ Gagal membuat ulang token.")


# --- HAPUS AKUN ---

@router.message(Command("hapus_akun_logbook", "hapus_akun"))
@router.callback_query(F.data == "log_menu_hapus")
async def cmd_hapus_akun_prompt(event: Message | CallbackQuery) -> None:
    """Prompt konfirmasi penghapusan akun."""
    _, target_msg = await unpack_event(event)
    if not target_msg:
        return

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ Ya, Hapus Akun Saya", callback_data="log_confirm_hapus_akun")],
        [InlineKeyboardButton(text="❌ Batal", callback_data="log_menu_back")],
    ])
    await target_msg.answer(
        "⚠️ <b>Konfirmasi Hapus Akun Logbook</b>\n\n"
        "Apakah Anda yakin ingin menghapus akun dan seluruh token CLI Anda dari sistem bot?",
        parse_mode="HTML",
        reply_markup=markup,
    )


@router.callback_query(F.data == "log_confirm_hapus_akun")
async def cb_confirm_hapus_akun(callback: CallbackQuery) -> None:
    """Eksekusi hapus akun."""
    await callback.answer()
    await delete_user_credential(callback.from_user.id)
    if callback.message:
        await callback.message.edit_text("✅ Akun dan token CLI Anda berhasil dihapus dari sistem bot.")
