"""
Helper pemformatan tampilan HTML murni untuk modul handler Logbook DERMAGA.
"""

import html
from typing import Any
from app.database.logbook_repo import PROFILE_DEFINITIONS
from app.services.logbook_service import format_reminder_days_display


def format_cli_config_block(public_url: str, token: str) -> str:
    """Menyusun blok <pre> JSON konfigurasi config.json CLI dengan HTML escaping."""
    return (
        "<pre>"
        "{\n"
        f'  "vps_endpoint": "{html.escape(str(public_url))}",\n'
        f'  "api_token": "{html.escape(str(token))}",\n'
        '  "location": "office"\n'
        "}"
        "</pre>"
    )


def build_unregistered_hub_text() -> str:
    """Menyusun teks HTML hub ketika akun DERMAGA pengguna belum tertaut."""
    return (
        "📖 <b>Pusat Kendali Logbook DERMAGA Polinema</b>\n\n"
        "⚠️ Akun DERMAGA Anda belum terhubung di bot ini.\n\n"
        "Gunakan perintah:\n"
        "<code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code>\n"
        "<i>Contoh:</i> <code>/daftar_logbook 2341720117 Rahasia123</code>\n"
        "<i>(Ketik tanpa tanda &lt; &gt;. Pesan otomatis dihapus demi keamanan).</i>"
    )


def build_daftar_success_text(username: str, token: str, public_url: str) -> str:
    """Menyusun teks HTML konfirmasi pendaftaran akun DERMAGA dan konfigurasi CLI."""
    return (
        f"🎉 <b>Pendaftaran Logbook DERMAGA Berhasil!</b>\n\n"
        f"👤 Akun: <code>{html.escape(username)}</code>\n"
        f"🔑 <b>API Token CLI Anda:</b>\n"
        f"<code>{html.escape(str(token))}</code>\n\n"
        f"📋 <b>Konfigurasi di Laptop / CLI Anda:</b>\n"
        f"Salin file <code>config.example.json</code> menjadi <code>config.json</code>, lalu sesuaikan:\n"
        + format_cli_config_block(public_url, token)
    )


def build_token_info_text(username: str, token: str, public_url: str) -> str:
    """Menyusun teks HTML informasi akun dan token CLI pengguna."""
    return (
        f"🔑 <b>Akun & API Token CLI Logbook Anda</b>\n\n"
        f"👤 <b>Username:</b> <code>{html.escape(username)}</code>\n"
        f"🔑 <b>API Token:</b>\n<code>{html.escape(str(token))}</code>\n\n"
        f"📋 <b>Konfigurasi di config.json:</b>\n"
        + format_cli_config_block(public_url, token)
    )


def build_hub_text(user: dict[str, Any], recent_drafts: list[dict[str, Any]]) -> str:
    """Menyusun teks HTML ringkasan akun dan draf terbaru untuk menu utama logbook."""
    username = html.escape(str(user["username"]))
    token = user.get("api_token", "-")
    short_token = f"{token[:8]}...{token[-4:]}" if token and len(token) > 12 else token
    reminder_time = user.get("reminder_time", "16:05")
    reminder_days = user.get("reminder_days", "0,1,2,3,4")
    active_prof = user.get("active_location_profile") or user.get("active_profile") or "office"
    prof_info = PROFILE_DEFINITIONS.get(active_prof, {})
    prof_name = html.escape(str(prof_info.get("default_name", active_prof.title())))

    drafts_text = ""
    if recent_drafts:
        drafts_text = "\n<b>Draf Logbook Terbaru:</b>\n"
        for d in recent_drafts:
            status_icon = "⏳" if d["status"] == "draft" else "✅"
            summary_short = html.escape(str(d["summary"])[:40])
            drafts_text += f"• {status_icon} <code>{html.escape(str(d['date']))}</code>: {summary_short}...\n"

    return (
        f"📖 <b>Pusat Kendali Logbook DERMAGA</b>\n\n"
        f"👤 <b>Pengguna:</b> <code>{username}</code>\n"
        f"🔑 <b>API Token:</b> <code>{html.escape(str(short_token))}</code>\n"
        f"⏰ <b>Jam Pengingat:</b> <b>{html.escape(str(reminder_time))} WIB</b>\n"
        f"🗓 <b>Jadwal Pengingat:</b> <b>{html.escape(format_reminder_days_display(reminder_days))}</b>\n"
        f"📍 <b>Profil Lokasi Aktif:</b> <b>{prof_name}</b>\n"
        f"{drafts_text}\n"
        f"Silakan pilih menu di bawah ini:"
    )


