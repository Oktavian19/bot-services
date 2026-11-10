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


@router.message(Command("help"))
async def cmd_help(message: Message, is_admin: bool = False) -> None:
    """Menampilkan panduan lengkap perintah bot."""
    help_text = (
        "📖 <b>Panduan Lengkap Perintah Bot</b>\n\n"
        "🎛 <b>Umum & Server:</b>\n"
        "• /start — Tampilkan menu utama pusat kendali\n"
        "• /help — Tampilkan panduan lengkap perintah bot\n"
        "• /ping — Cek status konektivitas server\n\n"
        "🔔 <b>Pengingat & Agenda:</b>\n"
        "• /reminder — Buka hub pengingat dan daftar agenda aktif\n"
        "• /add_reminder — Tambah pengingat baru via wizard interaktif\n"
        "• /edit_reminder — Kelola dan perbarui jadwal pengingat\n\n"
        "⛽ <b>BBM & Kendaraan:</b>\n"
        "• /bensin — Dasbor konsumsi BBM, riwayat isi bensin & status oli\n\n"
        "📝 <b>Logbook DERMAGA:</b>\n"
        "• /logbook — Pusat kendali absensi & logbook DERMAGA\n"
        "• /isi_logbook — Isi atau edit logbook DERMAGA hari ini\n"
        "• /daftar_logbook <code>&lt;nim&gt; &lt;pass&gt;</code> — Hubungkan akun & terbitkan API token CLI\n"
        "• /token_logbook — Tampilkan token API untuk logbook-cli\n"
        "• /cek_logbook — Cek entri logbook langsung dari portal web\n"
        "• /set_jam_logbook <code>[HH:MM]</code> — Atur jam pengingat harian (default: 16:05)\n"
        "• /set_hari_logbook <code>[hari]</code> — Atur jadwal hari pengingat (misal: senin-jumat)\n"
        "• /set_lokasi_logbook — Atur profil koordinat GPS magang (kantor/rumah/lain)\n"
        "• /hapus_akun_logbook — Hapus akun dan kredensial dari sistem bot\n"
    )

    if is_admin:
        help_text += (
            "\n🛠 <b>Administrator:</b>\n"
            "• /speedtest — Ukur kecepatan internet server (Ookla)\n"
            "• /admin_logbook — Panel daftar seluruh pengguna logbook\n"
        )

    await message.answer(help_text, parse_mode="HTML")


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

