import logging
import time
from datetime import datetime
import pytz
from telebot import types
from .database import (
    setup_database, insert_reminder, get_due_reminders, mark_reminder_completed,
    get_active_reminders_by_chat, delete_reminder, update_reminder_field
)

# Set the timezone
LOCAL_TZ = pytz.timezone('Asia/Jakarta')

# Global dictionary to store temporary user data during conversation
user_data_store = {}

def init_reminder(bot):
    """
    Initializes the reminder module by creating the database table 
    and registering commands.
    """
    setup_database()
    print("[+] Module Reminder: Database ready.")

    @bot.message_handler(commands=['reminder'])
    def show_reminder_hub(message):
        chat_id = message.chat.id
        reminders = get_active_reminders_by_chat(chat_id)
        
        text = "📅 <b>Daftar Pengingat Aktif Anda:</b>\n\n"
        if not reminders:
            text += "<i>Anda belum memiliki pengingat yang aktif saat ini.</i>"
        else:
            for idx, r in enumerate(reminders, 1):
                r_id, r_msg, r_date, r_time, r_prep = r
                text += f"{idx}. <b>{r_msg}</b>\n   🗓 Hari-H: <code>{r_date}</code> ({r_time} WIB) | ⏳ H-{r_prep}\n\n"
        
        # Create Inline Buttons for Hub
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_add = types.InlineKeyboardButton("➕ Tambah Pengingat", callback_data="rmd_hub_add")
        btn_edit = types.InlineKeyboardButton("📝 Edit Pengingat", callback_data="rmd_hub_edit")
        markup.add(btn_add, btn_edit)
        
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

    # Keep old command as shortcut if needed, or you can delete it
    @bot.message_handler(commands=['add_reminder'])
    def start_reminder(message):
        chat_id = message.chat.id
        user_data_store[chat_id] = {}
        msg = bot.send_message(chat_id, "Siap! Pengingat untuk acara apa? (Kirimkan pesan utamanya)")
        bot.register_next_step_handler(msg, ask_date, bot)

    @bot.message_handler(commands=['edit_reminder'])
    def show_edit_menu(message):
        chat_id = message.chat.id
        reminders = get_active_reminders_by_chat(chat_id)
        
        if not reminders:
            bot.send_message(chat_id, "ℹ️ Anda tidak memiliki pengingat yang aktif saat ini.")
            return
            
        markup = types.InlineKeyboardMarkup(row_width=1)
        for r in reminders:
            r_id, r_msg, r_date, r_time, r_prep = r
            short_msg = r_msg[:20] + "..." if len(r_msg) > 20 else r_msg
            button_text = f"[{r_date}] {short_msg}"
            markup.add(types.InlineKeyboardButton(button_text, callback_data=f"rmd_sel_{r_id}"))
            
        bot.send_message(chat_id, "Pilih pengingat yang ingin Anda kelola:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('rmd_'))
    def handle_reminder_callback(call):
        chat_id = call.message.chat.id
        bot.answer_callback_query(call.id) # Answer immediately to avoid loading icon
        
        if call.data == "rmd_hub_add":
            user_data_store[chat_id] = {}
            msg = bot.send_message(chat_id, "Siap! Pengingat untuk acara apa? (Kirimkan pesan utamanya)")
            bot.register_next_step_handler(msg, ask_date, bot)
            return
            
        elif call.data == "rmd_hub_edit":
            # Call the existing edit list directly using call.message
            show_edit_menu(call.message)
            return

        if len(call.data) <= 8:
            return

        action = call.data[:7]  # e.g., 'rmd_sel', 'rmd_del'
        reminder_id = int(call.data[8:]) 

        if action == "rmd_sel":
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("📝 Ubah Pesan", callback_data=f"rmd_msg_{reminder_id}"),
                types.InlineKeyboardButton("📅 Ubah Tanggal", callback_data=f"rmd_dat_{reminder_id}"),
                types.InlineKeyboardButton("⏰ Ubah Jam", callback_data=f"rmd_tim_{reminder_id}"),
                types.InlineKeyboardButton("⏳ Ubah H-", callback_data=f"rmd_prp_{reminder_id}")
            )
            markup.add(types.InlineKeyboardButton("🗑️ Hapus Pengingat", callback_data=f"rmd_del_{reminder_id}"))
            markup.add(types.InlineKeyboardButton("❌ Batal", callback_data=f"rmd_ccl_0"))
            
            bot.edit_message_text(
                "Pilih bagian mana yang ingin diubah atau dihapus:",
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=markup
            )
            
        elif action == "rmd_del":
            delete_reminder(reminder_id)
            bot.edit_message_text("🗑️ <b>Pengingat berhasil dihapus!</b>", chat_id=chat_id, message_id=call.message.message_id, parse_mode="HTML")
            
        elif action == "rmd_ccl":
            bot.edit_message_text("✅ Operasi dibatalkan.", chat_id=chat_id, message_id=call.message.message_id)

        elif action == "rmd_msg":
            msg = bot.send_message(chat_id, "Kirimkan pesan baru untuk pengingat ini:")
            bot.register_next_step_handler(msg, update_field_process, bot, reminder_id, 'message')
            
        elif action == "rmd_dat":
            msg = bot.send_message(chat_id, "Kirimkan tanggal baru (Format: YYYY-MM-DD):")
            bot.register_next_step_handler(msg, update_field_process, bot, reminder_id, 'target_date')
            
        elif action == "rmd_tim":
            msg = bot.send_message(chat_id, "Kirimkan jam baru (Format: HH:MM):")
            bot.register_next_step_handler(msg, update_field_process, bot, reminder_id, 'notify_time')
            
        elif action == "rmd_prp":
            msg = bot.send_message(chat_id, "Berapa hari sebelumnya bot harus mengingatkan? (Ketik angka saja):")
            bot.register_next_step_handler(msg, update_field_process, bot, reminder_id, 'prep_days')

