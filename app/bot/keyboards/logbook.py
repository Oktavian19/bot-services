"""
Keyboard inline untuk seluruh navigasi dan interaksi modul Logbook.
"""

from typing import Any, List, Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.database.logbook_repo import PROFILE_DEFINITIONS


def get_logbook_hub_keyboard(is_admin_user: bool = False) -> InlineKeyboardMarkup:
    """Menu utama kendali logbook."""
    rows = [
        [
            InlineKeyboardButton(text="📋 Cek Logbook Web", callback_data="log_menu_cek"),
            InlineKeyboardButton(text="📅 Kalender & Edit", callback_data="log_menu_edit"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Pengaturan", callback_data="log_menu_settings"),
            InlineKeyboardButton(text="📍 Lokasi GPS", callback_data="log_menu_set_lokasi"),
        ],
        [
            InlineKeyboardButton(text="🔑 Akun & Token CLI", callback_data="log_menu_account"),
        ],
    ]

    if is_admin_user:
        rows.append([InlineKeyboardButton(text="👥 Admin Panel", callback_data="log_menu_admin_users")])

    rows.append([InlineKeyboardButton(text="🔄 Refresh", callback_data="log_menu_refresh")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_draft_approval_keyboard(draft_id: int, selected_profile: str = "office") -> InlineKeyboardMarkup:
    """Keyboard interaktif persetujuan draf logbook."""
    p_info = PROFILE_DEFINITIONS.get(selected_profile, {})
    p_label = p_info.get("label", selected_profile.title())

    # Siklus pergantian profil lokasi (office -> home -> other -> office)
    next_profile_map = {"office": "home", "home": "other", "other": "office"}
    next_profile = next_profile_map.get(selected_profile, "office")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Setujui & Kirim ke DERMAGA",
                    callback_data=f"log_confirm_{draft_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"📍 Lokasi: {p_label} (Ganti)",
                    callback_data=f"log_draft_loc_{draft_id}_{next_profile}",
                )
            ],
            [
                InlineKeyboardButton(text="✏️ Edit Ringkasan", callback_data=f"log_edit_{draft_id}"),
                InlineKeyboardButton(text="❌ Batalkan", callback_data=f"log_cancel_{draft_id}"),
            ],
        ]
    )


def get_locations_menu_keyboard(profiles: List[dict[str, Any]], active_key: str) -> InlineKeyboardMarkup:
    """Menu konfigurasi profil lokasi GPS."""
    rows = []
    # Baris tombol pemilihan profil aktif
    switch_btns = []
    for p_key in ("office", "home", "other"):
        p_def = PROFILE_DEFINITIONS.get(p_key, {})
        icon = p_def.get("icon", "📍")
        label = p_def.get("label", p_key.title())
        is_active = (p_key == active_key)
        btn_text = f"🔘 {icon} {label}" if is_active else f"⚪ {icon} {label}"
        switch_btns.append(InlineKeyboardButton(text=btn_text, callback_data=f"log_loc_switch_{p_key}"))
    rows.append(switch_btns)

    # Baris tombol edit koordinat per profil
    for p_key in ("office", "home", "other"):
        p_def = PROFILE_DEFINITIONS.get(p_key, {})
        rows.append([InlineKeyboardButton(
            text=f"✏️ Atur Koordinat {p_def.get('label', p_key)}",
            callback_data=f"log_loc_edit_{p_key}"
        )])

    rows.append([InlineKeyboardButton(text="📖 Kembali ke Menu Logbook", callback_data="log_menu_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_settings_menu_keyboard() -> InlineKeyboardMarkup:
    """Menu pengaturan jam dan hari pengingat."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏰ Atur Jam Pengingat", callback_data="log_menu_set_jam"),
                InlineKeyboardButton(text="🗓 Atur Hari Pengingat", callback_data="log_menu_set_hari"),
            ],
            [
                InlineKeyboardButton(text="📖 Kembali ke Menu Logbook", callback_data="log_menu_back")
            ],
        ]
    )


def get_reminder_days_checklist_keyboard(active_days_str: str) -> InlineKeyboardMarkup:
    """Checklist tombol interaktif pemilihan hari aktif pengingat."""
    active_indices = set(int(x.strip()) for x in active_days_str.split(",") if x.strip().isdigit())
    nama_hari = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

    rows = []
    # Tombol toggle hari 0-6 (2 kolom per baris)
    day_btns = []
    for idx, name in enumerate(nama_hari):
        checked = "✅" if idx in active_indices else "⬜"
        day_btns.append(InlineKeyboardButton(text=f"{checked} {name}", callback_data=f"log_daytg_{idx}"))
        if len(day_btns) == 2 or idx == 6:
            rows.append(day_btns)
            day_btns = []

    # Preset Cepat
    rows.append([
        InlineKeyboardButton(text="🏢 Senin - Jumat", callback_data="log_dayps_weekdays"),
        InlineKeyboardButton(text="📅 Setiap Hari", callback_data="log_dayps_all"),
    ])
    rows.append([
        InlineKeyboardButton(text="🔕 Nonaktifkan", callback_data="log_dayps_none"),
    ])
    rows.append([
        InlineKeyboardButton(text="💾 Selesai / Simpan", callback_data="log_menu_settings")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_back_to_logbook_keyboard() -> InlineKeyboardMarkup:
    """Tombol kembali ke menu logbook."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back")]
        ]
    )

