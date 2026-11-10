"""
Middleware autentikasi dan pengecekan role administrator.
Menyuntikkan status 'is_admin: bool' ke dalam context data setiap handler.
"""

from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from app.core.config import get_settings


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        settings = get_settings()
        admin_chat_id = settings.ADMIN_CHAT_ID

        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else event.chat.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id

        # True jika tidak ada admin terkonfigurasi atau user_id cocok
        is_admin = bool(admin_chat_id is None or user_id == admin_chat_id)
        data["is_admin"] = is_admin
        data["admin_chat_id"] = admin_chat_id

        return await handler(event, data)

