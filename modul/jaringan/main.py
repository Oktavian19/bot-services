import os
import time
from datetime import datetime
import socket
import threading
import subprocess

CHAT_ID = os.environ.get('ADMIN_CHAT_ID')

def check_connection():
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=3)
        return True
    except OSError:
        pass
    return False

def network_loop(bot):
    was_connected = True
    downtime_start = None
    fail_count = 0
    TOLERANSI_GAGAL = 3

    while True:
        is_connected = check_connection()

        if is_connected:
            fail_count = 0 
            if not was_connected:
                downtime_end = datetime.now()
                durasi = downtime_end - downtime_start
                menit_mati = durasi.total_seconds() / 60
                
                time.sleep(5)
                
                msg = f"🔄 <b>Koneksi Server Pulih!</b>\n\nServer sempat terputus dari internet sejak:\n⏱ <code>{downtime_start.strftime('%H:%M:%S')}</code>\n\nDurasi terputus: <b>{menit_mati:.1f} menit</b>."
                
                try:
                    bot.send_message(CHAT_ID, msg, parse_mode="HTML")
                except Exception as e:
                    print(f"Gagal kirim notifikasi jaringan: {e}")
                    
                print(f"[{downtime_end.strftime('%H:%M:%S')}] Jaringan pulih kembali.")
                was_connected = True
                downtime_start = None
        else:
            fail_count += 1
            if fail_count >= TOLERANSI_GAGAL and was_connected:
                downtime_start = datetime.now()
                print(f"[{downtime_start.strftime('%H:%M:%S')}] Jaringan terputus! Menunggu pemulihan...")
                was_connected = False

        if was_connected:
            time.sleep(90)
        else:
            time.sleep(15)

# --- TELEGRAM ROUTES REGISTRATION ---
def register_handlers(bot):
    @bot.message_handler(commands=['ping'])
    def send_ping(message):
        waktu = datetime.now().strftime('%H:%M:%S')
        balasan = (
            f"🏓 <b>Pong!</b>\n\n"
            f"Server Debian dalam kondisi <b>ONLINE</b> dan terhubung ke jaringan.\n"
            f"⏱ <code>{waktu}</code>"
        )
        bot.reply_to(message, balasan, parse_mode="HTML")

    @bot.message_handler(commands=['speedtest'])
    def run_speedtest(message):
        if str(message.chat.id) != CHAT_ID:
            bot.reply_to(message, "❌ Akses ditolak. Hanya Administrator yang bisa menjalankan perintah ini.")
            return

        # Loading
        loading_msg = bot.reply_to(message, "🚀 Sedang mengukur kecepatan internet server...\n<i>Mohon tunggu sekitar 20-30 detik ⏳</i>", parse_mode="HTML")
        
        try:
            result = subprocess.run(['speedtest', '--accept-license', '--accept-gdpr'], 
                                    capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                output_bersih = result.stdout.strip()
                balasan_akhir = f"📊 <b>Laporan Speedtest Server:</b>\n<pre><code>{output_bersih}</code></pre>"
                
                bot.edit_message_text(chat_id=message.chat.id, message_id=loading_msg.message_id, 
                                      text=balasan_akhir, parse_mode="HTML")
            else:
                error_msg = result.stderr.strip()
                bot.edit_message_text(chat_id=message.chat.id, message_id=loading_msg.message_id, 
                                      text=f"❌ <b>Gagal melakukan Speedtest:</b>\n<pre><code>{error_msg}</code></pre>", parse_mode="HTML")
                
        except subprocess.TimeoutExpired:
            bot.edit_message_text(chat_id=message.chat.id, message_id=loading_msg.message_id, 
                                  text="❌ Speedtest gagal karena batas waktu (Timeout > 60 detik).", parse_mode="HTML")
        except FileNotFoundError:
             bot.edit_message_text(chat_id=message.chat.id, message_id=loading_msg.message_id, 
                                  text="❌ Paket <b>Speedtest</b> tidak ditemukan di server. Pastikan sudah terinstall.", parse_mode="HTML")
        except Exception as e:
            bot.edit_message_text(chat_id=message.chat.id, message_id=loading_msg.message_id, 
                                  text=f"❌ Terjadi error internal:\n<code>{e}</code>", parse_mode="HTML")

# --- INITIALIZATION ---
def init_jaringan(bot):
    print("Mengaktifkan modul pemantauan jaringan...")
    register_handlers(bot)
    t = threading.Thread(target=network_loop, args=(bot,))
    t.daemon = True
    t.start()