def ask_date(message, bot):
    """Stores the message and asks for the target date."""
    chat_id = message.chat.id
    
    # Check if user cancels
    if not message.text or message.text.startswith('/'):
        bot.send_message(chat_id, "Pembuatan pengingat dibatalkan (Atau input tidak valid).")
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

    if not date_text.text or date_text.startswith('/'):
        bot.send_message(chat_id, "Pembuatan pengingat dibatalkan (Atau input tidak valid).")
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

    if not prep_text.text or prep_text.startswith('/'):
        bot.send_message(chat_id, "Pembuatan pengingat dibatalkan (Atau input tidak valid).")
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

    if not time_text.text or time_text.startswith('/'):
        bot.send_message(chat_id, "Pembuatan pengingat dibatalkan (Atau input tidak valid).")
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

def update_field_process(message, bot, reminder_id, field):
    """Handles the user input for updating a specific field, including validation."""
    chat_id = message.chat.id
    new_val = message.text

    if not new_val.text or new_val.startswith('/'):
        bot.send_message(chat_id, "❌ Perubahan dibatalkan.")
        return

    try:
        # Validation rules based on the field being edited
        if field == 'target_date':
            datetime.strptime(new_val, "%Y-%m-%d")
        elif field == 'notify_time':
            datetime.strptime(new_val, "%H:%M")
        elif field == 'prep_days':
            if not new_val.isdigit():
                raise ValueError("Bukan angka")
            new_val = int(new_val) # Convert to integer for DB

        # Update the database if validation passes
        update_reminder_field(reminder_id, field, new_val)
        bot.send_message(chat_id, "✅ <b>Pengingat berhasil diperbarui!</b>", parse_mode="HTML")
        
    except ValueError:
        if field == 'target_date':
            bot.send_message(chat_id, "⚠️ Format tanggal salah. Pembaruan dibatalkan. Silakan ulangi /edit_reminder.")
        elif field == 'notify_time':
            bot.send_message(chat_id, "⚠️ Format jam salah. Pembaruan dibatalkan. Silakan ulangi /edit_reminder.")
        elif field == 'prep_days':
            bot.send_message(chat_id, "⚠️ Harap masukkan angka saja. Pembaruan dibatalkan. Silakan ulangi /edit_reminder.")

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