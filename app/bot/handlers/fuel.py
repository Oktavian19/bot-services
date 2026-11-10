"""
Router Aiogram untuk modul BBM & Motor (/bensin).
Mengelola pendaftaran motor, pencatatan transaksi BBM, riwayat, recalculation, dan interval ganti oli.
"""

from typing import Optional
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from app.bot.keyboards.fuel import (
    get_fuel_hub_keyboard,
    get_fuel_log_delete_confirm_keyboard,
    get_fuel_log_detail_keyboard,
    get_fuel_logs_keyboard,
    get_fuel_oil_confirm_keyboard,
    get_fuel_oil_menu_keyboard,
    get_fuel_price_keyboard,
    get_fuel_register_same_oli_keyboard,
    get_skip_odo_keyboard,
)
from app.core.logger import logger
from app.database.fuel_repo import (
    add_log_bensin,
    delete_log_bensin,
    get_log_bensin_by_id,
    get_logs_bensin,
    get_motor,
    get_statistik_bensin,
    get_status_oli,
    register_motor,
    update_log_bensin,
    update_odometer_oli,
)
from app.services.fuel_service import (
    render_fuel_hub_text,
    render_log_detail_text,
    render_oil_menu_text,
)

router = Router(name="fuel_router")


# --- FSM STATES ---

class MotorRegisterFSM(StatesGroup):
    waiting_for_name = State()
    waiting_for_odo = State()
    waiting_for_oil_odo = State()


class FuelRefillFSM(StatesGroup):
    waiting_for_odo = State()
    waiting_for_rupiah = State()
    waiting_for_price = State()


class FuelEditFSM(StatesGroup):
    waiting_for_odo = State()
    waiting_for_rupiah = State()
    waiting_for_price = State()


class FuelOilFSM(StatesGroup):
    waiting_for_manual_odo = State()


# --- HUB /BENSIN ---

async def show_bensin_hub(target: Message, chat_id: int) -> None:
    """Menampilkan dasbor hub bensin & motor."""
    logger.info(f"[BENSIN] User {chat_id} mengakses menu hub bensin.")
    motor = await get_motor(chat_id)
    stats = await get_statistik_bensin(chat_id)
    status_oli = await get_status_oli(chat_id)

    text = render_fuel_hub_text(motor, stats, status_oli)
    markup = get_fuel_hub_keyboard(motor_exists=bool(motor), status_oli=status_oli)
    await target.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(Command("bensin"))
async def cmd_bensin(message: Message) -> None:
    """Command /bensin."""
    await show_bensin_hub(message, message.chat.id)


@router.callback_query(F.data == "cb_bensin")
@router.callback_query(F.data == "bsn_back_hub")
async def cb_bensin_hub(callback: CallbackQuery) -> None:
    """Navigasi ke hub bensin."""
    await callback.answer()
    if callback.message:
        await show_bensin_hub(callback.message, callback.from_user.id)


# --- FLOW PENDAFTARAN MOTOR (FSM) ---

@router.callback_query(F.data == "bsn_daftar")
async def start_register_motor(callback: CallbackQuery, state: FSMContext) -> None:
    """Memulai alur pendaftaran motor."""
    await callback.answer()
    await state.clear()
    await state.set_state(MotorRegisterFSM.waiting_for_name)
    if callback.message:
        await callback.message.answer("Kirimkan nama/merek motor Anda (contoh: Vario 125 2013):")


@router.message(MotorRegisterFSM.waiting_for_name)
async def process_motor_name(message: Message, state: FSMContext) -> None:
    """Menerima nama motor."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pendaftaran dibatalkan.")
        return

    nama_motor = message.text.strip()
    await state.update_data(nama_motor=nama_motor)
    await state.set_state(MotorRegisterFSM.waiting_for_odo)
    await message.answer(f"Berapa Odometer saat ini pada motor {nama_motor}? (Ketik angka saja, contoh: 45000):")


@router.message(MotorRegisterFSM.waiting_for_odo)
async def process_motor_odo(message: Message, state: FSMContext) -> None:
    """Menerima odometer awal motor."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pendaftaran dibatalkan.")
        return

    try:
        odo_awal = float(message.text.strip().replace(",", "."))
        await state.update_data(odo_awal=odo_awal)
        await state.set_state(MotorRegisterFSM.waiting_for_oil_odo)

        markup = get_fuel_register_same_oli_keyboard()
        await message.answer(
            f"🛢 <b>Jadwal Ganti Oli Motor</b>\n\n"
            f"Di angka odometer berapa motor terakhir kali ganti oli?\n"
            f"<i>(Ketik angka odometer, atau klik tombol di bawah jika baru saja ganti oli pada odo {odo_awal:.0f} km)</i>:",
            parse_mode="HTML",
            reply_markup=markup,
        )
    except ValueError:
        await message.answer("⚠️ Odometer harus berupa angka (contoh: 45000.5). Pendaftaran dibatalkan.")
        await state.clear()


