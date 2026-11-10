"""
Entrypoint modern aplikasi bot-services.
Dibangun menggunakan aiogram v3 (asyncio native), Pydantic Settings, Loguru,
APScheduler, aiohttp web server receiver, dan penanganan sinyal Graceful Shutdown.
"""

import asyncio
import signal
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from aiohttp import web
from app.bot.handlers import (
    admin,
    common,
    fuel,
    logbook,
    magang_archived,
    network,
    reminder,
)
from app.bot.middlewares.auth import AuthMiddleware
from app.bot.middlewares.logging import LoggingMiddleware
from app.bot.middlewares.throttling import ThrottlingMiddleware
from app.core.config import get_settings
from app.core.logger import logger, setup_logger
from app.database.fuel_repo import init_fuel_db
from app.database.logbook_repo import init_logbook_db
from app.database.reminder_repo import init_reminder_db
from app.services.logbook_api import start_api_server
from app.services.scheduler import start_scheduler_and_tasks, stop_scheduler_and_tasks


async def setup_bot_commands(bot: Bot) -> None:
    """Mendaftarkan menu rekomendasi perintah Telegram lengkap dengan pemisahan scope pengguna dan admin."""
    settings = get_settings()

    user_commands = [
        BotCommand(command="start", description="Tampilkan menu utama pusat kendali"),
        BotCommand(command="help", description="Panduan lengkap perintah bot"),
        BotCommand(command="ping", description="Cek status konektivitas server"),
        BotCommand(command="reminder", description="Pusat kendali pengingat & agenda"),
        BotCommand(command="add_reminder", description="Tambah pengingat baru"),
        BotCommand(command="edit_reminder", description="Kelola & edit pengingat aktif"),
        BotCommand(command="bensin", description="Catatan konsumsi BBM & status oli"),
        BotCommand(command="logbook", description="Pusat kendali logbook DERMAGA"),
        BotCommand(command="isi_logbook", description="Isi logbook DERMAGA hari ini"),
        BotCommand(command="daftar_logbook", description="Pendaftaran akun DERMAGA"),
        BotCommand(command="token_logbook", description="Kelola API token CLI logbook"),
        BotCommand(command="cek_logbook", description="Cek tabel logbook web DERMAGA"),
        BotCommand(command="set_jam_logbook", description="Atur jam pengingat harian"),
        BotCommand(command="set_hari_logbook", description="Atur jadwal hari pengingat"),
        BotCommand(command="set_lokasi_logbook", description="Atur profil koordinat GPS magang"),
        BotCommand(command="hapus_akun_logbook", description="Hapus akun & data logbook"),
    ]

    # Daftarkan scope default untuk seluruh pengguna
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    logger.info(f"[BOT] {len(user_commands)} perintah reguler berhasil didaftarkan ke scope default Telegram!")

    # Jika ADMIN_CHAT_ID dikonfigurasi, daftarkan menu khusus admin (termasuk speedtest & admin_logbook)
    if settings.ADMIN_CHAT_ID:
        admin_commands = user_commands + [
            BotCommand(command="speedtest", description="Ukur kecepatan internet server"),
            BotCommand(command="admin_logbook", description="Panel admin pengguna logbook"),
        ]
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=settings.ADMIN_CHAT_ID))
            logger.info(f"[BOT] {len(admin_commands)} perintah admin berhasil didaftarkan untuk chat {settings.ADMIN_CHAT_ID}!")
        except Exception as e:
            logger.warning(f"[BOT] Gagal mendaftarkan menu khusus admin: {e}")


async def main() -> None:
    """Fungsi orkestrasi utama asinkron."""
    # 1. Inisialisasi Logger Terpusat
    setup_logger()
    logger.info("Memulai inisialisasi bot-services (aiogram v3 native)...")

    # 2. Muat Konfigurasi via Pydantic Settings
    settings = get_settings()

    # 3. Inisialisasi Database SQLite (Async Non-Destruktif)
    logger.info("Menginisialisasi basis data SQLite asinkron...")
    await init_reminder_db()
    await init_fuel_db()
    await init_logbook_db()

    # 4. Inisialisasi Bot & Dispatcher
    bot = Bot(
        token=settings.TELEGRAM_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # 5. Pasang Middlewares
    dp.update.outer_middleware(LoggingMiddleware())
    dp.update.middleware(AuthMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware(rate_limit_seconds=0.4))

    # 6. Registrasi Routers Modular
    dp.include_router(common.router)
    dp.include_router(network.router)
    dp.include_router(reminder.router)
    dp.include_router(fuel.router)
    dp.include_router(logbook.router)
    dp.include_router(admin.router)
    dp.include_router(magang_archived.router)

    # 7. Setup Perintah Bot
    await setup_bot_commands(bot)

    # 8. Jalankan Background Schedulers (APScheduler & Network Monitor Task)
    scheduler = start_scheduler_and_tasks(bot)

    # 9. Jalankan HTTP API Receiver Server (aiohttp.web untuk logbook CLI)
    api_runner: web.AppRunner = await start_api_server(bot)

    # 10. Konfigurasi Graceful Shutdown
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler(sig_name: str) -> None:
        logger.warning(f"Sinyal {sig_name} diterima. Memulai proses graceful shutdown...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig.name: _signal_handler(s))
        except (NotImplementedError, RuntimeError):
            # Fallback untuk platform/lingkungan tanpa add_signal_handler
            pass

    logger.info("Telegram Bot siap dan berjalan (Polling mode aktif)...")

    # Jalankan polling bersamaan dengan pemantau sinyal shutdown
    polling_task = asyncio.create_task(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        name="telegram_polling_task",
    )

    # Tunggu sinyal shutdown
    await stop_event.wait()

    # --- PROSES CLEANUP / SHUTDOWN ---
    logger.info("Menghentikan polling Telegram...")
    await dp.stop_polling()
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass

    logger.info("Mematikan background scheduler...")
    await stop_scheduler_and_tasks(scheduler)

    logger.info("Mematikan HTTP API receiver server...")
    await api_runner.cleanup()

    logger.info("Menutup sesi HTTP client bot...")
    await bot.session.close()

    logger.info("Aplikasi bot-services berhasil dimatikan secara bersih (Graceful Shutdown selesai).")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
