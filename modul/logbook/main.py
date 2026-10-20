import os
import json
import html
from telebot import types
from datetime import datetime
from .database import (
    setup_database, get_draft, update_draft_status, update_draft_summary,
    update_telegram_message_info, get_recent_drafts, set_active_credential,
    get_active_credential
)
from .website import submit_logbook_to_dermaga
from .server import run_http_server

ADMIN_CHAT_ID_STR = os.environ.get('ADMIN_CHAT_ID')
ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_STR) if ADMIN_CHAT_ID_STR else None

def is_admin(user_id: int) -> bool:
    if not ADMIN_CHAT_ID:
        return True
    return user_id == ADMIN_CHAT_ID

def format_draft_message(draft: dict) -> str:
    """Format tampilan pesan konfirmasi logbook ke Telegram HTML."""
    date = draft.get('date', '-')
    jam_masuk = draft.get('jam_masuk', '07:10')
    jam_pulang = draft.get('jam_pulang', '16:25')
    
    # Parse projects
    projects_raw = draft.get('projects', '[]')
    try:
        projects = json.loads(projects_raw) if isinstance(projects_raw, str) else projects_raw
        projects_str = ", ".join(projects) if isinstance(projects, list) else str(projects)
    except Exception:
        projects_str = str(projects_raw)

    summary = html.escape(draft.get('commits_summary', '-'))

    # Parse raw metadata commits
    commits_raw = draft.get('raw_metadata', '[]')
    commits_list = []
    try:
        commits = json.loads(commits_raw) if isinstance(commits_raw, str) else commits_raw
        if isinstance(commits, list):
            for c in commits:
                h = html.escape(str(c.get('hash', '')))
                subj = html.escape(str(c.get('subject', '')))
                proj = html.escape(str(c.get('project', '')))
                commits_list.append(f"• <code>[{proj}]</code> <code>{h}</code> {subj}")
    except Exception:
        pass

    commits_text = "\n".join(commits_list) if commits_list else "<i>Tidak ada metadata commit detail.</i>"

    text = (
        f"📖 <b>Draf Logbook Harian</b>\n\n"
        f"🗓 <b>Tanggal:</b> <code>{date}</code>\n"
        f"⏰ <b>Jam Kerja:</b> <code>{jam_masuk} - {jam_pulang}</code>\n"
        f"📦 <b>Proyek:</b> <b>{projects_str}</b>\n\n"
        f"📝 <b>Ringkasan Aktivitas:</b>\n"
        f"{summary}\n\n"
        f"🔨 <b>Daftar Commit Hari Ini:</b>\n"
        f"{commits_text}\n\n"
        f"Silakan konfirmasi untuk melakukan pengisian ke portal DERMAGA:"
    )
    return text

def build_draft_keyboard(draft_id: int):
    markup = types.InlineKeyboardMarkup(row_width=3)
    btn_confirm = types.InlineKeyboardButton("✅ Konfirmasi", callback_data=f"log_confirm_{draft_id}")
    btn_edit = types.InlineKeyboardButton("✏️ Ubah", callback_data=f"log_edit_{draft_id}")
    btn_cancel = types.InlineKeyboardButton("❌ Batal", callback_data=f"log_cancel_{draft_id}")
    markup.add(btn_confirm, btn_edit, btn_cancel)
    return markup

def send_draft_confirmation(bot, draft_id: int):
    """Mengirim pesan konfirmasi draf baru ke Telegram Admin."""
    if not ADMIN_CHAT_ID:
        print("[LOGBOOK - WARN] ADMIN_CHAT_ID belum diatur, notifikasi draf dilewati.")
        return

    draft = get_draft(draft_id)
    if not draft:
        return

    text = format_draft_message(draft)
    markup = build_draft_keyboard(draft_id)

    try:
        msg = bot.send_message(ADMIN_CHAT_ID, text, parse_mode="HTML", reply_markup=markup)
        update_telegram_message_info(draft_id, msg.chat.id, msg.message_id)
        print(f"[LOGBOOK] Pesan konfirmasi draf #{draft_id} terkirim ke Admin ({ADMIN_CHAT_ID}).")
    except Exception as e:
        print(f"[LOGBOOK - ERROR] Gagal mengirim pesan konfirmasi draf: {e}")