@router.callback_query(F.data == "bsn_reg_same_oli", MotorRegisterFSM.waiting_for_oil_odo)
async def process_same_oil_button(callback: CallbackQuery, state: FSMContext) -> None:
    """Opsi ganti oli sama dengan odometer awal."""
    await callback.answer()
    data = await state.get_data()
    await state.clear()

    nama_motor = data.get("nama_motor")
    odo_awal = data.get("odo_awal")
    chat_id = callback.from_user.id

    if nama_motor and odo_awal is not None:
        await register_motor(chat_id, nama_motor, odo_awal, odo_awal)
        if callback.message:
            await callback.message.answer(
                f"✅ <b>Motor {nama_motor} berhasil didaftarkan!</b>\n\n"
                f"📟 Odometer awal: <b>{odo_awal:.1f} km</b>\n"
                f"🛢 Terakhir ganti oli: <b>{odo_awal:.1f} km</b>\n"
                f"🎯 Jadwal ganti oli berikutnya: <b>{odo_awal + 3000.0:.1f} km</b>\n\n"
                f"Ketik /bensin saat Anda berada di SPBU.",
                parse_mode="HTML"
            )


@router.message(MotorRegisterFSM.waiting_for_oil_odo)
async def process_motor_oil_odo(message: Message, state: FSMContext) -> None:
    """Menerima angka odometer ganti oli secara manual saat pendaftaran."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pendaftaran dibatalkan.")
        return

    try:
        odo_oli = float(message.text.strip().replace(",", "."))
        data = await state.get_data()
        await state.clear()

        nama_motor = data["nama_motor"]
        odo_awal = data["odo_awal"]

        await register_motor(message.chat.id, nama_motor, odo_awal, odo_oli)
        await message.answer(
            f"✅ <b>Motor {nama_motor} berhasil didaftarkan!</b>\n\n"
            f"📟 Odometer awal: <b>{odo_awal:.1f} km</b>\n"
            f"🛢 Terakhir ganti oli: <b>{odo_oli:.1f} km</b>\n"
            f"🎯 Jadwal ganti oli berikutnya: <b>{odo_oli + 3000.0:.1f} km</b>\n\n"
            f"Ketik /bensin saat Anda berada di SPBU.",
            parse_mode="HTML"
        )
    except ValueError:
        await state.clear()
        await message.answer("⚠️ Odometer oli harus berupa angka (contoh: 44000). Pendaftaran dibatalkan.")


# --- FLOW ISI BENSIN (FSM) ---

@router.callback_query(F.data == "bsn_isi")
async def start_fill_fuel(callback: CallbackQuery, state: FSMContext) -> None:
    """Memulai alur pengisian bensin di SPBU."""
    await callback.answer()
    await state.clear()
    await state.set_state(FuelRefillFSM.waiting_for_odo)
    markup = get_skip_odo_keyboard()
    if callback.message:
        await callback.message.answer(
            "Berapa angka Odometer Anda saat ini di SPBU?\n"
            "<i>(Ketik angka, contoh: 45000, atau klik tombol di bawah jika lupa/tanpa odo)</i>:",
            parse_mode="HTML",
            reply_markup=markup,
        )


@router.callback_query(F.data == "bsn_skip_odo", FuelRefillFSM.waiting_for_odo)
async def skip_odo_button(callback: CallbackQuery, state: FSMContext) -> None:
    """Tombol lewati odometer pada pengisian bensin."""
    await callback.answer()
    await state.update_data(odo_sekarang=None)
    await state.set_state(FuelRefillFSM.waiting_for_rupiah)
    if callback.message:
        await callback.message.answer(
            "Berapa nominal Rupiah bensin yang Anda beli? (Hanya angka tanpa titik, misal: 25000):"
        )


@router.message(FuelRefillFSM.waiting_for_odo)
async def process_fill_odo(message: Message, state: FSMContext) -> None:
    """Menerima angka odometer di SPBU atau tanda lewati."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pengisian dibatalkan.")
        return

    txt = message.text.strip().lower()
    if txt in ("-", "skip", "lewati", "0", "tidak", "lupa"):
        odo_val = None
    else:
        try:
            odo_val = float(txt.replace(",", "."))
        except ValueError:
            await state.clear()
            await message.answer("⚠️ Odometer harus angka desimal/bulat (contoh: 45000.5) atau '-' jika tanpa odo. Dibatalkan.")
            return

    await state.update_data(odo_sekarang=odo_val)
    await state.set_state(FuelRefillFSM.waiting_for_rupiah)
    await message.answer("Berapa nominal Rupiah bensin yang Anda beli? (Hanya angka tanpa titik, misal: 25000):")


