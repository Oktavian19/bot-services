"""
Router Aiogram untuk alur umum bot (/start, /ping, dan callback menu utama).
"""

from datetime import datetime
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from app.bot.keyboards.common import get_main_menu_keyboard

router = Router(name="common_router")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Menampilkan menu utama Pusat Kendali Server."""
    text = (
        "🎛 <b>Pusat Kendali Server</b>\n"
        "Silakan pilih salah satu menu di bawah ini:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu_keyboard())


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    """Cek status online server via /ping."""
    waktu = datetime.now().strftime("%H:%M:%S")
    balasan = (
        f"🏓 <b>Pong!</b>\n\n"
        f"Server Debian dalam kondisi <b>ONLINE</b> dan terhubung ke jaringan.\n"
        f"⏱ <code>{waktu}</code>"
    )
    await message.reply(balasan, parse_mode="HTML")


@router.callback_query(F.data == "cb_ping")
async def cb_ping_handler(callback: CallbackQuery) -> None:
    """Handler tombol Ping Server di menu utama."""
    await callback.answer()
    waktu = datetime.now().strftime("%H:%M:%S")
    balasan = (
        f"🏓 <b>Pong!</b>\n\n"
        f"Server Debian dalam kondisi <b>ONLINE</b> dan terhubung ke jaringan.\n"
        f"⏱ <code>{waktu}</code>"
    )
    if callback.message:
        await callback.message.answer(balasan, parse_mode="HTML")


@router.callback_query(F.data == "cb_start")
async def cb_start_handler(callback: CallbackQuery) -> None:
    """Kembali ke menu utama dari submenu."""
    await callback.answer()
    text = (
        "🎛 <b>Pusat Kendali Server</b>\n"
        "Silakan pilih salah satu menu di bawah ini:"
    )
    if callback.message:
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_menu_keyboard())
        except Exception:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=get_main_menu_keyboard())

