"""
HTTP API receiver server berbasis aiohttp.web asinkron.
Menerima draf logbook dari logbook-cli melalui endpoint /api/logbook dan meneruskannya ke Telegram bot.
"""

from typing import Optional
from aiogram import Bot
from aiohttp import web
from app.core.config import get_settings
from app.core.logger import logger
from app.database.logbook_repo import (
    create_or_get_draft,
    get_user_by_token,
    stop_reminder_for_today,
    update_telegram_message_info,
)
from app.services.logbook_service import format_draft_message

_bot_instance: Optional[Bot] = None


async def handle_health(request: web.Request) -> web.Response:
    """Endpoint health check: GET /api/health."""
    return web.json_response({
        "status": "healthy",
        "service": "bot-services-logbook",
        "multi_user": True,
        "framework": "aiohttp-async"
    })


async def handle_submit_draft(request: web.Request) -> web.Response:
    """Endpoint receiver draf logbook: POST /api/logbook."""
    settings = get_settings()

    # 1. Autentikasi Bearer Token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return web.json_response(
            {"error": "Unauthorized: Missing or invalid Bearer token header"},
            status=401
        )

    token = auth_header[7:].strip()
    user = await get_user_by_token(token)

    # Fallback ke master token admin jika ada
    if not user:
        admin_token = settings.LOGBOOK_API_TOKEN
        admin_chat = settings.ADMIN_CHAT_ID
        if admin_token and token == admin_token and admin_chat:
            user = {"chat_id": admin_chat, "username": "admin"}

    if not user:
        logger.warning(f"[LOGBOOK-API] Token tidak terdaftar: {token[:8]}...")
        return web.json_response(
            {"error": "Unauthorized: Token API tidak terdaftar di sistem bot. Gunakan /daftar_logbook di Telegram."},
            status=401
        )

    chat_id = user["chat_id"]

    # 2. Validasi Ukuran dan Parsing JSON
    try:
        payload = await request.json()
    except Exception as e:
        return web.json_response({"error": f"Malformed JSON: {e}"}, status=400)

    # 3. Validasi Field
    required_fields = ["date", "projects", "summary", "idempotency_key"]
    missing = [f for f in required_fields if f not in payload]
    if missing:
        return web.json_response(
            {"error": f"Missing required fields: {', '.join(missing)}"},
            status=400
        )

    date_str = str(payload["date"])
    projects = payload["projects"]
    summary = str(payload["summary"])
    idempotency_key = str(payload["idempotency_key"])
    commits = payload.get("commits", [])
    jam_masuk = str(payload.get("jam_masuk") or "07:10")
    jam_pulang = str(payload.get("jam_pulang") or "16:25")
    location_profile = payload.get("location") or payload.get("profile")

    # 4. Simpan atau Ambil Draf
    try:
        draft, is_new = await create_or_get_draft(
            chat_id=chat_id,
            idempotency_key=idempotency_key,
            date=date_str,
            projects=projects,
            commits_summary=summary,
            raw_metadata=commits,
            jam_masuk=jam_masuk,
            jam_pulang=jam_pulang,
            target_profile=location_profile,
        )

        # 5. Kirim Notifikasi ke Telegram jika bot instance tersedia
        if _bot_instance and is_new:
            try:
                from app.bot.keyboards.logbook import get_draft_approval_keyboard
                text = format_draft_message(draft, location_profile)
                markup = get_draft_approval_keyboard(draft["id"], draft.get("selected_profile", "office"))
                sent_msg = await _bot_instance.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=markup
                )
                await update_telegram_message_info(draft["id"], sent_msg.message_id)
                await stop_reminder_for_today(chat_id, date_str)
            except Exception as e:
                logger.error(f"[LOGBOOK-API] Gagal mengirim notifikasi draft ke Telegram: {e}")

        return web.json_response({
            "status": "success",
            "message": "Draft created" if is_new else "Existing draft retrieved",
            "draft_id": draft["id"],
            "is_new": is_new,
            "date": draft["date"]
        }, status=200)

    except Exception as e:
        logger.error(f"[LOGBOOK-API] Error saat menyimpan draf: {e}")
        return web.json_response({"error": f"Internal server error: {e}"}, status=500)


def create_api_app(bot: Bot) -> web.Application:
    """Membangun instance aiohttp.web.Application untuk HTTP receiver API logbook."""
    global _bot_instance
    _bot_instance = bot

    app = web.Application()
    app.router.add_get("/api/health", handle_health)
    app.router.add_post("/api/logbook", handle_submit_draft)
    return app


async def start_api_server(bot: Bot) -> web.AppRunner:
    """Menjalankan HTTP API receiver di event loop asyncio."""
    settings = get_settings()
    app = create_api_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.LOGBOOK_API_HOST, settings.LOGBOOK_API_PORT)
    await site.start()
    logger.info(
        f"[LOGBOOK-API] HTTP Receiver aktif di http://{settings.LOGBOOK_API_HOST}:{settings.LOGBOOK_API_PORT}/api/logbook"
    )
    return runner
