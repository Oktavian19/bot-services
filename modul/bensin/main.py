from telebot import types
from .database import (
    setup_database, register_motor, get_motor, add_log_bensin, get_statistik_bensin,
    get_logs_bensin, get_log_bensin_by_id, delete_log_bensin, update_log_bensin,
    update_odometer_oli, get_status_oli
)

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
            text = "🏍 <b>Manajemen Bensin & Motor</b>\n\nAnda belum mendaftarkan motor. Silakan daftarkan terlebih dahulu untuk melacak konsumsi BBM dan jadwal ganti oli."
            markup.add(types.InlineKeyboardButton("📝 Daftar Motor", callback_data="bsn_daftar"))
        else:
            nama_motor, odo_awal, odo_akhir, odo_oli = motor
            total_jarak = odo_akhir - odo_awal
            
            stats = get_statistik_bensin(chat_id)
            if stats['rata_rata'] > 0:
                teks_kml = (
                    f"📊 <b>Rata-rata BBM:</b> {stats['rata_rata']:.2f} km/L\n"
                    f"📈 <b>Konsumsi Terakhir:</b> {stats['terakhir']:.2f} km/L\n\n"
                )
            else:
                teks_kml = "📊 <b>Data Konsumsi:</b> Belum ada riwayat pengisian bensin.\n\n"
                
            status_oli = get_status_oli(chat_id)
            if not status_oli or status_oli['status'] == 'belum_diatur':
                teks_oli = "🛢 <b>Status Oli:</b> ⚠️ Belum diatur (Klik 'Cek & Atur Oli')\n\n"
            elif status_oli['status'] == 'aman':
                teks_oli = f"🛢 <b>Status Oli:</b> 🟢 Aman (Sisa {status_oli['sisa_km']:.0f} km menuju {status_oli['target_oli']:.0f} km)\n\n"
            elif status_oli['status'] == 'mendekati':
                teks_oli = f"🛢 <b>Status Oli:</b> ⚠️ <b>Mendekati Ganti Oli!</b> (Sisa {status_oli['sisa_km']:.0f} km menuju {status_oli['target_oli']:.0f} km)\n\n"
            else:
                teks_oli = f"🛢 <b>Status Oli:</b> 🚨 <b>SUDAH MELEWATI JADWAL!</b> (Terlewat {abs(status_oli['sisa_km']):.0f} km dari {status_oli['target_oli']:.0f} km)\n\n"
            
            text = (
                f"🏍 <b>Manajemen Motor: {nama_motor}</b>\n\n"
                f"📟 <b>Odometer Awal:</b> {odo_awal:.1f} km\n"
                f"📟 <b>Odometer Terakhir:</b> {odo_akhir:.1f} km\n"
                f"🛣 <b>Total Terpantau:</b> {total_jarak:.1f} km\n\n"
                f"{teks_kml}"
                f"{teks_oli}"
                f"Silakan pilih menu di bawah ini:"
            )
            
            if status_oli and status_oli['status'] in ['mendekati', 'terlewat']:
                markup.add(types.InlineKeyboardButton("🛢️ Sudah Ganti Oli!", callback_data="bsn_action_ganti_oli"))
                
            markup.add(
                types.InlineKeyboardButton("⛽ Isi Bensin", callback_data="bsn_isi"),
                types.InlineKeyboardButton("📜 Riwayat & Edit/Hapus", callback_data="bsn_riwayat")
            )
            markup.add(
                types.InlineKeyboardButton("🛢️ Cek & Atur Oli", callback_data="bsn_menu_oli"),
                types.InlineKeyboardButton("⚙️ Ubah Motor (Reset)", callback_data="bsn_daftar")
            )
            
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
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⏭ Lewati Odometer", callback_data="bsn_skip_odo"))
            msg = bot.send_message(
                chat_id, 
                "Berapa angka Odometer Anda saat ini di SPBU?\n<i>(Ketik angka, contoh: 45000, atau klik tombol di bawah jika lupa/tanpa odo)</i>:", 
                parse_mode="HTML",
                reply_markup=markup
            )
            bot.register_next_step_handler(msg, ask_rupiah_bensin, bot)
            
        elif action == "bsn_skip_odo":
            bot.clear_step_handler_by_chat_id(chat_id)
            bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id, reply_markup=None)
            user_bensin_state[chat_id] = {'odo_sekarang': None}
            print(f"[BENSIN] User {chat_id} memilih lewati odometer via tombol.")
            msg = bot.send_message(chat_id, "Berapa nominal Rupiah bensin yang Anda beli? (Hanya angka tanpa titik, misal: 25000):")
            bot.register_next_step_handler(msg, ask_harga_per_liter, bot)
        
        elif action.startswith("bsn_hrg_"):
            bot.clear_step_handler_by_chat_id(chat_id)
            harga_pilihan = action.split("_")[2] 
            bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id, reply_markup=None)
            call.message.text = harga_pilihan
            process_log_bensin(call.message, bot)

        elif action == "bsn_riwayat":
            logs = get_logs_bensin(chat_id, limit=10)
            if not logs:
                bot.send_message(chat_id, "📜 <b>Riwayat Pengisian Bensin</b>\n\nBelum ada riwayat pengisian bensin.", parse_mode="HTML")
            else:
                markup = types.InlineKeyboardMarkup(row_width=1)
                for log_id, odo, rupiah, liter, jarak, kml, tgl in logs:
                    tgl_singkat = str(tgl)[:10] if tgl else ""
                    if odo is None:
                        btn_text = f"📅 {tgl_singkat} | [Tanpa Odo] | Rp{rupiah:,} ({liter:.2f}L)"
                    else:
                        btn_text = f"📅 {tgl_singkat} | {odo:.0f} km | Rp{rupiah:,} ({liter:.2f}L)"
                    markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"bsn_log_{log_id}"))
                
                bot.send_message(chat_id, "📜 <b>Riwayat Pengisian Bensin (10 Terakhir)</b>\nKlik salah satu log untuk detail/edit/hapus:", parse_mode="HTML", reply_markup=markup)

        elif action.startswith("bsn_log_"):
            log_id = int(action.split("_")[2])
            log = get_log_bensin_by_id(log_id, chat_id)
            if not log:
                bot.send_message(chat_id, "⚠️ Log bensin tidak ditemukan.")
            else:
                _, odo, rupiah, liter, jarak, kml, tgl = log
                if odo is None:
                    odo_teks = "- (Tanpa Odometer)"
                    jarak_teks = "- (Belum ada odo)"
                    kml_teks = "- (Menunggu odo berikutnya)"
                else:
                    odo_teks = f"{odo:.1f} km"
                    jarak_teks = f"{jarak:.1f} km"
                    kml_teks = f"{kml:.2f} km/L"
                    
                teks_detail = (
                    f"📝 <b>Detail Log Bensin #{log_id}</b>\n\n"
                    f"📅 <b>Tanggal:</b> {tgl}\n"
                    f"📟 <b>Odometer:</b> {odo_teks}\n"
                    f"💰 <b>Biaya:</b> Rp{rupiah:,}\n"
                    f"💧 <b>Volume:</b> {liter:.2f} Liter\n"
                    f"🛣 <b>Jarak Tempuh:</b> {jarak_teks}\n"
                    f"📊 <b>Konsumsi:</b> {kml_teks}"
                )
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton("✏️ Edit Log", callback_data=f"bsn_edit_{log_id}"),
                    types.InlineKeyboardButton("🗑 Hapus Log", callback_data=f"bsn_del_{log_id}")
                )
                markup.add(types.InlineKeyboardButton("📜 Kembali ke Riwayat", callback_data="bsn_riwayat"))
                bot.send_message(chat_id, teks_detail, parse_mode="HTML", reply_markup=markup)

        elif action.startswith("bsn_del_"):
            log_id = int(action.split("_")[2])
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✅ Ya, Hapus", callback_data=f"bsn_dodel_{log_id}"),
                types.InlineKeyboardButton("❌ Batal", callback_data=f"bsn_log_{log_id}")
            )
            bot.send_message(
                chat_id, 
                f"⚠️ <b>Konfirmasi Hapus Log #{log_id}</b>\n\nApakah Anda yakin ingin menghapus log ini?\nSistem akan menghitung ulang odometer dan statistik secara otomatis.", 
                parse_mode="HTML", 
                reply_markup=markup
            )

        elif action.startswith("bsn_dodel_"):
            log_id = int(action.split("_")[2])
            deleted = delete_log_bensin(log_id, chat_id)
            if deleted:
                bot.send_message(chat_id, f"✅ Log bensin #{log_id} berhasil dihapus dan statistik telah diperbarui!")
            else:
                bot.send_message(chat_id, "⚠️ Gagal menghapus log bensin.")

        elif action.startswith("bsn_edit_"):
            log_id = int(action.split("_")[2])
            log = get_log_bensin_by_id(log_id, chat_id)
            if not log:
                bot.send_message(chat_id, "⚠️ Log bensin tidak ditemukan.")
            else:
                user_bensin_state[chat_id] = {'edit_id': log_id}
                odo_cur = log[1]
                odo_cur_str = f"{odo_cur:.1f} km" if odo_cur is not None else "[Tanpa Odometer]"
                
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⏭ Lewati / Tanpa Odometer", callback_data="bsn_edit_skip_odo"))
                
                msg = bot.send_message(
                    chat_id, 
                    f"✏️ <b>Edit Log Bensin #{log_id}</b> (1/3)\n\n"
                    f"Berapa angka Odometer yang benar?\n"
                    f"<i>(Hanya angka, contoh: 45000, atau klik tombol di bawah jika tanpa odo)</i>\n"
                    f"<i>Nilai saat ini: {odo_cur_str}</i>",
                    parse_mode="HTML",
                    reply_markup=markup
                )
                bot.register_next_step_handler(msg, ask_edit_odo, bot)

        elif action == "bsn_edit_skip_odo":
            bot.clear_step_handler_by_chat_id(chat_id)
            bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id, reply_markup=None)
            if chat_id not in user_bensin_state or 'edit_id' not in user_bensin_state[chat_id]:
                bot.send_message(chat_id, "⚠️ Sesi edit telah berakhir. Silakan pilih log kembali dari riwayat.")
                return
            user_bensin_state[chat_id]['edit_odo'] = None
            log_id = user_bensin_state[chat_id]['edit_id']
            log = get_log_bensin_by_id(log_id, chat_id)
            rupiah_cur = log[2] if log else 0
            msg = bot.send_message(
                chat_id, 
                f"✏️ <b>Edit Log Bensin #{log_id}</b> (2/3)\n\n"
                f"Berapa nominal Rupiah yang benar? (Hanya angka, contoh: 25000):\n"
                f"<i>Nilai saat ini: Rp{rupiah_cur:,}</i>",
                parse_mode="HTML"
            )
            bot.register_next_step_handler(msg, ask_edit_rupiah, bot)

        elif action.startswith("bsn_edithrg_"):
            bot.clear_step_handler_by_chat_id(chat_id)
            harga_pilihan = action.split("_")[2] 
            bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id, reply_markup=None)
            call.message.text = harga_pilihan
            process_edit_log_bensin(call.message, bot)

        elif action == "bsn_reg_same_oli":
            bot.clear_step_handler_by_chat_id(chat_id)
            bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id, reply_markup=None)
            if chat_id in user_bensin_state and 'nama_motor' in user_bensin_state[chat_id] and 'odo_awal' in user_bensin_state[chat_id]:
                nama_motor = user_bensin_state[chat_id]['nama_motor']
                odo_awal = user_bensin_state[chat_id]['odo_awal']
                register_motor(chat_id, nama_motor, odo_awal, odo_awal)
                user_bensin_state.pop(chat_id, None)
                bot.send_message(
                    chat_id, 
                    f"✅ <b>Motor {nama_motor} berhasil didaftarkan!</b>\n\n"
                    f"📟 Odometer awal: <b>{odo_awal:.1f} km</b>\n"
                    f"🛢 Terakhir ganti oli: <b>{odo_awal:.1f} km</b>\n"
                    f"🎯 Jadwal ganti oli berikutnya: <b>{odo_awal + 3000.0:.1f} km</b>\n\n"
                    f"Ketik /bensin saat Anda berada di SPBU.", 
                    parse_mode="HTML"
                )

        elif action == "bsn_menu_oli":
            status_oli = get_status_oli(chat_id)
            if not status_oli:
                bot.send_message(chat_id, "⚠️ Data motor tidak ditemukan. Silakan daftarkan motor terlebih dahulu.")
                return
                
            markup = types.InlineKeyboardMarkup(row_width=1)
            
            if status_oli['status'] == 'belum_diatur':
                teks_detail = (
                    f"🛢 <b>Informasi & Pengingat Ganti Oli</b>\n\n"
                    f"⚠️ <b>Status:</b> Belum diatur.\n"
                    f"📟 <b>Odometer Motor Saat Ini:</b> {status_oli['odo_sekarang']:.1f} km\n\n"
                    f"<i>Silakan atur kilometer saat terakhir ganti oli agar bot dapat memantau jadwal penggantian oli setiap 3.000 km.</i>"
                )
                markup.add(types.InlineKeyboardButton("✏️ Atur Km Terakhir Ganti Oli", callback_data="bsn_edit_oli_manual"))
            else:
                terakhir_oli = status_oli['terakhir_oli']
                target_oli = status_oli['target_oli']
                odo_sekarang = status_oli['odo_sekarang']
                jarak_sejak = status_oli['jarak_sejak_oli']
                sisa_km = status_oli['sisa_km']
                
                if status_oli['status'] == 'aman':
                    badge_status = f"🟢 <b>Aman</b> (Sisa {sisa_km:.0f} km)"
                elif status_oli['status'] == 'mendekati':
                    badge_status = f"⚠️ <b>Mendekati Jadwal!</b> (Sisa {sisa_km:.0f} km)"
                else:
                    badge_status = f"🚨 <b>SUDAH MELEWATI JADWAL!</b> (Terlewat {abs(sisa_km):.0f} km)"
                    
                teks_detail = (
                    f"🛢 <b>Informasi & Pengingat Ganti Oli</b>\n\n"
                    f"📊 <b>Status:</b> {badge_status}\n"
                    f"📟 <b>Odometer Motor Saat Ini:</b> {odo_sekarang:.1f} km\n"
                    f"🔧 <b>Terakhir Ganti Oli:</b> {terakhir_oli:.1f} km\n"
                    f"🎯 <b>Jadwal Ganti Oli Berikutnya:</b> {target_oli:.1f} km\n"
                    f"🛣 <b>Jarak Sejak Ganti Oli:</b> {jarak_sejak:.1f} km\n\n"
                    f"<i>Jadwal ganti oli dihitung setiap 3.000 km dari kilometer ganti oli terakhir.</i>"
                )
                markup.add(types.InlineKeyboardButton("🛢️ Sudah Ganti Oli", callback_data="bsn_action_ganti_oli"))
                markup.add(types.InlineKeyboardButton("✏️ Ubah Km Terakhir Ganti Oli", callback_data="bsn_edit_oli_manual"))
                
            markup.add(types.InlineKeyboardButton("🔙 Kembali ke Menu Hub", callback_data="bsn_back_hub"))
            bot.send_message(chat_id, teks_detail, parse_mode="HTML", reply_markup=markup)

        elif action == "bsn_action_ganti_oli":
            motor = get_motor(chat_id)
            if not motor:
                bot.send_message(chat_id, "⚠️ Data motor tidak ditemukan.")
                return
            nama_motor, odo_awal, odo_akhir, odo_oli = motor
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(f"✅ Gunakan Odo Saat Ini ({odo_akhir:.0f} km)", callback_data=f"bsn_set_oli_cur_{odo_akhir}"),
                types.InlineKeyboardButton("✏️ Ketik Angka Odo Manual", callback_data="bsn_edit_oli_manual"),
                types.InlineKeyboardButton("❌ Batal", callback_data="bsn_menu_oli")
            )
            bot.send_message(
                chat_id,
                f"🛢 <b>Konfirmasi Ganti Oli</b>\n\n"
                f"Apakah penggantian oli dilakukan pada angka odometer saat ini (<b>{odo_akhir:.1f} km</b>)?\n\n"
                f"Atau pilih ketik manual jika Anda mengganti oli pada angka km yang berbeda.",
                parse_mode="HTML",
                reply_markup=markup
            )

        elif action.startswith("bsn_set_oli_cur_"):
            odo_val = float(action.replace("bsn_set_oli_cur_", ""))
            update_odometer_oli(chat_id, odo_val)
            bot.send_message(
                chat_id,
                f"✅ <b>Data Ganti Oli Berhasil Diperbarui!</b>\n\n"
                f"🔧 Terakhir ganti oli: <b>{odo_val:.1f} km</b>\n"
                f"🎯 Jadwal ganti oli berikutnya: <b>{odo_val + 3000.0:.1f} km</b>\n\n"
                f"Status oli Anda telah diperbarui dan kembali normal.",
                parse_mode="HTML"
            )

        elif action == "bsn_edit_oli_manual":
            msg = bot.send_message(
                chat_id,
                "Berapa angka Odometer saat terakhir kali Anda ganti oli? (Ketik angka saja, contoh: 45000):"
            )
            bot.register_next_step_handler(msg, process_update_oli_manual, bot)

        elif action == "bsn_back_hub":
            call.message.text = "/bensin"
            bot.process_new_messages([call.message])

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
        bot.register_next_step_handler(msg, ask_odo_oli_awal, bot)

    def ask_odo_oli_awal(message, bot):
        chat_id = message.chat.id
        if not message.text or message.text.startswith('/'):
            bot.send_message(chat_id, "❌ Pendaftaran dibatalkan.")
            user_bensin_state.pop(chat_id, None)
            return
            
        try:
            odo_awal = float(message.text.replace(",", "."))
            user_bensin_state[chat_id]['odo_awal'] = odo_awal
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Sama dengan Odo Saat Ini", callback_data="bsn_reg_same_oli"))
            
            msg = bot.send_message(
                chat_id, 
                f"🛢 <b>Jadwal Ganti Oli Motor</b>\n\n"
                f"Di angka odometer berapa motor {user_bensin_state[chat_id]['nama_motor']} terakhir kali ganti oli?\n"
                f"<i>(Ketik angka odometer, atau klik tombol di bawah jika baru saja ganti oli pada odo {odo_awal:.0f} km)</i>:",
                parse_mode="HTML",
                reply_markup=markup
            )
            bot.register_next_step_handler(msg, save_motor, bot)
        except ValueError:
            print(f"[BENSIN - ERROR] User {chat_id} gagal mendaftar, input odometer tidak valid: {message.text}")
            bot.send_message(chat_id, "⚠️ Odometer harus berupa angka (contoh: 45000.5). Pendaftaran dibatalkan.")
            user_bensin_state.pop(chat_id, None)
        
    def save_motor(message, bot):
        chat_id = message.chat.id
        if not message.text or message.text.startswith('/'):
            bot.send_message(chat_id, "❌ Pendaftaran dibatalkan.")
            user_bensin_state.pop(chat_id, None)
            return
            
        try:
            nama_motor = user_bensin_state[chat_id]['nama_motor']
            odo_awal = user_bensin_state[chat_id]['odo_awal']
            odo_oli = float(message.text.replace(",", "."))
            
            register_motor(chat_id, nama_motor, odo_awal, odo_oli)
            user_bensin_state.pop(chat_id, None)
            print(f"[BENSIN] Motor {nama_motor} milik User {chat_id} berhasil disimpan dengan Odo Awal: {odo_awal}, Odo Oli: {odo_oli}")
            
            bot.send_message(
                chat_id, 
                f"✅ <b>Motor {nama_motor} berhasil didaftarkan!</b>\n\n"
                f"📟 Odometer awal: <b>{odo_awal:.1f} km</b>\n"
                f"🛢 Terakhir ganti oli: <b>{odo_oli:.1f} km</b>\n"
                f"🎯 Jadwal ganti oli berikutnya: <b>{odo_oli + 3000.0:.1f} km</b>\n\n"
                f"Ketik /bensin saat Anda berada di SPBU.", 
                parse_mode="HTML"
            )
        except ValueError:
            print(f"[BENSIN - ERROR] User {chat_id} gagal mendaftar, input odometer oli tidak valid: {message.text}")
            bot.send_message(chat_id, "⚠️ Odometer oli harus berupa angka (contoh: 44000). Pendaftaran dibatalkan.")
            user_bensin_state.pop(chat_id, None)

    def process_update_oli_manual(message, bot):
        chat_id = message.chat.id
        if not message.text or message.text.startswith('/'):
            bot.send_message(chat_id, "❌ Batal mengubah odometer ganti oli.")
            return
            
        txt = message.text.strip().replace(",", ".")
        try:
            odo_val = float(txt)
            update_odometer_oli(chat_id, odo_val)
            bot.send_message(
                chat_id,
                f"✅ <b>Data Ganti Oli Berhasil Diperbarui!</b>\n\n"
                f"🔧 Terakhir ganti oli: <b>{odo_val:.1f} km</b>\n"
                f"🎯 Jadwal ganti oli berikutnya: <b>{odo_val + 3000.0:.1f} km</b>",
                parse_mode="HTML"
            )
        except ValueError:
            bot.send_message(chat_id, "⚠️ Odometer harus berupa angka (contoh: 45000). Dibatalkan.")

    # --- FLOW PENGISIAN BENSIN ---
    def ask_rupiah_bensin(message, bot):
        chat_id = message.chat.id
        if not message.text or message.text.startswith('/'):
            bot.send_message(chat_id, "❌ Dibatalkan.")
            user_bensin_state.pop(chat_id, None)
            return
            
        txt = message.text.strip().lower()
        if txt in ['-', 'skip', 'lewati', '0', 'tidak', 'lupa']:
            user_bensin_state[chat_id] = {'odo_sekarang': None}
            print(f"[BENSIN] User {chat_id} memilih tanpa Odo SPBU.")
        else:
            try:
                odo_sekarang = float(txt.replace(",", "."))
                user_bensin_state[chat_id] = {'odo_sekarang': odo_sekarang}
                print(f"[BENSIN] User {chat_id} input Odo SPBU: {odo_sekarang}")
            except ValueError:
                print(f"[BENSIN - ERROR] User {chat_id} gagal input odo SPBU: {message.text}")
                bot.send_message(chat_id, "⚠️ Odometer harus angka desimal/bulat (contoh: 45000.5) atau '-' jika tanpa odo. Dibatalkan.")
                user_bensin_state.pop(chat_id, None)
                return
            
        msg = bot.send_message(chat_id, "Berapa nominal Rupiah bensin yang Anda beli? (Hanya angka tanpa titik, misal: 25000):")
        bot.register_next_step_handler(msg, ask_harga_per_liter, bot)
        
    def ask_harga_per_liter(message, bot):
        chat_id = message.chat.id
        if not message.text or message.text.startswith('/'):
            bot.send_message(chat_id, "❌ Dibatalkan.")
            user_bensin_state.pop(chat_id, None)
            return
            
        rupiah_bersih = message.text.replace(".", "").replace(",", "")
        if not rupiah_bersih.isdigit():
            bot.send_message(chat_id, "⚠️ Nominal salah. Dibatalkan.")
            user_bensin_state.pop(chat_id, None)
            return
            
        if chat_id not in user_bensin_state:
            user_bensin_state[chat_id] = {}
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
            user_bensin_state.pop(chat_id, None)
            return
            
        try:
            odo_sekarang = user_bensin_state.get(chat_id, {}).get('odo_sekarang')
            rupiah = user_bensin_state.get(chat_id, {}).get('rupiah')
            if rupiah is None:
                bot.send_message(chat_id, "⚠️ Sesi pengisian bensin tidak valid. Silakan ulangi dari /bensin.")
                user_bensin_state.pop(chat_id, None)
                return
                
            harga_per_liter = int(harga_bersih)
            liter = rupiah / harga_per_liter
            print(f"[BENSIN] Kalkulasi User {chat_id}: Rp{rupiah} / {harga_per_liter} = {liter:.2f} Liter")
            
            # Simpan ke Database
            hasil = add_log_bensin(chat_id, odo_sekarang, rupiah, liter)
            
            if hasil:
                if hasil.get("tanpa_odo"):
                    print(f"[BENSIN] Log bensin tanpa odo User {chat_id} berhasil dicatat.")
                    pesan = (
                        f"⛽ <b>Pengisian Bensin Tersimpan!</b> (Tanpa Odometer)\n\n"
                        f"💰 <b>Biaya:</b> Rp{rupiah:,}\n"
                        f"💧 <b>Volume:</b> {hasil['liter']:.2f} Liter\n\n"
                        f"📌 <i>Konsumsi km/L akan diakumulasikan dan dihitung otomatis saat Anda mencatat odometer pada pengisian berikutnya.</i>"
                    )
                else:
                    print(f"[BENSIN] Log bensin User {chat_id} berhasil dicatat. Km/L: {hasil['kml']}")
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
                    
                    status_oli = get_status_oli(chat_id)
                    reply_markup_oli = None
                    if status_oli and status_oli['status'] in ['mendekati', 'terlewat']:
                        if status_oli['status'] == 'terlewat':
                            pesan += f"\n\n🚨 <b>PERINGATAN OLI:</b> Anda sudah melewati jadwal ganti oli sejauh <b>{abs(status_oli['sisa_km']):.0f} km</b>! Segera ganti oli motor Anda."
                        else:
                            pesan += f"\n\n⚠️ <b>PENGINGAT OLI:</b> Odometer sudah mendekati jadwal ganti oli (Sisa <b>{status_oli['sisa_km']:.0f} km</b> lagi menuju {status_oli['target_oli']:.0f} km)."
                        reply_markup_oli = types.InlineKeyboardMarkup()
                        reply_markup_oli.add(types.InlineKeyboardButton("🛢️ Sudah Ganti Oli", callback_data="bsn_action_ganti_oli"))
                    
                    bot.send_message(chat_id, pesan, parse_mode="HTML", reply_markup=reply_markup_oli)
                    user_bensin_state.pop(chat_id, None)
                    return
            else:
                bot.send_message(chat_id, "⚠️ Gagal menyimpan. Motor belum didaftarkan.")
                
            user_bensin_state.pop(chat_id, None)
            
        except Exception as e:
            print(f"[BENSIN - FATAL ERROR] Terjadi kegagalan sistem untuk User {chat_id}: {e}")
            bot.send_message(chat_id, f"Terjadi kesalahan sistem: {e}")
            user_bensin_state.pop(chat_id, None)

    # --- FLOW EDIT BENSIN ---
    def ask_edit_odo(message, bot):
        chat_id = message.chat.id
        if not message.text or message.text.startswith('/'):
            bot.send_message(chat_id, "❌ Edit dibatalkan.")
            user_bensin_state.pop(chat_id, None)
            return
            
        txt = message.text.strip().lower()
        if txt in ['-', 'skip', 'lewati', '0', 'tidak', 'lupa']:
            user_bensin_state[chat_id]['edit_odo'] = None
        else:
            try:
                edit_odo = float(txt.replace(",", "."))
                user_bensin_state[chat_id]['edit_odo'] = edit_odo
            except ValueError:
                bot.send_message(chat_id, "⚠️ Odometer harus angka desimal/bulat (contoh: 45000.5) atau '-' jika tanpa odo. Edit dibatalkan.")
                user_bensin_state.pop(chat_id, None)
                return
                
        log_id = user_bensin_state[chat_id]['edit_id']
        log = get_log_bensin_by_id(log_id, chat_id)
        rupiah_cur = log[2] if log else 0
        
        msg = bot.send_message(
            chat_id, 
            f"✏️ <b>Edit Log Bensin #{log_id}</b> (2/3)\n\n"
            f"Berapa nominal Rupiah yang benar? (Hanya angka, contoh: 25000):\n"
            f"<i>Nilai saat ini: Rp{rupiah_cur:,}</i>",
            parse_mode="HTML"
        )
        bot.register_next_step_handler(msg, ask_edit_rupiah, bot)

    def ask_edit_rupiah(message, bot):
        chat_id = message.chat.id
        if not message.text or message.text.startswith('/'):
            bot.send_message(chat_id, "❌ Edit dibatalkan.")
            user_bensin_state.pop(chat_id, None)
            return
            
        rupiah_bersih = message.text.replace(".", "").replace(",", "")
        if not rupiah_bersih.isdigit():
            bot.send_message(chat_id, "⚠️ Nominal Rupiah salah. Edit dibatalkan.")
            user_bensin_state.pop(chat_id, None)
            return
            
        user_bensin_state[chat_id]['edit_rupiah'] = int(rupiah_bersih)
        log_id = user_bensin_state[chat_id]['edit_id']
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🟢 Pertalite", callback_data="bsn_edithrg_10000"),
            types.InlineKeyboardButton("🔵 Pertamax", callback_data="bsn_edithrg_16250")
        )
        
        msg = bot.send_message(
            chat_id, 
            f"✏️ <b>Edit Log Bensin #{log_id}</b> (3/3)\n\n"
            f"Berapa Harga per Liter bensinnya?\n"
            f"<i>(Ketik nominal manual diperbolehkan, contoh: 10000)</i>:", 
            parse_mode="HTML",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_edit_log_bensin, bot)

    def process_edit_log_bensin(message, bot):
        chat_id = message.chat.id
        if not message.text:
            return
            
        harga_bersih = message.text.replace(".", "").replace(",", "")
        if not harga_bersih.isdigit():
            bot.send_message(chat_id, "⚠️ Harga salah. Edit dibatalkan.")
            user_bensin_state.pop(chat_id, None)
            return
            
        try:
            log_id = user_bensin_state[chat_id]['edit_id']
            edit_odo = user_bensin_state[chat_id]['edit_odo']
            edit_rupiah = user_bensin_state[chat_id]['edit_rupiah']
            harga_per_liter = int(harga_bersih)
            
            liter = edit_rupiah / harga_per_liter
            
            updated = update_log_bensin(log_id, chat_id, edit_odo, edit_rupiah, liter)
            
            if updated:
                odo_display = f"{edit_odo:.1f} km" if edit_odo is not None else "- (Tanpa Odometer)"
                pesan = (
                    f"✅ <b>Log Bensin #{log_id} Berhasil Diperbarui!</b>\n\n"
                    f"📟 <b>Odometer:</b> {odo_display}\n"
                    f"💰 <b>Biaya:</b> Rp{edit_rupiah:,}\n"
                    f"💧 <b>Volume:</b> {liter:.2f} Liter\n\n"
                    f"<i>Statistik & konsumsi km/L telah dihitung ulang secara otomatis.</i>"
                )
                bot.send_message(chat_id, pesan, parse_mode="HTML")
            else:
                bot.send_message(chat_id, "⚠️ Gagal memperbarui log bensin.")
                
            user_bensin_state.pop(chat_id, None)
        except Exception as e:
            print(f"[BENSIN - FATAL ERROR] Gagal edit log untuk User {chat_id}: {e}")
            bot.send_message(chat_id, f"Terjadi kesalahan sistem: {e}")
            user_bensin_state.pop(chat_id, None)