"""
Router Aiogram untuk modul Magang (Status: Diarsipkan / Nonaktif).
Disiapkan agar mudah diaktifkan kembali di masa mendatang tanpa merusak arsitektur baru.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

router = Router(name="magang_archived_router")


@router.message(Command("magang"))
@router.callback_query(F.data == "cb_magang")
async def cmd_magang_archived(event: Message | CallbackQuery) -> None:
    """Pemberitahuan bahwa modul magang saat ini berstatus arsip."""
    target_msg = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()

    text = (
        "🎓 <b>Pusat Pemantauan Magang</b>\n\n"
        "ℹ️ <i>Modul ini saat ini dalam status diarsipkan (nonaktif).</i>\n\n"
        "Untuk mengaktifkan kembali pemantauan status pendaftaran magang pada portal JTI, "
        "buka konfigurasi router di <code>main.py</code>."
    )
    await target_msg.answer(text, parse_mode="HTML")