def handle_edit_input(message, bot, draft_id: int):
    """Handler langkah berikutnya untuk menerima teks revisi ringkasan."""
    if not is_admin(message.from_user.id):
        return

    new_text = message.text.strip()
    if not new_text or new_text.startswith('/'):
        bot.send_message(message.chat.id, "❌ Perubahan dibatalkan atau format tidak valid.")
        return

    update_draft_summary(draft_id, new_text)
    draft = get_draft(draft_id)

    text = format_draft_message(draft)
    markup = build_draft_keyboard(draft_id)

    bot.send_message(
        message.chat.id,
        "✅ <b>Ringkasan berhasil diperbarui!</b>\nBerikut draf yang siap disetujui ulang:\n\n" + text,
        parse_mode="HTML",
        reply_markup=markup
    )

def init_logbook(bot):
    """Inisialisasi modul logbook, database, command Telegram, dan callback."""
    setup_database()
    print("[+] Module Logbook: Database & services ready.")

    @bot.message_handler(commands=['logbook'])
    def cmd_logbook(message):
        if not is_admin(message.from_user.id):
            bot.send_message(message.chat.id, "⛔ Akses ditolak. Anda bukan admin bot.")
            return

        drafts = get_recent_drafts(limit=5)
        user, _ = get_active_credential()
        user_str = user if user else "Belum diatur"

        text = (
            f"📖 <b>Pusat Kendali Logbook DERMAGA</b>\n"
            f"👤 Akun login: <code>{user_str}</code>\n\n"
            f"<b>Riwayat Draf Terakhir:</b>\n"
        )

        if not drafts:
            text += "<i>Belum ada draf logbook tercatat.</i>"
        else:
            status_emojis = {
                'pending': '⏳ Pending',
                'approved': '👍 Disetujui',
                'submitted': '✅ Berhasil Submit',
                'skipped': '⏩ Dilewati',
                'cancelled': '❌ Dibatalkan',
                'failed': '⚠️ Gagal Submit'
            }
            for d in drafts:
                st = status_emojis.get(d['status'], d['status'])
                text += f"• #{d['id']} | <code>{d['date']}</code> | {st}\n"

        text += (
            f"\n💡 <b>Perintah pendukung:</b>\n"
            f"• <code>/set_dermaga_auth &lt;username&gt; &lt;password&gt;</code> untuk update akun login."
        )

        bot.send_message(message.chat.id, text, parse_mode="HTML")

    @bot.message_handler(commands=['set_dermaga_auth'])
    def cmd_set_auth(message):
        if not is_admin(message.from_user.id):
            bot.send_message(message.chat.id, "⛔ Akses ditolak.")
            return

        # Hapus pesan sensitif dari obrolan
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass

        parts = message.text.split()
        if len(parts) < 3:
            bot.send_message(message.chat.id, "❌ Format salah. Gunakan: <code>/set_dermaga_auth &lt;username&gt; &lt;password&gt;</code>", parse_mode="HTML")
            return

        username = parts[1].strip()
        password = parts[2].strip()
        set_active_credential(username, password)
        bot.send_message(message.chat.id, f"✅ Kredensial DERMAGA untuk akun <code>{username}</code> berhasil diperbarui dan dienkripsi.", parse_mode="HTML")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('log_'))
    def callback_logbook(call):
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "Akses ditolak.", show_alert=True)
            return

        bot.answer_callback_query(call.id)
        data = call.data

        # 1. Konfirmasi Submit
        if data.startswith('log_confirm_'):
            draft_id = int(data.replace('log_confirm_', ''))
            draft = get_draft(draft_id)
            if not draft:
                bot.send_message(call.message.chat.id, "❌ Draf tidak ditemukan.")
                return

            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            bot.send_message(call.message.chat.id, f"⏳ Sedang memproses submit logbook #{draft_id} ke DERMAGA...")

            res = submit_logbook_to_dermaga(draft)

            if res['status'] == 'EXISTS':
                # Tanggal sudah ada entri di website -> Beri pilihan Timpa / Biarkan
                web_id = res['web_id']
                existing_desc = html.escape(res.get('existing_deskripsi') or '-')
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                btn_over = types.InlineKeyboardButton("🔄 Timpa / Update", callback_data=f"log_over_{draft_id}_{web_id}")
                btn_skip = types.InlineKeyboardButton("⏩ Biarkan (Skip)", callback_data=f"log_skip_{draft_id}")
                markup.add(btn_over, btn_skip)

                msg_warning = (
                    f"⚠️ <b>Logbook Hari Ini Sudah Ada di DERMAGA!</b>\n\n"
                    f"Entri tanggal <code>{draft['date']}</code> sudah terdaftar dengan ID: <code>{web_id}</code>.\n\n"
                    f"<b>Deskripsi saat ini di website:</b>\n"
                    f"<i>{existing_desc}</i>\n\n"
                    f"Pilih tindakan yang ingin diambil:"
                )
                bot.send_message(call.message.chat.id, msg_warning, parse_mode="HTML", reply_markup=markup)

            elif res['status'] == 'SUCCESS':
                update_draft_status(draft_id, 'submitted')
                bot.send_message(call.message.chat.id, f"🎉 <b>Sukses!</b> {res['message']}", parse_mode="HTML")
            else:
                err_msg = res.get('message', 'Terjadi kesalahan')
                update_draft_status(draft_id, 'failed', error_message=err_msg)
                
                # Sediakan tombol coba lagi
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔄 Coba Submit Ulang", callback_data=f"log_confirm_{draft_id}"))
                bot.send_message(call.message.chat.id, f"❌ <b>Gagal Submit:</b> {err_msg}", parse_mode="HTML", reply_markup=markup)

        # 2. Timpa entri yang ada di website
        elif data.startswith('log_over_'):
            parts = data.split('_')
            draft_id = int(parts[2])
            web_id = parts[3]
            draft = get_draft(draft_id)
            if not draft:
                bot.send_message(call.message.chat.id, "❌ Draf tidak ditemukan.")
                return

            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            bot.send_message(call.message.chat.id, f"⏳ Sedang menimpa logbook ID <code>{web_id}</code> di DERMAGA...", parse_mode="HTML")

            res = submit_logbook_to_dermaga(draft, override_id=web_id)
            if res['status'] == 'SUCCESS':
                update_draft_status(draft_id, 'submitted')
                bot.send_message(call.message.chat.id, f"✅ <b>Logbook berhasil diperbarui</b> di portal DERMAGA!", parse_mode="HTML")
            else:
                err_msg = res.get('message', 'Gagal memperbarui logbook')
                update_draft_status(draft_id, 'failed', error_message=err_msg)
                bot.send_message(call.message.chat.id, f"❌ <b>Gagal Memperbarui:</b> {err_msg}", parse_mode="HTML")

        # 3. Biarkan entri lama (Skip)
        elif data.startswith('log_skip_'):
            draft_id = int(data.replace('log_skip_', ''))
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            update_draft_status(draft_id, 'skipped')
            bot.send_message(call.message.chat.id, f"⏩ Draf logbook #{draft_id} ditandai selesai (dilewati). Data di DERMAGA tidak diubah.")

        # 4. Ubah draf
        elif data.startswith('log_edit_'):
            draft_id = int(data.replace('log_edit_', ''))
            prompt_msg = bot.send_message(
                call.message.chat.id,
                f"✏️ <b>Edit Draf #{draft_id}</b>\nSilakan ketik atau tempel teks ringkasan logbook baru:",
                parse_mode="HTML"
            )
            bot.register_next_step_handler(prompt_msg, handle_edit_input, bot, draft_id)

        # 5. Batalkan draf
        elif data.startswith('log_cancel_'):
            draft_id = int(data.replace('log_cancel_', ''))
            update_draft_status(draft_id, 'cancelled')
            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            except Exception:
                pass
            bot.send_message(call.message.chat.id, f"❌ Draf logbook #{draft_id} telah <b>dibatalkan</b>.", parse_mode="HTML")

def jalankan_server(bot):
    """Runner thread untuk HTTP Server receiver yang meneruskan draf baru ke Telegram."""
    def on_new_draft(draft):
        send_draft_confirmation(bot, draft['id'])

    run_http_server(on_draft_cb=on_new_draft)
