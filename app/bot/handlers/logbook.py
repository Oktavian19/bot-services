"""
Router Aiogram utama untuk modul Logbook DERMAGA Polinema.
Menggabungkan sub-router modular di logbook_modules/ tanpa perubahan antarmuka bagi main.py.
"""

from aiogram import Router
from app.bot.handlers.logbook_modules import (
    account,
    calendar_edit,
    calendar_nav,
    drafts,
    fill_reminder,
    location_settings,
    reminder_settings,
    web,
)

router = Router(name="logbook_router")
router.include_router(account.router)
router.include_router(web.router)
router.include_router(calendar_nav.router)
router.include_router(calendar_edit.router)
router.include_router(reminder_settings.router)
router.include_router(location_settings.router)
router.include_router(drafts.router)
router.include_router(fill_reminder.router)
