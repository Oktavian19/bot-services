import telebot
import socket
import urllib3.util.connection as urllib3_cn
from telebot import types
from datetime import datetime

# Import modul
from modul.magang import main as magang
from modul.jaringan import main as jaringan

# --- PATCH FORCE IPV4 ---
def allowed_gai_family():
    return socket.AF_INET
urllib3_cn.allowed_gai_family = allowed_gai_family

# --- CONFIGURATION ---
TELEGRAM_TOKEN = '8794413205:AAHqoki60gONMQqzFLQV290j_iyu8O0Ef-M'
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- SETUP MENU COMMAND ---
def setup_bot_commands():
    commands = [
        types.BotCommand("start", "Mulai pendaftaran akun magang"),
        types.BotCommand("stop", "Hentikan pemantauan magang"),
        types.BotCommand("check", "Cek status magang manual sekarang"),
        types.BotCommand("active", "Lihat akun magang yang sedang dipantau"),
        types.BotCommand("ping", "Cek status koneksi server"),
        types.BotCommand("speedtest", "Uji kecepatan internet server (Admin)")
    ]
    bot.set_my_commands(commands)
    print("[+] Menu rekomendasi command berhasil diterapkan!")

# --- PERINTAH MENU DENGAN TOMBOL INLINE ---
@bot.message_handler(commands=['menu'])
def send_menu_utama(message):
    
    markup = types.InlineKeyboardMarkup(row_width=2) 
    
    tombol_ping = types.InlineKeyboardButton("🏓 Ping Server", callback_data="cb_ping")
    tombol_status = types.InlineKeyboardButton("🔍 Cek Magang", callback_data="cb_check")
    tombol_active = types.InlineKeyboardButton("👥 User Aktif", callback_data="cb_active")
    tombol_speed = types.InlineKeyboardButton("🚀 Speedtest", callback_data="cb_speedtest")
    
    markup.add(tombol_ping, tombol_status, tombol_active, tombol_speed)
    
    bot.send_message(message.chat.id, "🎛 <b>Pusat Kendali Server</b>\nSilakan pilih salah satu menu di bawah ini:", 
                     parse_mode="HTML", reply_markup=markup)

# --- HANDLER KLIK TOMBOL ---
@bot.callback_query_handler(func=lambda call: True)
def callback_listener(call):
    bot.answer_callback_query(call.id)
    
    if call.data == "cb_ping":
        waktu = datetime.now().strftime('%H:%M:%S')
        bot.send_message(call.message.chat.id, f"🏓 <b>Pong!</b> (via Tombol)\n⏱ <code>{waktu}</code>", parse_mode="HTML")
        
    elif call.data == "cb_check":
        call.message.text = "/check"
        bot.process_new_messages([call.message])
        
    elif call.data == "cb_active":
        call.message.text = "/active"
        bot.process_new_messages([call.message])
        
    elif call.data == "cb_speedtest":
        call.message.text = "/speedtest"
        bot.process_new_messages([call.message])

if __name__ == '__main__':
    print("Memulai inisialisasi layanan...")
    
    setup_bot_commands()

    # Modul Magang
    magang.init_magang(bot)
    
    # Modul Jaringan
    jaringan.init_jaringan(bot)
    
    print("Telegram bot siap dan berjalan!")
    bot.infinity_polling()
