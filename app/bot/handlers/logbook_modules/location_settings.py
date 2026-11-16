"""
Sub-router Logbook untuk pengaturan profil lokasi GPS magang.
"""

import html
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from app.bot.handlers.logbook_modules.shared import LogbookSetLocFSM, unpack_event
from app.bot.keyboards.logbook import get_back_to_logbook_keyboard, get_locations_menu_keyboard
from app.database.logbook_repo import (
    PROFILE_DEFINITIONS,
    get_active_location_profile,
    get_user_location_profiles,
    save_location_profile,
    set_active_location_profile,
)
from app.services.logbook_service import parse_coordinates_input

router = Router(name="logbook_location_settings_router")


@router.message(Command("set_lokasi_logbook", "lokasi_logbook", "set_gps_logbook"))
@router.callback_query(F.data == "log_menu_set_lokasi")
async def cmd_set_lokasi(event: Message | CallbackQuery) -> None:
    """Menampilkan menu profil lokasi GPS magang."""
    chat_id, target_msg = await unpack_event(event)
    if not target_msg:
        return

    profiles = await get_user_location_profiles(chat_id)
    active_profile = await get_active_location_profile(chat_id)

    text = "📍 <b>Pengaturan Profil Lokasi GPS Magang</b>\n\n"
    for p in profiles:
        p_key = p["profile_key"]
        p_def = PROFILE_DEFINITIONS.get(p_key, {})
        icon = p_def.get("icon", "📍")
        label = html.escape(str(p_def.get("label", p_key.title())))
        status_tag = " <b>[AKTIF]</b>" if p_key == active_profile else ""
        maps_url = f"https://www.google.com/maps?q={p['latitude']},{p['longitude']}"
        text += (
            f"{icon} <b>{label}</b>{status_tag}\n"
            f"   Koordinat: <a href=\"{maps_url}\"><code>{p['latitude']}, {p['longitude']}</code></a> (±{p['accuracy']}m)\n\n"
        )
    text += "Klik tombol di bawah untuk berganti profil aktif atau mengatur koordinat baru:"
    await target_msg.answer(text, parse_mode="HTML", reply_markup=get_locations_menu_keyboard(profiles, active_profile))


@router.callback_query(F.data.startswith("log_loc_switch_"))
async def cb_switch_location_profile(callback: CallbackQuery) -> None:
    """Ganti profil lokasi aktif."""
    await callback.answer()
    p_key = callback.data.split("_")[3]
    await set_active_location_profile(callback.from_user.id, p_key)
    profiles = await get_user_location_profiles(callback.from_user.id)
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=get_locations_menu_keyboard(profiles, p_key))
        except Exception:
            pass


@router.callback_query(F.data.startswith("log_loc_edit_"))
async def cb_start_edit_location(callback: CallbackQuery, state: FSMContext) -> None:
    """Minta input koordinat baru untuk profil lokasi."""
    await callback.answer()
    p_key = callback.data.split("_")[3]
    p_def = PROFILE_DEFINITIONS.get(p_key, {})
    await state.set_state(LogbookSetLocFSM.waiting_for_location)
    await state.update_data(target_profile=p_key)
    if callback.message:
        await callback.message.answer(
            f"📍 <b>Atur Lokasi {html.escape(str(p_def.get('label', p_key)))}</b>\n\n"
            "Silakan kirimkan salah satu di bawah ini:\n"
            "• 📎 Share pin lokasi langsung dari Telegram (Live Location)\n"
            "• Angka koordinat: <code>-7.9467, 112.6156</code>\n"
            "• Tautan Google Maps tempat magang.",
            parse_mode="HTML",
        )


async def _save_location_and_reply(
    message: Message,
    state: FSMContext,
    profile_key: str,
    lat: float,
    lng: float,
    accuracy: float,
) -> None:
    """Menyimpan koordinat lokasi ke database dan mengirim konfirmasi tautan Google Maps."""
    lat_str, lng_str = f"{lat:.6f}", f"{lng:.6f}"
    acc_str = f"{int(round(accuracy))}"
    await state.clear()
    await save_location_profile(message.chat.id, profile_key, lat_str, lng_str, acc_str)
    maps_url = f"https://www.google.com/maps?q={lat_str},{lng_str}"
    await message.answer(
        f"✅ <b>Lokasi GPS Berhasil Diperbarui!</b>\n\n"
        f"📍 Koordinat: <a href=\"{maps_url}\"><code>{lat_str}, {lng_str}</code></a> (±{acc_str}m)",
        parse_mode="HTML",
        reply_markup=get_back_to_logbook_keyboard(),
    )


@router.message(LogbookSetLocFSM.waiting_for_location)
async def process_location_input(message: Message, state: FSMContext) -> None:
    """Menerima kiriman koordinat GPS pin Telegram, teks angka, atau URL Google Maps."""
    data = await state.get_data()
    p_key = data.get("target_profile", "office")

    if message.location:
        await _save_location_and_reply(
            message,
            state,
            p_key,
            message.location.latitude,
            message.location.longitude,
            message.location.horizontal_accuracy or 15.0,
        )
        return

    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pengaturan lokasi dibatalkan.")
        return

    parsed = parse_coordinates_input(message.text)
    if not parsed:
        await message.answer(
            "❌ Format koordinat tidak dikenali. Masukkan contoh: <code>-7.9467, 112.6156</code>",
            parse_mode="HTML",
        )
        return

    await _save_location_and_reply(message, state, p_key, *parsed)
