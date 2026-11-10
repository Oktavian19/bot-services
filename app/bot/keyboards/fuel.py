"""
Keyboard inline untuk modul BBM & Motor.
"""

from typing import Any, List, Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_fuel_hub_keyboard(motor_exists: bool, status_oli: Optional[dict[str, Any]] = None) -> InlineKeyboardMarkup:
    """Menu tombol dasbor hub /bensin."""
    if not motor_exists:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📝 Daftar Motor", callback_data="bsn_daftar")]
            ]
        )

    rows = []
    if status_oli and status_oli.get("status") in ("mendekati", "terlewat"):
        rows.append([InlineKeyboardButton(text="🛢️ Sudah Ganti Oli!", callback_data="bsn_action_ganti_oli")])

    rows.append([
        InlineKeyboardButton(text="⛽ Isi Bensin", callback_data="bsn_isi"),
        InlineKeyboardButton(text="📜 Riwayat & Edit/Hapus", callback_data="bsn_riwayat"),
    ])
    rows.append([
        InlineKeyboardButton(text="🛢️ Cek & Atur Oli", callback_data="bsn_menu_oli"),
        InlineKeyboardButton(text="⚙️ Ubah Motor (Reset)", callback_data="bsn_daftar"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_skip_odo_keyboard() -> InlineKeyboardMarkup:
    """Tombol pintas lewati odometer saat pengisian SPBU."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Lewati Odometer", callback_data="bsn_skip_odo")]
        ]
    )


def get_fuel_price_keyboard(edit_mode: bool = False) -> InlineKeyboardMarkup:
    """Pilihan cepat harga per liter bensin (Pertalite vs Pertamax)."""
    prefix = "bsn_edithrg_" if edit_mode else "bsn_hrg_"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 Pertalite (10.000)", callback_data=f"{prefix}10000"),
                InlineKeyboardButton(text="🔵 Pertamax (16.250)", callback_data=f"{prefix}16250"),
            ]
        ]
    )


def get_fuel_logs_keyboard(logs: List[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Menampilkan 10 log bensin terakhir."""
    rows = []
    for log in logs:
        log_id = log["id"]
        odo = log["odometer"]
        rupiah = log["rupiah"]
        liter = log["liter"]
        tgl = str(log["tanggal"])[:10] if log.get("tanggal") else ""

        if odo is None:
            btn_text = f"📅 {tgl} | [Tanpa Odo] | Rp{rupiah:,} ({liter:.2f}L)"
        else:
            btn_text = f"📅 {tgl} | {odo:.0f} km | Rp{rupiah:,} ({liter:.2f}L)"

        rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"bsn_log_{log_id}")])

    rows.append([InlineKeyboardButton(text="🔙 Kembali ke Hub Bensin", callback_data="bsn_back_hub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_fuel_log_detail_keyboard(log_id: int) -> InlineKeyboardMarkup:
    """Menu aksi detail log: Edit, Hapus, Kembali."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Edit Log", callback_data=f"bsn_edit_{log_id}"),
                InlineKeyboardButton(text="🗑 Hapus Log", callback_data=f"bsn_del_{log_id}"),
            ],
            [
                InlineKeyboardButton(text="📜 Kembali ke Riwayat", callback_data="bsn_riwayat"),
            ],
        ]
    )


def get_fuel_log_delete_confirm_keyboard(log_id: int) -> InlineKeyboardMarkup:
    """Konfirmasi hapus log bensin."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ya, Hapus", callback_data=f"bsn_dodel_{log_id}"),
                InlineKeyboardButton(text="❌ Batal", callback_data=f"bsn_log_{log_id}"),
            ]
        ]
    )


def get_fuel_oil_menu_keyboard(status_oli: dict[str, Any]) -> InlineKeyboardMarkup:
    """Tombol pada menu detail oli."""
    rows = []
    if status_oli.get("status") == "belum_diatur":
        rows.append([InlineKeyboardButton(text="✏️ Atur Km Terakhir Ganti Oli", callback_data="bsn_edit_oli_manual")])
    else:
        rows.append([InlineKeyboardButton(text="🛢️ Sudah Ganti Oli", callback_data="bsn_action_ganti_oli")])
        rows.append([InlineKeyboardButton(text="✏️ Ubah Km Terakhir Ganti Oli", callback_data="bsn_edit_oli_manual")])

    rows.append([InlineKeyboardButton(text="🔙 Kembali ke Menu Hub", callback_data="bsn_back_hub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_fuel_oil_confirm_keyboard(odo_akhir: float) -> InlineKeyboardMarkup:
    """Konfirmasi ganti oli apakah menggunakan angka km saat ini atau ketik manual."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Gunakan Odo Saat Ini ({odo_akhir:.0f} km)", callback_data=f"bsn_set_oli_cur_{odo_akhir}")],
            [InlineKeyboardButton(text="✏️ Ketik Angka Odo Manual", callback_data="bsn_edit_oli_manual")],
            [InlineKeyboardButton(text="❌ Batal", callback_data="bsn_menu_oli")],
        ]
    )


def get_fuel_register_same_oli_keyboard() -> InlineKeyboardMarkup:
    """Tombol opsi ganti oli sama dengan odometer awal saat daftar."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Sama dengan Odo Saat Ini", callback_data="bsn_reg_same_oli")]
        ]
    )

