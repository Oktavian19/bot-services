import requests
from bs4 import BeautifulSoup
from datetime import datetime
import random
import threading
import sqlite3
import os
from cryptography.fernet import Fernet

LOGIN_URL = 'https://jti.polinema.ac.id/jtiportal/login'
AUTH_URL = 'https://jti.polinema.ac.id/jtiportal/login/auth'
DASHBOARD_URL = 'https://jti.polinema.ac.id/jtiportal/mahasiswa'

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.db')

# State Trackers
active_users = {}       
user_events = {}        
manual_checks = {}      

# Masukkan Secret Key Anda di sini
SECRET_KEY = os.environ.get('MAGANG_SECRET_KEY')
cipher_suite = Fernet(SECRET_KEY)

def encrypt_pass(plain_text):
    return cipher_suite.encrypt(plain_text.encode()).decode()

def decrypt_pass(cipher_text):
    return cipher_suite.decrypt(cipher_text.encode()).decode()

# --- DATABASE OPERATIONS ---
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            password TEXT,
            last_status TEXT
        )''')

def add_user_db(chat_id, username, plain_password):
    enc_password = encrypt_pass(plain_password)
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('INSERT OR REPLACE INTO users (chat_id, username, password, last_status) VALUES (?, ?, ?, ?)',
                     (chat_id, username, enc_password, None))

def remove_user_db(chat_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('DELETE FROM users WHERE chat_id = ?', (chat_id,))

def update_status_db(chat_id, status):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('UPDATE users SET last_status = ? WHERE chat_id = ?', (status, chat_id))

def get_all_users_db():
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute('SELECT chat_id, username, password, last_status FROM users')
        return cur.fetchall()

# --- MONITORING THREAD ---
# Perhatikan kita menambahkan parameter 'bot' di sini
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
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        bot.reply_to(message, "Halo! Kirim Username Anda untuk memulai pemantauan status magang:")
        bot.register_next_step_handler(message, process_username_step, bot)

    def process_username_step(message, bot):
        chat_id = message.chat.id
        username = message.text.strip()
        if chat_id in active_users:
            bot.send_message(chat_id, f"Pemantauan untuk {active_users[chat_id]} sudah berjalan! Ketik /stop terlebih dahulu.")
            return
        bot.send_message(chat_id, "Kirim Password Anda:")
        bot.register_next_step_handler(message, process_password_step, bot, username)

    def process_password_step(message, bot, username):
        chat_id = message.chat.id
        plain_password = message.text.strip()
        try:
            bot.delete_message(chat_id, message.message_id)
            bot.send_message(chat_id, "(Pesan password Anda telah dihapus otomatis demi keamanan)")
        except Exception:
            pass 
        
        active_users[chat_id] = username
        user_events[chat_id] = threading.Event()
        manual_checks[chat_id] = False
        add_user_db(chat_id, username, plain_password)
        
        bot.send_message(chat_id, f"Memulai otomasi pemantauan status magang untuk Username: {username}...")
        t = threading.Thread(target=pantau_magang, args=(bot, chat_id, username, plain_password))
        t.daemon = True 
        t.start()

    @bot.message_handler(commands=['stop'])
    def stop_pantau(message):
        chat_id = message.chat.id
        if chat_id in active_users:
            user_stopped = active_users.pop(chat_id)
            manual_checks.pop(chat_id, None)
            remove_user_db(chat_id)
            event = user_events.pop(chat_id, None)
            if event: event.set()
            bot.reply_to(message, f"Pemantauan untuk {user_stopped} langsung dihentikan.")
        else:
            bot.reply_to(message, "Tidak ada pemantauan yang sedang berjalan.")

    @bot.message_handler(commands=['check'])
    def cek_pantau(message):
        chat_id = message.chat.id
        if chat_id in active_users:
            bot.reply_to(message, "Meminta pembaruan status ke server... (mohon tunggu)")
            manual_checks[chat_id] = True
            event = user_events.get(chat_id)
            if event: event.set()
        else:
            bot.reply_to(message, "Tidak ada pemantauan yang sedang berjalan.")

    @bot.message_handler(commands=['active'])
    def cek_active(message):
        if active_users:
            users = "\n".join([f"- {user}" for user in active_users.values()])
            bot.reply_to(message, f"Daftar akun yang sedang dipantau saat ini:\n{users}")
        else:
            bot.reply_to(message, "Saat ini tidak ada proses pemantauan yang berjalan.")

# --- INITIALIZATION ---
def init_magang(bot):
    print("Membaca database pengguna aktif...")
    init_db()
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
            
            try:
                print("🔄 Server baru saja di-restart. Pemantauan dilanjutkan!")
            except Exception:
                pass
        except Exception as e:
            print(f"Gagal meresume {username}: {e}")