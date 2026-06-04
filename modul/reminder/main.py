import logging
from datetime import datetime
import pytz
from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters
)
from .database import setup_database, insert_reminder, get_due_reminders, mark_reminder_completed

# Define conversation states
TARGET_MESSAGE, TARGET_DATE, PREP_DAYS, NOTIFY_TIME = range(4)

# Set the timezone
LOCAL_TZ = pytz.timezone('Asia/Jakarta')

async def start_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation and asks for the reminder message."""
    await update.message.reply_text(
        "Siap! Pengingat untuk acara apa? (Kirimkan pesan utamanya)"
    )
    return TARGET_MESSAGE

async def ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the message and asks for the target date."""
    context.user_data['message'] = update.message.text
    await update.message.reply_text(
        "Pesan dicatat. Kapan tanggal target atau hari-H nya?\n"
        "(Format: YYYY-MM-DD, contoh: 2026-06-15)"
    )
    return TARGET_DATE

async def ask_prep_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the date and asks for preparation days."""
    date_text = update.message.text
    try:
        # Validate date format
        datetime.strptime(date_text, "%Y-%m-%d")
        context.user_data['target_date'] = date_text
        
        await update.message.reply_text(
            f"Berapa hari sebelum tanggal {date_text} saya harus mulai mengingatkan Anda?\n"
            "(Ketik angkanya saja, misal: 3)"
        )
        return PREP_DAYS
    except ValueError:
        await update.message.reply_text("Format salah. Silakan gunakan format YYYY-MM-DD (contoh: 2026-06-15).")
        return TARGET_DATE

async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores prep days and asks for notification time."""
    prep_text = update.message.text
    if not prep_text.isdigit():
        await update.message.reply_text("Harap masukkan angka saja (contoh: 3).")
        return PREP_DAYS
    
    context.user_data['prep_days'] = int(prep_text)
    await update.message.reply_text(
        "Di jam berapa saya harus mengirimkan pengingat ini setiap harinya?\n"
        "(Format: HH:MM, contoh: 07:00)"
    )
    return NOTIFY_TIME

async def save_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the time, saves everything to DB, and ends conversation."""
    time_text = update.message.text
    try:
        # Validate time format
        datetime.strptime(time_text, "%H:%M")
        
        chat_id = update.effective_chat.id
        message = context.user_data['message']
        target_date = context.user_data['target_date']
        prep_days = context.user_data['prep_days']
        
        # Insert to database
        insert_reminder(chat_id, message, target_date, time_text, prep_days)
        
        await update.message.reply_text(
            f"✅ Pengingat berhasil diatur!\n"
            f"Saya akan mengingatkan tentang: '{message}'\n"
            f"Setiap jam {time_text} WIB, mulai H-{prep_days} sebelum tanggal {target_date}."
        )
        # Clear user data
        context.user_data.clear()
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("Format waktu salah. Gunakan format HH:MM (contoh: 07:00).")
        return NOTIFY_TIME

async def cancel_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text("Pembuatan pengingat dibatalkan.")
    context.user_data.clear()
    return ConversationHandler.END

# ----------------- SCHEDULER LOGIC -----------------

async def check_reminders_job(context: ContextTypes.DEFAULT_TYPE):
    """Background job that runs every minute to check and send reminders."""
    now = datetime.now(LOCAL_TZ)
    current_time_str = now.strftime("%H:%M")
    current_date = now.date()
    
    # Get reminders that are scheduled for this exact minute
    due_reminders = get_due_reminders(current_time_str)
    
    for reminder in due_reminders:
        r_id, chat_id, message, target_date_str, prep_days = reminder
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        
        # Calculate days difference
        days_left = (target_date - current_date).days
        
        # Check if today is within the preparation window
        if 0 <= days_left <= prep_days:
            if days_left == 0:
                header = "🚨 **REMINDER HARI INI!** 🚨"
                # Mark as completed so it won't trigger tomorrow
                mark_reminder_completed(r_id)
            elif days_left == 1:
                header = "🔔 **REMINDER (BESOK!)** 🔔"
            else:
                header = f"🔔 **REMINDER (H-{days_left})** 🔔"
                
            full_message = f"{header}\n\n{message}"
            
            try:
                await context.bot.send_message(chat_id=chat_id, text=full_message)
            except Exception as e:
                logging.error(f"Failed to send reminder {r_id} to {chat_id}: {e}")

# ----------------- MODULE EXPORT -----------------

def get_reminder_handler():
    """Returns the ConversationHandler to be added to the main application."""
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('add_reminder', start_reminder)],
        states={
            TARGET_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_date)],
            TARGET_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_prep_days)],
            PREP_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_time)],
            NOTIFY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_reminder)],
        },
        fallbacks=[CommandHandler('cancel', cancel_reminder)],
    )
    return conv_handler