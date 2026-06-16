import requests
from bs4 import BeautifulSoup
from datetime import datetime
import random
import threading
from telebot import types
from .database import (
    decrypt_pass, init_db, add_user_db, remove_user_db, update_status_db, get_all_users_db
)

LOGIN_URL = 'https://jti.polinema.ac.id/jtiportal/login'
AUTH_URL = 'https://jti.polinema.ac.id/jtiportal/login/auth'
DASHBOARD_URL = 'https://jti.polinema.ac.id/jtiportal/mahasiswa'

# State Trackers
active_users = {}       
user_events = {}        
manual_checks = {}      

# --- MONITORING THREAD ---
def pantau_magang(bot, chat_id, username, plain_password, initial_status=None):
    last_status = initial_status
    
    while True:
        if chat_id not in active_users:
            break

        with requests.Session() as s:
            try:
                req = s.get(LOGIN_URL)
                soup = BeautifulSoup(req.text, 'html.parser')
                csrf_input = soup.find('input', {'name': 'csrf_test_name'})
                
                if csrf_input:
                    csrf_token = csrf_input['value']
                    s.post(AUTH_URL, data={'username': username, 'password': plain_password, 'csrf_test_name': csrf_token})
                    
                    dashboard_req = s.get(DASHBOARD_URL)
                    dashboard_soup = BeautifulSoup(dashboard_req.text, 'html.parser')

                    if "Beranda" not in (dashboard_soup.title.text if dashboard_soup.title else ""):
                        bot.send_message(chat_id, f"❌ Login gagal untuk Username {username}!\nPemantauan dibatalkan.")
                        print(f"[MAGANG - ERROR] Autentikasi portal gagal untuk User {chat_id} ({username}). Thread dihentikan.")
                        active_users.pop(chat_id, None)
                        user_events.pop(chat_id, None)
                        manual_checks.pop(chat_id, None)
                        remove_user_db(chat_id)
                        break
                    
                    title_span = dashboard_soup.find('span', string=lambda t: t and 'Pendaftaran Magang' in t)
                    waktu_sekarang = datetime.now().strftime('%H:%M:%S')
                    is_manual_check = manual_checks.get(chat_id, False)
                    
                    if title_span:
                        card = title_span.find_parent('div', class_='card')
                        status_div = card.find('div', class_='fz-custom')
                        perusahaan_span = card.find('span', class_='fw-bold text-dark')
                        
                        if status_div and perusahaan_span:
                            status_lamaran = status_div.text.strip()
                            perusahaan = perusahaan_span.text.strip()
                            
                            print(f"[{waktu_sekarang}] Check {username} | Status: {status_lamaran} at {perusahaan}")
                            
                            if is_manual_check:
                                bot.send_message(chat_id, f"🔍 [Cek Manual] Status Magang {username} di {perusahaan} saat ini:\n{status_lamaran}")
                                manual_checks[chat_id] = False
                                if status_lamaran != last_status:
                                    last_status = status_lamaran
                                    update_status_db(chat_id, status_lamaran)
                            elif last_status is None:
                                last_status = status_lamaran
                                update_status_db(chat_id, status_lamaran)
                                bot.send_message(chat_id, f"✅ Pemantauan aktif!\nStatus awal di {perusahaan} adalah: {status_lamaran}")
                            elif status_lamaran != last_status:
                                print(f"[MAGANG] Perubahan status terdeteksi untuk {username}: {last_status} -> {status_lamaran}")
                                bot.send_message(chat_id, f"🎉 Status Magang {username} di {perusahaan} BERUBAH!\nDari: {last_status}\nMenjadi: {status_lamaran}")
                                last_status = status_lamaran 
                                update_status_db(chat_id, status_lamaran)
                        else:
                            if is_manual_check:
                                bot.send_message(chat_id, "🔍 [Cek Manual] Elemen status/perusahaan tidak ditemukan.")
                                manual_checks[chat_id] = False
                    else:
                        if is_manual_check:
                            bot.send_message(chat_id, "🔍 [Cek Manual] Kotak 'Pendaftaran Magang' tidak ditemukan.")
                            manual_checks[chat_id] = False
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error occurred for {username}: {e}")
                
        interval_cek = random.randint(2400, 4200)
        event = user_events.get(chat_id)
        if event:
            event.wait(interval_cek)
            event.clear() 
        else:
            break 