@router.message(FuelRefillFSM.waiting_for_rupiah)
async def process_fill_rupiah(message: Message, state: FSMContext) -> None:
    """Menerima nominal Rupiah pembelian bensin."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Pengisian dibatalkan.")
        return

    rupiah_clean = message.text.replace(".", "").replace(",", "").strip()
    if not rupiah_clean.isdigit():
        await state.clear()
        await message.answer("⚠️ Nominal Rupiah tidak valid. Dibatalkan.")
        return

    await state.update_data(rupiah=int(rupiah_clean))
    await state.set_state(FuelRefillFSM.waiting_for_price)

    markup = get_fuel_price_keyboard(edit_mode=False)
    await message.answer(
        "Berapa Harga per Liter bensinnya?\n<i>(Ketik nominal manual diperbolehkan)</i>:",
        parse_mode="HTML",
        reply_markup=markup,
    )


async def finalize_fuel_log(chat_id: int, target_msg: Message, state: FSMContext, harga_per_liter: int) -> None:
    """Kalkulasi volume liter dan penyimpanan transaksi BBM ke database."""
    data = await state.get_data()
    await state.clear()

    odo_sekarang = data.get("odo_sekarang")
    rupiah = data.get("rupiah")
    if rupiah is None:
        await target_msg.answer("⚠️ Sesi tidak valid. Silakan ulangi /bensin.")
        return

    liter = rupiah / harga_per_liter
    hasil = await add_log_bensin(chat_id, odo_sekarang, rupiah, liter)

    if not hasil:
        await target_msg.answer("⚠️ Gagal menyimpan. Motor belum didaftarkan.")
        return

    if hasil.get("tanpa_odo"):
        pesan = (
            f"⛽ <b>Pengisian Bensin Tersimpan!</b> (Tanpa Odometer)\n\n"
            f"💰 <b>Biaya:</b> Rp{rupiah:,}\n"
            f"💧 <b>Volume:</b> {hasil['liter']:.2f} Liter\n\n"
            f"📌 <i>Konsumsi km/L akan diakumulasikan dan dihitung otomatis saat Anda mencatat odometer pada pengisian berikutnya.</i>"
        )
        await target_msg.answer(pesan, parse_mode="HTML")
    else:
        accum_info = ""
        if hasil.get("jumlah_log_tanpa_odo", 0) > 0:
            accum_info = f"\n🔄 <i>Mencakup akumulasi dari {hasil['jumlah_log_tanpa_odo']} pengisian tanpa odometer sebelumnya (Total BBM: {hasil['total_liter_akumulasi']:.2f} L).</i>\n"

        pesan = (
            f"⛽ <b>Pengisian Bensin Tersimpan!</b>\n\n"
            f"💰 <b>Biaya:</b> Rp{rupiah:,}\n"
            f"💧 <b>Volume:</b> {hasil['liter']:.2f} Liter\n"
            f"🛣 <b>Jarak Sejak Terakhir:</b> {hasil['jarak']:.1f} km\n"
            f"📊 <b>Rata-rata Konsumsi: {hasil['kml']:.2f} km/L</b>{accum_info}"
        )

        status_oli = await get_status_oli(chat_id)
        reply_markup_oli = None
        if status_oli and status_oli.get("status") in ("mendekati", "terlewat"):
            if status_oli["status"] == "terlewat":
                pesan += f"\n\n🚨 <b>PERINGATAN OLI:</b> Anda sudah melewati jadwal ganti oli sejauh <b>{abs(status_oli['sisa_km']):.0f} km</b>! Segera ganti oli motor Anda."
            else:
                pesan += f"\n\n⚠️ <b>PENGINGAT OLI:</b> Odometer sudah mendekati jadwal ganti oli (Sisa <b>{status_oli['sisa_km']:.0f} km</b> lagi menuju {status_oli['target_oli']:.0f} km)."
            reply_markup_oli = get_fuel_hub_keyboard(motor_exists=True, status_oli=status_oli)

        await target_msg.answer(pesan, parse_mode="HTML", reply_markup=reply_markup_oli)


@router.callback_query(F.data.startswith("bsn_hrg_"), FuelRefillFSM.waiting_for_price)
async def cb_fuel_price_button(callback: CallbackQuery, state: FSMContext) -> None:
    """Pilihan harga bensin dari tombol preset."""
    await callback.answer()
    harga = int(callback.data.split("_")[2])
    if callback.message:
        await finalize_fuel_log(callback.from_user.id, callback.message, state, harga)


@router.message(FuelRefillFSM.waiting_for_price)
async def process_fill_price_manual(message: Message, state: FSMContext) -> None:
    """Pilihan harga bensin dari input ketik manual."""
    harga_clean = message.text.replace(".", "").replace(",", "").strip() if message.text else ""
    if not harga_clean.isdigit():
        await state.clear()
        await message.answer("⚠️ Harga tidak valid. Pengisian dibatalkan.")
        return
    await finalize_fuel_log(message.chat.id, message, state, int(harga_clean))


# --- RIWAYAT, DETAIL, EDIT & HAPUS LOG ---

@router.callback_query(F.data == "bsn_riwayat")
async def show_fuel_history(callback: CallbackQuery) -> None:
    """Menampilkan 10 log pengisian terakhir."""
    await callback.answer()
    logs = await get_logs_bensin(callback.from_user.id, limit=10)
    if not logs:
        text = "📜 <b>Riwayat Pengisian Bensin</b>\n\nBelum ada riwayat pengisian bensin."
        markup = None
    else:
        text = "📜 <b>Riwayat Pengisian Bensin (10 Terakhir)</b>\nKlik salah satu log untuk detail/edit/hapus:"
        markup = get_fuel_logs_keyboard(logs)
    if callback.message:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("bsn_log_"))
async def show_fuel_log_detail(callback: CallbackQuery) -> None:
    """Menampilkan detail satu log pengisian."""
    await callback.answer()
    log_id = int(callback.data.split("_")[2])
    log = await get_log_bensin_by_id(log_id, callback.from_user.id)
    if not log:
        if callback.message:
            await callback.message.answer("⚠️ Log bensin tidak ditemukan.")
        return

    text = render_log_detail_text(log)
    markup = get_fuel_log_detail_keyboard(log_id)
    if callback.message:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("bsn_del_"))
async def confirm_delete_log(callback: CallbackQuery) -> None:
    """Konfirmasi penghapusan log bensin."""
    await callback.answer()
    log_id = int(callback.data.split("_")[2])
    text = (
        f"⚠️ <b>Konfirmasi Hapus Log #{log_id}</b>\n\n"
        f"Apakah Anda yakin ingin menghapus log ini?\n"
        f"Sistem akan menghitung ulang odometer dan statistik secara otomatis."
    )
    markup = get_fuel_log_delete_confirm_keyboard(log_id)
    if callback.message:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("bsn_dodel_"))
async def do_delete_log(callback: CallbackQuery) -> None:
    """Eksekusi penghapusan log bensin dan recalculation."""
    await callback.answer()
    log_id = int(callback.data.split("_")[2])
    deleted = await delete_log_bensin(log_id, callback.from_user.id)
    if callback.message:
        if deleted:
            await callback.message.answer(f"✅ Log bensin #{log_id} berhasil dihapus dan statistik telah diperbarui!")
        else:
            await callback.message.answer("⚠️ Gagal menghapus log bensin.")


# --- FLOW EDIT LOG BENSIN (FSM) ---

@router.callback_query(F.data.startswith("bsn_edit_"))
async def start_edit_log(callback: CallbackQuery, state: FSMContext) -> None:
    """Memulai proses pengeditan log bensin."""
    await callback.answer()
    log_id = int(callback.data.split("_")[2])
    log = await get_log_bensin_by_id(log_id, callback.from_user.id)
    if not log:
        if callback.message:
            await callback.message.answer("⚠️ Log bensin tidak ditemukan.")
        return

    await state.clear()
    await state.set_state(FuelEditFSM.waiting_for_odo)
    await state.update_data(edit_log_id=log_id)

    odo_cur = log["odometer"]
    odo_cur_str = f"{odo_cur:.1f} km" if odo_cur is not None else "[Tanpa Odometer]"

    markup = get_skip_odo_keyboard()
    if callback.message:
        await callback.message.answer(
            f"✏️ <b>Edit Log Bensin #{log_id}</b> (1/3)\n\n"
            f"Berapa angka Odometer yang benar?\n"
            f"<i>(Hanya angka, contoh: 45000, atau klik tombol di bawah jika tanpa odo)</i>\n"
            f"<i>Nilai saat ini: {odo_cur_str}</i>",
            parse_mode="HTML",
            reply_markup=markup,
        )


@router.callback_query(F.data == "bsn_skip_odo", FuelEditFSM.waiting_for_odo)
async def edit_skip_odo_button(callback: CallbackQuery, state: FSMContext) -> None:
    """Tombol lewati odometer pada mode edit."""
    await callback.answer()
    await state.update_data(edit_odo=None)
    await state.set_state(FuelEditFSM.waiting_for_rupiah)
    if callback.message:
        await callback.message.answer("Berapa nominal Rupiah yang benar? (Hanya angka, contoh: 25000):")


@router.message(FuelEditFSM.waiting_for_odo)
async def process_edit_odo(message: Message, state: FSMContext) -> None:
    """Menerima angka odometer baru untuk edit log."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Edit dibatalkan.")
        return

    txt = message.text.strip().lower()
    if txt in ("-", "skip", "lewati", "0", "tidak", "lupa"):
        odo_val = None
    else:
        try:
            odo_val = float(txt.replace(",", "."))
        except ValueError:
            await state.clear()
            await message.answer("⚠️ Odometer harus angka desimal/bulat. Edit dibatalkan.")
            return

    await state.update_data(edit_odo=odo_val)
    await state.set_state(FuelEditFSM.waiting_for_rupiah)
    await message.answer("Berapa nominal Rupiah yang benar? (Hanya angka, contoh: 25000):")


