"""
Keyboard inline untuk alur modul Reminder.
"""

from datetime import datetime
from typing import Any, List
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_reminder_hub_keyboard() -> InlineKeyboardMarkup:
    """Keyboard hub pengingat: Tambah & Edit."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Tambah Pengingat", callback_data="rmd_hub_add"),
                InlineKeyboardButton(text="📝 Edit Pengingat", callback_data="rmd_hub_edit"),
            ]
        ]
    )


def get_reminder_edit_list_keyboard(reminders: List[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Menampilkan tombol untuk setiap pengingat aktif agar user dapat memilih yang ingin dikelola."""
    rows = []
    for r in reminders:
        r_id = r["id"]
        r_msg = r["message"]
        r_date = r["target_date"]
        try:
            tampilan_tanggal = datetime.strptime(r_date, "%Y-%m-%d").strftime("%d-%m-%Y")
        except Exception:
            tampilan_tanggal = r_date
        short_msg = r_msg[:20] + "..." if len(r_msg) > 20 else r_msg
        btn_text = f"[{tampilan_tanggal}] {short_msg}"
        rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"rmd_sel_{r_id}")])

    rows.append([InlineKeyboardButton(text="⬅️ Kembali", callback_data="rmd_ccl_0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_reminder_manage_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    """Menu aksi untuk pengingat yang dipilih: ubah pesan, tanggal, jam, H-, hapus, batal."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Ubah Pesan", callback_data=f"rmd_msg_{reminder_id}"),
                InlineKeyboardButton(text="📅 Ubah Tanggal", callback_data=f"rmd_dat_{reminder_id}"),
            ],
            [
                InlineKeyboardButton(text="⏰ Ubah Jam", callback_data=f"rmd_tim_{reminder_id}"),
                InlineKeyboardButton(text="⏳ Ubah H-", callback_data=f"rmd_prp_{reminder_id}"),
            ],
            [
                InlineKeyboardButton(text="🗑️ Hapus Pengingat", callback_data=f"rmd_del_{reminder_id}"),
            ],
            [
                InlineKeyboardButton(text="❌ Batal", callback_data="rmd_ccl_0"),
            ],
        ]
    )

