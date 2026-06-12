import os
import telebot
import socket
import urllib3.util.connection as urllib3_cn
from telebot import types
from datetime import datetime
import threading

# Import modul
from modul.magang import main as magang
from modul.jaringan import main as jaringan
from modul.reminder import main as reminder

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
        types.BotCommand("magang", "Pusat kendali pemantauan magang"),
        types.BotCommand("reminder", "Manajemen agenda & pengingat"),
        types.BotCommand("ping", "Cek status koneksi server"),
    ]
    bot.set_my_commands(commands)
    print("[+] Menu rekomendasi command berhasil diterapkan!")

# --- PERINTAH MENU DENGAN TOMBOL INLINE ---
@bot.message_handler(commands=['start'])
def send_menu_utama(message):
    
    markup = types.InlineKeyboardMarkup(row_width=2) 
    
    tombol_ping = types.InlineKeyboardButton("🏓 Ping Server", callback_data="cb_ping")
    tombol_magang = types.InlineKeyboardButton("🎓 Pusat Magang", callback_data="cb_magang")
    tombol_reminder = types.InlineKeyboardButton("🔔 Pengingat", callback_data="cb_reminder")
    tombol_speed = types.InlineKeyboardButton("🚀 Speedtest", callback_data="cb_speedtest")
    
    markup.add(tombol_ping, tombol_magang, tombol_reminder, tombol_speed)
    
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
        
    elif call.data == "cb_magang":
        call.message.text = "/magang"
        bot.process_new_messages([call.message])
        
    elif call.data == "cb_reminder":
        call.message.text = "/reminder"
        bot.process_new_messages([call.message])
        
    elif call.data == "cb_speedtest":
        call.message.text = "/speedtest"
        bot.process_new_messages([call.message])

if __name__ == '__main__':
    print("Memulai inisialisasi layanan...")
    
    setup_bot_commands()

    # Inisialisasi Handler Modul
    magang.init_magang(bot)
    jaringan.init_jaringan(bot)
    reminder.init_reminder(bot)
    
    print("Memulai background scheduler untuk reminder...")
    thread_scheduler = threading.Thread(target=reminder.jalankan_scheduler, args=(bot,))
    thread_scheduler.daemon = True
    thread_scheduler.start()      
    
    print("Telegram bot siap dan berjalan!")
    bot.infinity_polling()
