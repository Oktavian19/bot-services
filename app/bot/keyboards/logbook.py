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
            InlineKeyboardButton(text="✍️ Isi Logbook", callback_data="log_menu_isi"),
            InlineKeyboardButton(text="🔗 Link Verifikasi", callback_data="log_menu_link_verif"),
        ],
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


def get_month_calendar_keyboard(current_month: str, months_list: list, month_entries: list) -> InlineKeyboardMarkup:
    """Membuat keyboard inline grid 3 kolom untuk tanggal logbook dan navigasi bulan."""
    from app.services.logbook_service import format_short_date

    rows = []
    # 1. Grid tanggal (3 tombol per baris)
    row = []
    for entry in month_entries:
        web_id = entry.get("web_id")
        if not web_id:
            continue
        tgl_short = format_short_date(entry.get("tanggal_iso", "") or entry.get("tanggal_text", ""))
        row.append(InlineKeyboardButton(text=f"📅 {tgl_short}", callback_data=f"log_edpick_{web_id}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # 2. Baris Navigasi Bulan
    nav_row = []
    if current_month in months_list:
        curr_idx = months_list.index(current_month)
        if curr_idx + 1 < len(months_list):
            prev_m = months_list[curr_idx + 1]
            nav_row.append(InlineKeyboardButton(text="⬅️ Bulan Sebelumnya", callback_data=f"log_edmonth_{prev_m}"))
        if curr_idx - 1 >= 0:
            next_m = months_list[curr_idx - 1]
            nav_row.append(InlineKeyboardButton(text="Bulan Berikutnya ➡️", callback_data=f"log_edmonth_{next_m}"))
    if nav_row:
        rows.append(nav_row)

    # 3. Tombol Kembali
    rows.append([InlineKeyboardButton(text="⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_edit_detail_keyboard(any_changed: bool) -> InlineKeyboardMarkup:
    """Membuat keyboard tombol aksi pengubahan field logbook dan submit ke DERMAGA."""
    rows = [
        [
            InlineKeyboardButton(text="⏰ Ubah Jam Masuk", callback_data="log_edact_masuk"),
            InlineKeyboardButton(text="⏰ Ubah Jam Pulang", callback_data="log_edact_pulang"),
        ],
        [
            InlineKeyboardButton(text="📝 Ubah Pekerjaan", callback_data="log_edact_desk"),
        ],
        [
            InlineKeyboardButton(
                text="💾 Simpan Perubahan" if any_changed else "💾 Simpan (Belum Ada Perubahan)",
                callback_data="log_edact_save",
            )
        ],
        [
            InlineKeyboardButton(text="⬅️ Pilih Tanggal Lain", callback_data="log_edact_backmonth"),
            InlineKeyboardButton(text="❌ Batal", callback_data="log_edact_cancel"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_verification_weeks_keyboard(weeks_data: dict[str, Any]) -> InlineKeyboardMarkup:
    """Menyusun keyboard pilihan kartu minggu untuk melihat tautan verifikasi."""
    rows = []

    pending_weeks = []
    completed_weeks = []

    for k, w in sorted(weeks_data.items(), reverse=True):
        verif = w.get("verif")
        if not verif:
            continue
        if verif.get("link_supervisor") or verif.get("link_dosen"):
            pending_weeks.append(w)
        elif verif.get("pdf"):
            completed_weeks.append(w)

    # 1. Minggu yang sedang menunggu verifikasi (prioritas teratas)
    for pw in pending_weeks:
        label = pw.get("label", "Minggu")
        rentang = pw.get("rentang", "")
        short_rentang = rentang.split("-")[0].strip() if "-" in rentang else rentang
        rows.append([
            InlineKeyboardButton(
                text=f"⏳ {label} ({short_rentang}) [Menunggu]",
                callback_data=f"log_verif_{pw.get('awal')}",
            )
        ])

    # 2. Riwayat minggu yang sudah terverifikasi (tampilkan hingga 6 minggu terbaru, 2 per baris)
    comp_row = []
    for cw in completed_weeks[:6]:
        label = cw.get("label", "Minggu")
        comp_row.append(
            InlineKeyboardButton(
                text=f"✅ {label}",
                callback_data=f"log_verif_{cw.get('awal')}",
            )
        )
        if len(comp_row) == 2:
            rows.append(comp_row)
            comp_row = []
    if comp_row:
        rows.append(comp_row)

    # 3. Baris Aksi Navigasi
    rows.append([
        InlineKeyboardButton(text="🔄 Refresh Data", callback_data="log_verif_refresh"),
        InlineKeyboardButton(text="⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_verification_detail_keyboard(
    week_info: dict[str, Any],
    parties: dict[str, str],
) -> InlineKeyboardMarkup:
    """Menyusun keyboard tombol buka link verifikasi eksternal dan navigasi kembali."""
    rows = []
    verif = week_info.get("verif") or {}
    link_spv = verif.get("link_supervisor")
    link_dos = verif.get("link_dosen")
    pdf_url = verif.get("pdf")

    if link_spv and str(link_spv).startswith("http"):
        rows.append([InlineKeyboardButton(text="🌐 Buka Link Supervisor", url=str(link_spv))])
    if link_dos and str(link_dos).startswith("http"):
        rows.append([InlineKeyboardButton(text="🌐 Buka Link Dosen", url=str(link_dos))])
    if pdf_url and str(pdf_url).startswith("http"):
        rows.append([InlineKeyboardButton(text="📥 Download PDF Logbook", url=str(pdf_url))])

    rows.append([
        InlineKeyboardButton(text="⬅️ Pilih Minggu Lain", callback_data="log_menu_link_verif"),
        InlineKeyboardButton(text="⬅️ Menu Logbook", callback_data="log_menu_back"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)