def render_verification_weeks_text(weeks_data: dict[str, Any]) -> str:
    """Menyusun teks HTML pengantar daftar kartu minggu untuk pengambilan link verifikasi."""
    pending = []
    completed = []
    for _, w in sorted(weeks_data.items(), reverse=True):
        v = w.get("verif")
        if not v:
            continue
        if v.get("link_supervisor") or v.get("link_dosen"):
            pending.append(w)
        elif v.get("pdf"):
            completed.append(w)

    text = "🔗 <b>Pusat Link Verifikasi Logbook DERMAGA</b>\n\n"
    if pending:
        text += (
            f"⏳ <b>{len(pending)} Minggu Menunggu Verifikasi:</b>\n"
            "Tautan siap dibagikan kepada Pembimbing Lapangan dan Dosen Pembimbing.\n\n"
        )
        for p in pending:
            lbl = html.escape(str(p.get("label", "Minggu")))
            rng = html.escape(str(p.get("rentang", "-")))
            text += f"• <b>{lbl}</b> (<code>{rng}</code>)\n"
        text += "\n<i>Ketuk kartu minggu di bawah untuk mengambil dan menyalin link verifikasi:</i>"
    elif completed:
        text += (
            "✅ <b>Tidak ada minggu yang sedang menunggu verifikasi saat ini.</b>\n"
            "Semua minggu yang telah diajukan sudah selesai diverifikasi secara lengkap.\n\n"
            "<i>Anda dapat melihat riwayat minggu sebelumnya atau mengunduh PDF di bawah ini:</i>"
        )
    else:
        text += (
            "ℹ️ <b>Belum ada logbook mingguan yang diajukan untuk verifikasi.</b>\n\n"
            "<i>Setelah Anda menandatangani draf mingguan di portal DERMAGA, "
            "link verifikasi untuk Supervisor dan Dosen Pembimbing akan otomatis muncul di sini.</i>"
        )

    return text


def render_verification_detail_text(week_info: dict[str, Any], parties: dict[str, str]) -> str:
    """Menyusun teks HTML detail link verifikasi dan status tanda tangan kartu minggu terpilih."""
    label = html.escape(str(week_info.get("label", "-")))
    rentang = html.escape(str(week_info.get("rentang", "-")))
    verif = week_info.get("verif") or {}

    ttd_mhs = verif.get("mahasiswa")
    ttd_spv = verif.get("supervisor")
    ttd_dos = verif.get("dosen")
    link_spv = verif.get("link_supervisor")
    link_dos = verif.get("link_dosen")
    pdf_url = verif.get("pdf")

    spv_name = parties.get("supervisor", "Pembimbing Lapangan")
    dos_name = parties.get("dosen", "Dosen Pembimbing")

    status_mhs = f"✅ Ditandatangani ({html.escape(str(ttd_mhs))})" if ttd_mhs else "⏳ Belum ditandatangani"
    status_spv = f"✅ Ditandatangani ({html.escape(str(ttd_spv))})" if ttd_spv else "⏳ Menunggu verifikasi"
    status_dos = f"✅ Ditandatangani ({html.escape(str(ttd_dos))})" if ttd_dos else "⏳ Menunggu verifikasi"

    text = (
        f"🔗 <b>LINK VERIFIKASI LOGBOOK DERMAGA</b>\n"
        f"🏷 <b>Minggu:</b> <b>{label}</b> (<code>{rentang}</code>)\n\n"
        f"📋 <b>Status Tanda Tangan:</b>\n"
        f"• Mahasiswa: {status_mhs}\n"
        f"• Supervisor: {status_spv}\n"
        f"• Dosen: {status_dos}\n\n"
    )

    has_links = False
    if link_spv:
        has_links = True
        text += (
            f"👤 <b>{html.escape(str(spv_name))}</b>\n"
            f"🔗 <b>Link Verifikasi:</b>\n"
            f"<code>{html.escape(str(link_spv))}</code>\n\n"
        )
    elif ttd_spv:
        text += f"👤 <b>{html.escape(str(spv_name))}:</b> ✅ <i>Sudah diverifikasi ({html.escape(str(ttd_spv))})</i>\n\n"

    if link_dos:
        has_links = True
        text += (
            f"🎓 <b>{html.escape(str(dos_name))}</b>\n"
            f"🔗 <b>Link Verifikasi:</b>\n"
            f"<code>{html.escape(str(link_dos))}</code>\n\n"
        )
    elif ttd_dos:
        text += f"🎓 <b>{html.escape(str(dos_name))}:</b> ✅ <i>Sudah diverifikasi ({html.escape(str(ttd_dos))})</i>\n\n"

    if has_links:
        text += (
            "💡 <i>Ketuk link di atas untuk menyalin langsung. Bagikan link ini (mis. lewat WhatsApp/email). "
            "Penerima dapat menandatangani tanpa perlu login.</i>"
        )
    elif pdf_url:
        text += (
            f"🎉 <b>Logbook minggu ini telah selesai diverifikasi lengkap!</b>\n"
            f"📄 Berkas PDF resmi telah diterbitkan oleh DERMAGA:\n"
            f"<code>{html.escape(str(pdf_url))}</code>"
        )
    else:
        text += (
            "ℹ️ <i>Link verifikasi belum aktif atau belum diterbitkan. "
            "Pastikan Anda telah menandatangani logbook mingguan di portal DERMAGA terlebih dahulu.</i>"
        )

    return text