# --- TELEGRAM ROUTES REGISTRATION ---
def register_handlers(bot):
    
    # Hub Magang Utama
    @bot.message_handler(commands=['magang'])
    def show_magang_hub(message):
        chat_id = message.chat.id
        print(f"[MAGANG] User {chat_id} mengakses menu hub magang.")
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_pantau = types.InlineKeyboardButton("▶️ Mulai Pantau", callback_data="mgg_pantau")
        btn_stop = types.InlineKeyboardButton("⏹️ Stop Pantau", callback_data="mgg_stop")
        btn_check = types.InlineKeyboardButton("🔄 Cek Sekarang", callback_data="mgg_check")
        btn_active = types.InlineKeyboardButton("👥 User Aktif", callback_data="mgg_active")
        
        markup.add(btn_pantau, btn_stop, btn_check, btn_active)
        
        status_teks = "🟢 Aktif" if chat_id in active_users else "🔴 Berhenti"
        user_info = f" (<b>{active_users[chat_id]}</b>)" if chat_id in active_users else ""
        
        pesan = (
            f"🎓 <b>Pusat Kendali Magang JTI</b>\n"
            f"Status Pemantauan Anda: {status_teks}{user_info}\n\n"
            f"Silakan pilih aksi di bawah ini:"
        )
        bot.send_message(chat_id, pesan, parse_mode="HTML", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('mgg_'))
    def handle_magang_callback(call):
        chat_id = call.message.chat.id
        bot.answer_callback_query(call.id)
        action = call.data
        print(f"[MAGANG] User {chat_id} memicu aksi callback: {action}")
        
        if action == "mgg_pantau":
            if chat_id in active_users:
                bot.send_message(chat_id, f"⚠️ Pemantauan untuk <b>{active_users[chat_id]}</b> sudah berjalan! Hentikan terlebih dahulu.", parse_mode="HTML")
            else:
                msg = bot.send_message(chat_id, "Halo! Kirim Username portal Anda untuk memulai pemantauan status magang:")
                bot.register_next_step_handler(msg, process_username_step, bot)
                
        elif action == "mgg_stop":
            if chat_id in active_users:
                user_stopped = active_users.pop(chat_id)
                manual_checks.pop(chat_id, None)
                remove_user_db(chat_id)
                event = user_events.pop(chat_id, None)
                if event: event.set()
                bot.send_message(chat_id, f"⏹️ Pemantauan untuk <b>{user_stopped}</b> berhasil dihentikan.", parse_mode="HTML")
                print(f"[MAGANG] Thread pemantauan dihentikan paksa oleh User {chat_id} ({user_stopped}).")
            else:
                bot.send_message(chat_id, "ℹ️ Tidak ada pemantauan yang sedang berjalan untuk akun Anda.")
                
        elif action == "mgg_check":
            if chat_id in active_users:
                bot.send_message(chat_id, "🔄 Meminta pembaruan status ke server portal JTI... (mohon tunggu)")
                manual_checks[chat_id] = True
                event = user_events.get(chat_id)
                if event: event.set()
            else:
                bot.send_message(chat_id, "ℹ️ Tidak ada pemantauan yang sedang berjalan. Klik Mulai Pantau terlebih dahulu.")
                
        elif action == "mgg_active":
            if active_users:
                users = "\n".join([f"- {user}" for user in active_users.values()])
                bot.send_message(chat_id, f"👥 <b>Daftar Akun Sedang Dipantau:</b>\n{users}", parse_mode="HTML")
            else:
                bot.send_message(chat_id, "ℹ️ Saat ini tidak ada proses pemantauan magang yang berjalan di server.")

    def process_username_step(message, bot):
        chat_id = message.chat.id
        
        if not message.text or message.text.startswith('/'):
            bot.send_message(chat_id, "❌ Operasi pendaftaran pemantauan dibatalkan.")
            return
            
        username = message.text.strip()
        print(f"[MAGANG] User {chat_id} memulai pendaftaran dengan username: {username}")
        msg = bot.send_message(chat_id, "Kirim Password Anda:")
        bot.register_next_step_handler(msg, process_password_step, bot, username)

    def process_password_step(message, bot, username):
        chat_id = message.chat.id
        
        # Validasi keamanan
        if not message.text or message.text.startswith('/'):
            bot.send_message(chat_id, "❌ Operasi pendaftaran pemantauan dibatalkan.")
            print(f"[MAGANG - WARNING] Input password dibatalkan/tidak valid untuk User {chat_id}.")
            return
            
        plain_password = message.text.strip()
        try:
            bot.delete_message(chat_id, message.message_id)
            bot.send_message(chat_id, "(Pesan password Anda telah dihapus otomatis demi keamanan 🔒)")
        except Exception:
            pass 
        
        active_users[chat_id] = username
        user_events[chat_id] = threading.Event()
        manual_checks[chat_id] = False
        add_user_db(chat_id, username, plain_password)
        
        bot.send_message(chat_id, f"▶️ Memulai otomasi pemantauan status magang untuk Username: <b>{username}</b>...", parse_mode="HTML")
        t = threading.Thread(target=pantau_magang, args=(bot, chat_id, username, plain_password))
        t.daemon = True 
        t.start()
        print(f"[MAGANG] Thread pemantauan otomatis berhasil dijalankan untuk User {chat_id} ({username}).")

# --- INITIALIZATION ---
def init_magang(bot):
    print("Membaca database pengguna aktif...")
    init_db()
    print("[+] Module Magang: Database ready.")

    register_handlers(bot)
    
    users = get_all_users_db()
    if not users:
        print("Tidak ada pengguna aktif di database.")
        return
        
    for chat_id, username, enc_password, last_status in users:
        try:
            plain_password = decrypt_pass(enc_password)
            active_users[chat_id] = username
            user_events[chat_id] = threading.Event()
            manual_checks[chat_id] = False
            
            t = threading.Thread(target=pantau_magang, args=(bot, chat_id, username, plain_password, last_status))
            t.daemon = True
            t.start()
            print(f"[MAGANG] Berhasil meresume thread pemantauan untuk User {chat_id} ({username}).")
            
        except Exception as e:
            print(f"[MAGANG - ERROR] Gagal meresume {username}: {e}")