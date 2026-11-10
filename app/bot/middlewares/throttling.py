"""
Middleware pembatasan laju klik (throttling / anti-flood).
"""

import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit_seconds: float = 0.5):
        self.rate_limit_seconds = rate_limit_seconds
        self.last_user_activity: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        if isinstance(event, CallbackQuery):
            user_id = event.from_user.id
            now = time.time()
            last_time = self.last_user_activity.get(user_id, 0.0)

            if now - last_time < self.rate_limit_seconds:
                await event.answer("⏳ Terlalu cepat, mohon tunggu sejenak.", show_alert=False)
                return None

            self.last_user_activity[user_id] = now

        return await handler(event, data)