def render_edit_detail_text(session: dict[str, Any]) -> str:
    """Menyusun teks tampilan detail entri logbook yang sedang diedit."""
    orig = session.get("original", {})
    tgl = html.escape(str(session.get("tanggal", "-")))
    web_id = html.escape(str(session.get("web_id", "-")))
    masuk = html.escape(str(session.get("jam_masuk", "07:10")))
    pulang = html.escape(str(session.get("jam_pulang", "16:25")))
    desk = html.escape(str(session.get("deskripsi", "-")))

    masuk_badge = " <i>(diubah)</i>" if session.get("jam_masuk", "07:10") != orig.get("jam_masuk") else ""
    pulang_badge = " <i>(diubah)</i>" if session.get("jam_pulang", "16:25") != orig.get("jam_pulang") else ""
    desk_badge = " <i>(diubah)</i>" if session.get("deskripsi") != orig.get("deskripsi") else ""

    text = (
        f"📝 <b>Detail Logbook Terpilih</b>\n\n"
        f"🗓 <b>Tanggal:</b> <code>{tgl}</code> (ID: <code>#{web_id}</code>)\n"
        f"⏰ <b>Jam Masuk:</b> <code>{masuk}</code>{masuk_badge}\n"
        f"⏰ <b>Jam Pulang:</b> <code>{pulang}</code>{pulang_badge}\n"
        f"📋 <b>Pekerjaan / Aktivitas:</b>{desk_badge}\n"
        f"<blockquote>{desk}</blockquote>\n\n"
    )
    if masuk_badge or pulang_badge or desk_badge:
        text += "💡 <i>Terdapat perubahan yang belum disimpan. Klik 'Simpan Perubahan' untuk mengonfirmasi ke DERMAGA.</i>"
    else:
        text += "<i>Pilih field di bawah jika Anda ingin mengubah jam kerja atau deskripsi pekerjaan:</i>"
    return text


def render_edit_confirm_text(session: dict[str, Any]) -> str:
    """Menyusun teks konfirmasi final sebelum menyimpan perubahan logbook lampau."""
    tgl = html.escape(str(session.get("tanggal", "-")))
    web_id = html.escape(str(session.get("web_id", "-")))
    masuk = html.escape(str(session.get("jam_masuk", "07:10")))
    pulang = html.escape(str(session.get("jam_pulang", "16:25")))
    desk = html.escape(str(session.get("deskripsi", "-")))

    return (
        f"📖 <b>Konfirmasi Perubahan Logbook DERMAGA</b>\n\n"
        f"🗓 <b>Tanggal:</b> <code>{tgl}</code> (ID: <code>#{web_id}</code>)\n"
        f"⏰ <b>Jam Kerja:</b> <code>{masuk} - {pulang} WIB</code>\n\n"
        f"📝 <b>Ringkasan Aktivitas Terbaru:</b>\n"
        f"<blockquote>{desk}</blockquote>\n\n"
        f"Silakan konfirmasi untuk memperbarui data pada portal DERMAGA:"
    )
