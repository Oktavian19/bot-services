from telebot import types
from .database import setup_database, register_motor, get_motor, add_log_bensin, get_statistik_bensin

user_bensin_state = {}

def init_bensin(bot):
    setup_database()
    print("[+] Module Bensin: Database ready.")

    @bot.message_handler(commands=['bensin'])
    def show_bensin_hub(message):
        chat_id = message.chat.id
        print(f"[BENSIN] User {chat_id} mengakses menu hub bensin.")
        motor = get_motor(chat_id)
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        if not motor:
            text = "🏍 <b>Manajemen Bensin Motor</b>\n\nAnda belum mendaftarkan motor. Silakan daftarkan terlebih dahulu untuk melacak konsumsi BBM."
            markup.add(types.InlineKeyboardButton("📝 Daftar Motor", callback_data="bsn_daftar"))
        else:
            nama_motor, odo_awal, odo_akhir = motor
            total_jarak = odo_akhir - odo_awal
            
            stats = get_statistik_bensin(chat_id)
            if stats['rata_rata'] > 0:
                teks_kml = (
                    f"📊 <b>Rata-rata Keseluruhan:</b> {stats['rata_rata']:.2f} km/L\n"
                    f"📈 <b>Konsumsi Terakhir:</b> {stats['terakhir']:.2f} km/L\n\n"
                )
            else:
                teks_kml = "📊 <b>Data Konsumsi:</b> Belum ada riwayat pengisian bensin.\n\n"
            
            text = (
                f"🏍 <b>Manajemen Bensin: {nama_motor}</b>\n\n"
                f"📟 <b>Odometer Awal:</b> {odo_awal:.1f} km\n"
                f"📟 <b>Odometer Terakhir:</b> {odo_akhir:.1f} km\n"
                f"🛣 <b>Total Terpantau:</b> {total_jarak:.1f} km\n\n"
                f"{teks_kml}"
                f"Silakan pilih menu di bawah ini:"
            )
            markup.add(types.InlineKeyboardButton("⛽ Isi Bensin", callback_data="bsn_isi"))
            markup.add(types.InlineKeyboardButton("⚙️ Ubah Motor (Reset)", callback_data="bsn_daftar"))
            
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('bsn_'))
    def handle_bensin_callback(call):
        chat_id = call.message.chat.id
        bot.answer_callback_query(call.id)
        action = call.data
        print(f"[BENSIN] User {chat_id} memicu aksi callback: {action}")
        
        if action == "bsn_daftar":
            msg = bot.send_message(chat_id, "Kirimkan nama/merek motor Anda (contoh: Vario 125 2013):")
            bot.register_next_step_handler(msg, ask_odo_awal, bot)
            
        elif action == "bsn_isi":
            user_bensin_state[chat_id] = {}
            msg = bot.send_message(chat_id, "Berapa angka Odometer Anda saat ini di SPBU? (Hanya angka, contoh: 45000):")
            bot.register_next_step_handler(msg, ask_rupiah_bensin, bot)
        
        elif action.startswith("bsn_hrg_"):
            bot.clear_step_handler_by_chat_id(chat_id)
            harga_pilihan = action.split("_")[2] 
            bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id, reply_markup=None)
            call.message.text = harga_pilihan
            process_log_bensin(call.message, bot)

    # --- FLOW PENDAFTARAN MOTOR ---
    def ask_odo_awal(message, bot):
        chat_id = message.chat.id
        if not message.text or message.text.startswith('/'):
            bot.send_message(chat_id, "❌ Pendaftaran dibatalkan.")
            return
            
        nama_motor = message.text
        user_bensin_state[chat_id] = {'nama_motor': nama_motor}
        print(f"[BENSIN] User {chat_id} memulai pendaftaran motor: {nama_motor}")
        
        msg = bot.send_message(chat_id, f"Berapa Odometer saat ini pada motor {nama_motor}? (Ketik angka saja):")
        bot.register_next_step_handler(msg, save_motor, bot)
        
    def save_motor(message, bot):
        chat_id = message.chat.id
        if not message.text or message.text.startswith('/'):
            bot.send_message(chat_id, "❌ Pendaftaran dibatalkan.")
            return
            
        try:
            nama_motor = user_bensin_state[chat_id]['nama_motor']
            odo_awal = float(message.text.replace(",", "."))
            
            register_motor(chat_id, nama_motor, odo_awal)
            user_bensin_state.pop(chat_id, None)
            print(f"[BENSIN] Motor {nama_motor} milik User {chat_id} berhasil disimpan dengan Odo Awal: {odo_awal}")
            
            bot.send_message(chat_id, f"✅ <b>Motor {nama_motor} berhasil didaftarkan!</b>\nOdometer awal ditetapkan pada {odo_awal:.1f} km.\n\nKetik /bensin saat Anda berada di SPBU.", parse_mode="HTML")
        except ValueError:
            print(f"[BENSIN - ERROR] User {chat_id} gagal mendaftar, input odometer tidak valid: {message.text}")
            bot.send_message(chat_id, "⚠️ Odometer harus berupa angka (contoh: 45000.5). Pendaftaran dibatalkan.")

    # --- FLOW PENGISIAN BENSIN ---
    def ask_rupiah_bensin(message, bot):
        chat_id = message.chat.id
        if not message.text or message.text.startswith('/'):
            bot.send_message(chat_id, "❌ Dibatalkan.")
            return
            
        try:
            odo_sekarang = float(message.text.replace(",", "."))
            user_bensin_state[chat_id]['odo_sekarang'] = odo_sekarang
            print(f"[BENSIN] User {chat_id} input Odo SPBU: {odo_sekarang}")
            
            msg = bot.send_message(chat_id, "Berapa nominal Rupiah bensin yang Anda beli? (Hanya angka tanpa titik, misal: 25000)")
            bot.register_next_step_handler(msg, ask_harga_per_liter, bot)
        except ValueError:
            print(f"[BENSIN - ERROR] User {chat_id} gagal input odo SPBU: {message.text}")
            bot.send_message(chat_id, "⚠️ Odometer harus angka desimal/bulat (contoh: 45000.5). Dibatalkan.")
        
    def ask_harga_per_liter(message, bot):
        chat_id = message.chat.id
        if not message.text or message.text.startswith('/'):
            bot.send_message(chat_id, "❌ Dibatalkan.")
            return
            
        rupiah_bersih = message.text.replace(".", "").replace(",", "")
        if not rupiah_bersih.isdigit():
            bot.send_message(chat_id, "⚠️ Nominal salah. Dibatalkan.")
            return
            
        user_bensin_state[chat_id]['rupiah'] = int(rupiah_bersih)
        print(f"[BENSIN] User {chat_id} mengisi bensin sebesar: Rp{rupiah_bersih}")
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🟢 Pertalite", callback_data="bsn_hrg_10000"),
            types.InlineKeyboardButton("🔵 Pertamax", callback_data="bsn_hrg_16250")
        )
        
        msg = bot.send_message(
            chat_id, 
            "Berapa Harga per Liter bensinnya?\n<i>(Ketik nominal manual diperbolehkan)</i>:", 
            parse_mode="HTML",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_log_bensin, bot)

    def process_log_bensin(message, bot):
        chat_id = message.chat.id
        if not message.text:
            return
            
        harga_bersih = message.text.replace(".", "").replace(",", "")
        if not harga_bersih.isdigit():
            bot.send_message(chat_id, "⚠️ Harga salah. Dibatalkan.")
            return
            
        try:
            odo_sekarang = user_bensin_state[chat_id]['odo_sekarang']
            rupiah = user_bensin_state[chat_id]['rupiah']
            harga_per_liter = int(harga_bersih)
            
            liter = rupiah / harga_per_liter
            print(f"[BENSIN] Kalkulasi User {chat_id}: Rp{rupiah} / {harga_per_liter} = {liter:.2f} Liter")
            
            # Simpan ke Database
            hasil = add_log_bensin(chat_id, odo_sekarang, rupiah, liter)
            
            if hasil:
                print(f"[BENSIN] Log bensin User {chat_id} berhasil dicatat. Km/L: {hasil['kml']}")
                pesan = (
                    f"⛽ <b>Pengisian Bensin Tersimpan!</b>\n\n"
                    f"💰 Biaya: Rp{rupiah:,}\n"
                    f"💧 Volume: {hasil['liter']:.2f} Liter\n"
                    f"🛣 Jarak Sejak Terakhir: {hasil['jarak']:.1f} km\n"
                    f"📊 <b>Rata-rata Konsumsi: {hasil['kml']:.2f} km/L</b>"
                )
                bot.send_message(chat_id, pesan, parse_mode="HTML")
            else:
                bot.send_message(chat_id, "⚠️ Gagal menyimpan. Motor belum didaftarkan.")
                
            user_bensin_state.pop(chat_id, None)
            
        except Exception as e:
            print(f"[BENSIN - FATAL ERROR] Terjadi kegagalan sistem untuk User {chat_id}: {e}")
            bot.send_message(chat_id, f"Terjadi kesalahan sistem: {e}")