@router.message(FuelEditFSM.waiting_for_rupiah)
async def process_edit_rupiah(message: Message, state: FSMContext) -> None:
    """Menerima nominal Rupiah baru untuk edit log."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Edit dibatalkan.")
        return

    rupiah_clean = message.text.replace(".", "").replace(",", "").strip()
    if not rupiah_clean.isdigit():
        await state.clear()
        await message.answer("⚠️ Nominal Rupiah tidak valid. Edit dibatalkan.")
        return

    await state.update_data(edit_rupiah=int(rupiah_clean))
    await state.set_state(FuelEditFSM.waiting_for_price)

    markup = get_fuel_price_keyboard(edit_mode=True)
    await message.answer(
        "Berapa Harga per Liter bensinnya?\n<i>(Ketik nominal manual diperbolehkan)</i>:",
        parse_mode="HTML",
        reply_markup=markup,
    )


async def finalize_edit_fuel_log(chat_id: int, target_msg: Message, state: FSMContext, harga_per_liter: int) -> None:
    """Menyimpan pembaruan log bensin ke database dan memicu recalculation otomatis."""
    data = await state.get_data()
    await state.clear()

    log_id = data.get("edit_log_id")
    edit_odo = data.get("edit_odo")
    edit_rupiah = data.get("edit_rupiah")

    if not log_id or edit_rupiah is None:
        await target_msg.answer("⚠️ Sesi edit tidak valid. Silakan ulangi.")
        return

    liter = edit_rupiah / harga_per_liter
    updated = await update_log_bensin(log_id, chat_id, edit_odo, edit_rupiah, liter)

    if updated:
        odo_display = f"{edit_odo:.1f} km" if edit_odo is not None else "- (Tanpa Odometer)"
        pesan = (
            f"✅ <b>Log Bensin #{log_id} Berhasil Diperbarui!</b>\n\n"
            f"📟 <b>Odometer:</b> {odo_display}\n"
            f"💰 <b>Biaya:</b> Rp{edit_rupiah:,}\n"
            f"💧 <b>Volume:</b> {liter:.2f} Liter\n\n"
            f"<i>Statistik & konsumsi km/L telah dihitung ulang secara otomatis.</i>"
        )
        await target_msg.answer(pesan, parse_mode="HTML")
    else:
        await target_msg.answer("⚠️ Gagal memperbarui log bensin.")


@router.callback_query(F.data.startswith("bsn_edithrg_"), FuelEditFSM.waiting_for_price)
async def cb_edit_fuel_price_button(callback: CallbackQuery, state: FSMContext) -> None:
    """Pilihan harga bensin pada mode edit via tombol preset."""
    await callback.answer()
    harga = int(callback.data.split("_")[2])
    if callback.message:
        await finalize_edit_fuel_log(callback.from_user.id, callback.message, state, harga)


@router.message(FuelEditFSM.waiting_for_price)
async def process_edit_price_manual(message: Message, state: FSMContext) -> None:
    """Pilihan harga bensin pada mode edit via ketik manual."""
    harga_clean = message.text.replace(".", "").replace(",", "").strip() if message.text else ""
    if not harga_clean.isdigit():
        await state.clear()
        await message.answer("⚠️ Harga salah. Edit dibatalkan.")
        return
    await finalize_edit_fuel_log(message.chat.id, message, state, int(harga_clean))


# --- MENU OLI & PENGATURAN KILOMETER OLI ---

@router.callback_query(F.data == "bsn_menu_oli")
async def show_oil_menu(callback: CallbackQuery) -> None:
    """Menampilkan status dan menu pengelolaan ganti oli."""
    await callback.answer()
    status_oli = await get_status_oli(callback.from_user.id)
    if not status_oli:
        if callback.message:
            await callback.message.answer("⚠️ Data motor tidak ditemukan. Silakan daftarkan motor terlebih dahulu.")
        return

    text = render_oil_menu_text(status_oli)
    markup = get_fuel_oil_menu_keyboard(status_oli)
    if callback.message:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data == "bsn_action_ganti_oli")
async def action_ganti_oli(callback: CallbackQuery) -> None:
    """Konfirmasi aksi ganti oli."""
    await callback.answer()
    motor = await get_motor(callback.from_user.id)
    if not motor:
        if callback.message:
            await callback.message.answer("⚠️ Data motor tidak ditemukan.")
        return

    odo_akhir = motor["odometer_terakhir"]
    text = (
        f"🛢 <b>Konfirmasi Ganti Oli</b>\n\n"
        f"Apakah penggantian oli dilakukan pada angka odometer saat ini (<b>{odo_akhir:.1f} km</b>)?\n\n"
        f"Atau pilih ketik manual jika Anda mengganti oli pada angka km yang berbeda."
    )
    markup = get_fuel_oil_confirm_keyboard(odo_akhir)
    if callback.message:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("bsn_set_oli_cur_"))
async def set_oli_current_odo(callback: CallbackQuery) -> None:
    """Memperbarui odometer ganti oli menggunakan angka saat ini."""
    await callback.answer()
    odo_val = float(callback.data.replace("bsn_set_oli_cur_", ""))
    await update_odometer_oli(callback.from_user.id, odo_val)
    if callback.message:
        await callback.message.answer(
            f"✅ <b>Data Ganti Oli Berhasil Diperbarui!</b>\n\n"
            f"🔧 Terakhir ganti oli: <b>{odo_val:.1f} km</b>\n"
            f"🎯 Jadwal ganti oli berikutnya: <b>{odo_val + 3000.0:.1f} km</b>\n\n"
            f"Status oli Anda telah diperbarui dan kembali normal.",
            parse_mode="HTML"
        )


@router.callback_query(F.data == "bsn_edit_oli_manual")
async def start_edit_oli_manual(callback: CallbackQuery, state: FSMContext) -> None:
    """Meminta input angka km ganti oli manual."""
    await callback.answer()
    await state.clear()
    await state.set_state(FuelOilFSM.waiting_for_manual_odo)
    if callback.message:
        await callback.message.answer(
            "Berapa angka Odometer saat terakhir kali Anda ganti oli? (Ketik angka saja, contoh: 45000):"
        )


@router.message(FuelOilFSM.waiting_for_manual_odo)
async def process_edit_oli_manual_input(message: Message, state: FSMContext) -> None:
    """Menerima dan menyimpan angka km ganti oli manual."""
    if not message.text or message.text.startswith("/"):
        await state.clear()
        await message.answer("❌ Batal mengubah odometer ganti oli.")
        return

    txt = message.text.strip().replace(",", ".")
    try:
        odo_val = float(txt)
        await state.clear()
        await update_odometer_oli(message.chat.id, odo_val)
        await message.answer(
            f"✅ <b>Data Ganti Oli Berhasil Diperbarui!</b>\n\n"
            f"🔧 Terakhir ganti oli: <b>{odo_val:.1f} km</b>\n"
            f"🎯 Jadwal ganti oli berikutnya: <b>{odo_val + 3000.0:.1f} km</b>",
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer("⚠️ Odometer harus berupa angka (contoh: 45000). Dibatalkan.")
        await state.clear()

