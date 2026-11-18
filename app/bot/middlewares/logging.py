"""
Middleware logging untuk merekam setiap pesan dan callback query yang masuk melalui Loguru.
"""

import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update
from app.core.logger import logger


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        start_time = time.perf_counter()
        target = event.event if isinstance(event, Update) else event

        user_id = "unknown"
        event_desc = type(target).__name__

        if isinstance(target, Message):
            user_id = str(target.from_user.id if target.from_user else target.chat.id)
            event_desc = f"Message: {target.text or target.content_type}"
        elif isinstance(target, CallbackQuery):
            user_id = str(target.from_user.id)
            event_desc = f"Callback: {target.data}"

        logger.debug(f"[UPDATE-IN] User {user_id} -> {event_desc}")

        try:
            result = await handler(event, data)
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.debug(f"[UPDATE-DONE] User {user_id} selesai dalam {elapsed:.2f}ms")
            return result
        except Exception as e:
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.error(f"[UPDATE-ERROR] User {user_id} ({event_desc}) gagal setelah {elapsed:.2f}ms: {e}")
            raise

