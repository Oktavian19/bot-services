"""
Keyboard inline untuk alur utama bot (/start dan menu kendali).
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Mengembalikan inline keyboard pusat kendali server di menu utama."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏓 Ping Server", callback_data="cb_ping"),
                InlineKeyboardButton(text="🔔 Pengingat", callback_data="cb_reminder"),
            ],
            [
                InlineKeyboardButton(text="🚀 Speedtest", callback_data="cb_speedtest"),
                InlineKeyboardButton(text="⛽ BBM Motor", callback_data="cb_bensin"),
            ],
            [
                InlineKeyboardButton(text="📖 Logbook", callback_data="cb_logbook"),
            ],
        ]
    )


def get_back_button(callback_data: str = "cb_start") -> InlineKeyboardMarkup:
    """Tombol kembali generik."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Kembali ke Menu Utama", callback_data=callback_data)]
        ]
    )

