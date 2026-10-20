import os
import telebot
import socket
import urllib3.util.connection as urllib3_cn
from telebot import types
from datetime import datetime
import threading

# Import modul
# [MODUL MAGANG ARSIP] Un-comment baris di bawah ini jika ingin mengaktifkan kembali:
# from modul.magang import main as magang
from modul.jaringan import main as jaringan
from modul.reminder import main as reminder
from modul.bensin import main as bensin
from modul.logbook import main as logbook

# --- PATCH FORCE IPV4 ---
def allowed_gai_family():
    return socket.AF_INET
urllib3_cn.allowed_gai_family = allowed_gai_family

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- SETUP MENU COMMAND ---
def setup_bot_commands():
    commands = [
        types.BotCommand("start", "Tampilkan menu utama"),
        # [MODUL MAGANG ARSIP] Un-comment baris di bawah jika modul magang diaktifkan:
        # types.BotCommand("magang", "Pusat kendali pemantauan magang"),
        types.BotCommand("reminder", "Manajemen agenda & pengingat"),
        types.BotCommand("ping", "Cek status koneksi server"),
        types.BotCommand("bensin", "Catatan konsumsi & riwayat BBM"),
        types.BotCommand("logbook", "Pusat kendali logbook DERMAGA"),
    ]
    bot.set_my_commands(commands)
    print("[+] Menu rekomendasi command berhasil diterapkan!")

# --- PERINTAH MENU DENGAN TOMBOL INLINE ---
@bot.message_handler(commands=['start'])
def send_menu_utama(message):
    
    markup = types.InlineKeyboardMarkup(row_width=2) 
    
    tombol_ping = types.InlineKeyboardButton("🏓 Ping Server", callback_data="cb_ping")
    # [MODUL MAGANG ARSIP] Un-comment baris di bawah dan sertakan tombol_magang ke markup.add(...) jika modul diaktifkan:
    # tombol_magang = types.InlineKeyboardButton("🎓 Pusat Magang", callback_data="cb_magang")
    tombol_reminder = types.InlineKeyboardButton("🔔 Pengingat", callback_data="cb_reminder")
    tombol_speed = types.InlineKeyboardButton("🚀 Speedtest", callback_data="cb_speedtest")
    tombol_bensin = types.InlineKeyboardButton("⛽ BBM Motor", callback_data="cb_bensin")
    tombol_logbook = types.InlineKeyboardButton("📖 Logbook", callback_data="cb_logbook")
    
    markup.add(tombol_ping, tombol_reminder, tombol_speed, tombol_bensin, tombol_logbook)
    
    bot.send_message(message.chat.id, "🎛 <b>Pusat Kendali Server</b>\nSilakan pilih salah satu menu di bawah ini:", 
                     parse_mode="HTML", reply_markup=markup)

# --- HANDLER KLIK TOMBOL ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('cb_'))
def callback_listener(call):
    bot.answer_callback_query(call.id)
    
    if call.data == "cb_ping":
        waktu = datetime.now().strftime('%H:%M:%S')
        balasan = (
            f"🏓 <b>Pong!</b>\n\n"
            f"Server Debian dalam kondisi <b>ONLINE</b> dan terhubung ke jaringan.\n"
            f"⏱ <code>{waktu}</code>"
        )
        bot.send_message(call.message.chat.id, balasan, parse_mode="HTML")
        
    # [MODUL MAGANG ARSIP] Un-comment di bawah jika modul magang diaktifkan:
    # elif call.data == "cb_magang":
    #     call.message.text = "/magang"
    #     bot.process_new_messages([call.message])
        
    elif call.data == "cb_reminder":
        call.message.text = "/reminder"
        bot.process_new_messages([call.message])
        
    elif call.data == "cb_speedtest":
        call.message.text = "/speedtest"
        bot.process_new_messages([call.message])

    elif call.data == "cb_bensin":
        call.message.text = "/bensin"
        bot.process_new_messages([call.message])

    elif call.data == "cb_logbook":
        call.message.text = "/logbook"
        bot.process_new_messages([call.message])

if __name__ == '__main__':
    print("Memulai inisialisasi layanan...")
    
    setup_bot_commands()

    # Inisialisasi Handler Modul
    # [MODUL MAGANG ARSIP] Un-comment baris di bawah jika ingin mengaktifkan modul magang:
    # magang.init_magang(bot)
    jaringan.init_jaringan(bot)
    reminder.init_reminder(bot)
    bensin.init_bensin(bot)
    logbook.init_logbook(bot)

    print("Memulai background scheduler untuk reminder...")
    thread_scheduler = threading.Thread(target=reminder.jalankan_scheduler, args=(bot,))
    thread_scheduler.daemon = True
    thread_scheduler.start()      

    print("Memulai background receiver untuk logbook...")
    thread_logbook = threading.Thread(target=logbook.jalankan_server, args=(bot,))
    thread_logbook.daemon = True
    thread_logbook.start()

    print("Telegram bot siap dan berjalan!")
    bot.infinity_polling(timeout=20, long_polling_timeout=20)

