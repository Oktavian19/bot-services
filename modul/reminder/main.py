import logging
import time
from datetime import datetime
import pytz
from telebot import types
from .database import setup_database, insert_reminder, get_due_reminders, mark_reminder_completed

# Set the timezone
LOCAL_TZ = pytz.timezone('Asia/Jakarta')

# Global dictionary to store temporary user data during conversation
user_data_store = {}

def init_reminder(bot):
    """
    Initializes the reminder module by creating the database table 
    and registering the /add_reminder command.
    """
    setup_database()
    print("[+] Module Reminder: Database ready.")

    @bot.message_handler(commands=['add_reminder'])
    def start_reminder(message):
        chat_id = message.chat.id
        user_data_store[chat_id] = {} # Initialize empty dict for this user
        
        msg = bot.send_message(chat_id, "Siap! Pengingat untuk acara apa? (Kirimkan pesan utamanya)")
        # Register the next function to capture the user's reply
        bot.register_next_step_handler(msg, ask_date, bot)

def ask_date(message, bot):
    """Stores the message and asks for the target date."""
    chat_id = message.chat.id
    
    # Check if user cancels
    if message.text.startswith('/'):
        bot.send_message(chat_id, "Pembuatan pengingat dibatalkan.")
        user_data_store.pop(chat_id, None)
        return

    user_data_store[chat_id]['message'] = message.text
    
    msg = bot.send_message(
        chat_id, 
        "Pesan dicatat. Kapan tanggal target atau hari-H nya?\n(Format: YYYY-MM-DD, contoh: 2026-06-15)"
    )
    bot.register_next_step_handler(msg, ask_prep_days, bot)

def ask_prep_days(message, bot):
    """Stores the date and asks for preparation days."""
    chat_id = message.chat.id
    date_text = message.text

    if date_text.startswith('/'):
        bot.send_message(chat_id, "Pembuatan pengingat dibatalkan.")
        user_data_store.pop(chat_id, None)
        return

    try:
        # Validate date format
        datetime.strptime(date_text, "%Y-%m-%d")
        user_data_store[chat_id]['target_date'] = date_text
        
        msg = bot.send_message(
            chat_id, 
            f"Berapa hari sebelum tanggal {date_text} saya harus mulai mengingatkan Anda?\n(Ketik angkanya saja, misal: 3)"
        )
        bot.register_next_step_handler(msg, ask_time, bot)
    except ValueError:
        msg = bot.send_message(chat_id, "⚠️ Format salah. Silakan gunakan format YYYY-MM-DD (contoh: 2026-06-15):")
        bot.register_next_step_handler(msg, ask_prep_days, bot) # Re-ask this step

def ask_time(message, bot):
    """Stores prep days and asks for notification time."""
    chat_id = message.chat.id
    prep_text = message.text

    if prep_text.startswith('/'):
        bot.send_message(chat_id, "Pembuatan pengingat dibatalkan.")
        user_data_store.pop(chat_id, None)
        return

    if not prep_text.isdigit():
        msg = bot.send_message(chat_id, "⚠️ Harap masukkan angka saja (contoh: 3):")
        bot.register_next_step_handler(msg, ask_time, bot)
        return
    
    user_data_store[chat_id]['prep_days'] = int(prep_text)
    
    msg = bot.send_message(
        chat_id, 
        "Di jam berapa saya harus mengirimkan pengingat ini setiap harinya?\n(Format: HH:MM, contoh: 07:00)"
    )
    bot.register_next_step_handler(msg, save_reminder, bot)

def save_reminder(message, bot):
    """Stores the time, saves everything to SQLite, and ends conversation."""
    chat_id = message.chat.id
    time_text = message.text

    if time_text.startswith('/'):
        bot.send_message(chat_id, "Pembuatan pengingat dibatalkan.")
        user_data_store.pop(chat_id, None)
        return

    try:
        # Validate time format
        datetime.strptime(time_text, "%H:%M")
        
        # Retrieve all stored data
        data = user_data_store.get(chat_id)
        if not data:
            bot.send_message(chat_id, "⚠️ Terjadi kesalahan data sesi. Silakan ulangi /add_reminder.")
            return

        msg_content = data['message']
        target_date = data['target_date']
        prep_days = data['prep_days']
        
        # Insert to database
        insert_reminder(chat_id, msg_content, target_date, time_text, prep_days)
        
        bot.send_message(
            chat_id,
            f"✅ <b>Pengingat berhasil diatur!</b>\n\n"
            f"<b>Pesan:</b> '{msg_content}'\n"
            f"<b>Waktu:</b> Setiap jam {time_text} WIB, mulai H-{prep_days} sebelum tanggal {target_date}.",
            parse_mode="HTML"
        )
        
        # Clear cache session
        user_data_store.pop(chat_id, None)
        
    except ValueError:
        msg = bot.send_message(chat_id, "⚠️ Format waktu salah. Gunakan format HH:MM (contoh: 07:00):")
        bot.register_next_step_handler(msg, save_reminder, bot)

# ----------------- BACKGROUND SCHEDULER LOGIC -----------------

def jalankan_scheduler(bot):
    """
    Background job loop that runs every minute to check 
    and send out active due reminders.
    """
    while True:
        try:
            now = datetime.now(LOCAL_TZ)
            current_time_str = now.strftime("%H:%M")
            current_date = now.date()
            
            # Fetch due reminders from DB matching current HH:MM
            due_reminders = get_due_reminders(current_time_str)
            
            for reminder in due_reminders:
                r_id, chat_id, message, target_date_str, prep_days = reminder
                target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
                
                # Calculate days difference
                days_left = (target_date - current_date).days
                
                # Verify if today falls into the notification active days window
                if 0 <= days_left <= prep_days:
                    if days_left == 0:
                        header = "🚨 <b>REMINDER HARI INI!</b> 🚨"
                        # Deactivate completed reminder row
                        mark_reminder_completed(r_id)
                    elif days_left == 1:
                        header = "🔔 <b>REMINDER (BESOK!)</b> 🔔"
                    else:
                        header = f"🔔 <b>REMINDER (H-{days_left})</b> 🔔"
                        
                    full_message = f"{header}\n\n{message}"
                    
                    try:
                        bot.send_message(chat_id=chat_id, text=full_message, parse_mode="HTML")
                    except Exception as e:
                        logging.error(f"Failed to send reminder {r_id} to {chat_id}: {e}")
                        
        except Exception as e:
            logging.error(f"Error inside scheduler loop: {e}")
            
        # Sleep for 60 seconds to match the clock resolution
        time.sleep(60)