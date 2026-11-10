"""
Router Aiogram untuk modul Jaringan (/speedtest dan callback cb_speedtest).
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from app.core.logger import logger
from app.services.network_service import run_speedtest_async

router = Router(name="network_router")


async def execute_speedtest_flow(event_message: Message, chat_id: int, is_admin: bool) -> None:
    """Eksekusi alur speedtest dengan pengecekan hak akses admin."""
    logger.info(f"[JARINGAN] User {chat_id} meminta eksekusi /speedtest.")

    if not is_admin:
        logger.warning(f"[JARINGAN - WARNING] Akses /speedtest ditolak untuk User {chat_id} (Bukan Admin).")
        await event_message.reply("❌ Akses ditolak. Hanya Administrator yang bisa menjalankan perintah ini.")
        return

    loading_msg = await event_message.reply(
        "🚀 Sedang mengukur kecepatan internet server...\n<i>Mohon tunggu sekitar 20-30 detik ⏳</i>",
        parse_mode="HTML"
    )

    success, result = await run_speedtest_async()

    if success:
        logger.info(f"[JARINGAN] Speedtest berhasil dieksekusi untuk User {chat_id}.")
        balasan_akhir = f"📊 <b>Laporan Speedtest Server:</b>\n<pre><code>{result}</code></pre>"
    else:
        balasan_akhir = result

    try:
        await loading_msg.edit_text(balasan_akhir, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[JARINGAN] Gagal update teks hasil speedtest: {e}")
        await event_message.answer(balasan_akhir, parse_mode="HTML")


@router.message(Command("speedtest"))
async def cmd_speedtest(message: Message, is_admin: bool = False) -> None:
    """Command /speedtest (Admin only)."""
    await execute_speedtest_flow(message, message.chat.id, is_admin)


@router.callback_query(F.data == "cb_speedtest")
async def cb_speedtest_handler(callback: CallbackQuery, is_admin: bool = False) -> None:
    """Callback tombol Speedtest dari menu utama."""
    await callback.answer()
    if callback.message:
        await execute_speedtest_flow(callback.message, callback.from_user.id, is_admin)

