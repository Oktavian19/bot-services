"""
Utilitas bersama dan definisi FSM StatesGroup untuk sub-modul handler Logbook DERMAGA.
"""

import json
from typing import Any, Optional
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from app.services.logbook_service import validate_time_format


# --- FSM STATES ---

class LogbookManualFillFSM(StatesGroup):
    waiting_for_text = State()
    waiting_for_edit_text = State()


class LogbookEditSummaryFSM(StatesGroup):
    waiting_for_summary = State()


class LogbookSetJamFSM(StatesGroup):
    waiting_for_time = State()


class LogbookSetLocFSM(StatesGroup):
    waiting_for_location = State()


class LogbookEditPastFSM(StatesGroup):
    waiting_for_masuk = State()
    waiting_for_pulang = State()
    waiting_for_deskripsi = State()


# --- EVENT & UI HELPERS ---

async def unpack_event(event: Message | CallbackQuery) -> tuple[int, Optional[Message]]:
    """Mengekstrak chat_id dan target Message, serta menjawab CallbackQuery bila ada."""
    if isinstance(event, CallbackQuery):
        await event.answer()
        return event.from_user.id, event.message
    return event.chat.id, event


async def edit_or_answer(
    target: Optional[Message],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = "HTML",
) -> None:
    """Memperbarui pesan secara in-place atau mengirim pesan baru bila edit gagal."""
    if not target:
        return
    try:
        await target.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception:
        await target.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)


def normalize_time_hhmm(raw: str) -> Optional[str]:
    """Memvalidasi waktu format 24 jam HH:MM (00:00–23:59) dan menormalkan ke 2 digit."""
    val = (raw or "").strip()
    if not validate_time_format(val):
        return None
    h, m = val.split(":")
    return f"{int(h):02d}:{int(m):02d}"


def extract_override_id(raw_metadata: Any) -> Optional[str]:
    """Mengambil override_id dari metadata JSON draf logbook bila tersedia."""
    if not raw_metadata:
        return None
    try:
        meta = json.loads(raw_metadata) if isinstance(raw_metadata, str) else raw_metadata
        if isinstance(meta, dict):
            return meta.get("override_id")
        if isinstance(meta, list) and meta and isinstance(meta[0], dict):
            return meta[0].get("override_id")
    except Exception:
        return None
    return None
