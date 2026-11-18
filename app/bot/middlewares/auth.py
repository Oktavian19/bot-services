"""
Middleware autentikasi dan pengecekan role administrator.
Menyuntikkan status 'is_admin: bool' ke dalam context data setiap handler.
"""

from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update
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
        target = event.event if isinstance(event, Update) else event

        user_id = None
        chat_id = None
        if isinstance(target, Message):
            user_id = target.from_user.id if target.from_user else None
            chat_id = target.chat.id
        elif isinstance(target, CallbackQuery):
            user_id = target.from_user.id
            chat_id = target.message.chat.id if target.message else None
        elif data.get("event_from_user"):
            user_id = data["event_from_user"].id

        # True jika tidak ada admin terkonfigurasi atau user_id / chat_id cocok
        is_admin = bool(
            admin_chat_id is None
            or user_id == admin_chat_id
            or chat_id == admin_chat_id
        )
        data["is_admin"] = is_admin
        data["admin_chat_id"] = admin_chat_id

        return await handler(event, data)

