import os
import json
import html
from telebot import types
from datetime import datetime
from .database import (
    setup_database, get_draft, update_draft_status, update_draft_summary,
    update_telegram_message_info, get_recent_drafts, register_user_credential,
    get_user_by_chat_id, get_user_credential, regenerate_api_token,
    delete_user_credential, get_all_users
)
from .website import submit_logbook_to_dermaga, fetch_dermaga_table, test_dermaga_login
from .server import run_http_server

def get_admin_chat_id() -> str:
    raw = os.environ.get('ADMIN_CHAT_ID', '')
    return raw.strip("'\" ")

def get_logbook_public_url() -> str:
    raw = os.environ.get('LOGBOOK_PUBLIC_URL', 'http://127.0.0.1:8088/api/logbook')
    return raw.strip("'\" ")

def is_admin(chat_or_user_id) -> bool:
    admin_id = get_admin_chat_id()
    if not admin_id:
        return True
    return str(chat_or_user_id).strip() == admin_id

def check_message_admin(message) -> bool:
    """Periksa apakah chat.id atau from_user.id merupakan admin."""
    if is_admin(message.chat.id):
        return True
    if getattr(message, 'from_user', None) and is_admin(message.from_user.id):
        return True
    return False

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
    """Mengirim pesan konfirmasi draf baru ke Telegram Pengguna terkait."""
    draft = get_draft(draft_id)
    if not draft:
        return

    chat_id = draft.get('chat_id')
    if not chat_id:
        admin_id_str = get_admin_chat_id()
        chat_id = int(admin_id_str) if admin_id_str.isdigit() else admin_id_str

    if not chat_id:
        print(f"[LOGBOOK - WARN] Tidak ada target chat_id untuk draf #{draft_id}, notifikasi dilewati.")
        return

    text = format_draft_message(draft)
    markup = build_draft_keyboard(draft_id)

    try:
        msg = bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
        update_telegram_message_info(draft_id, msg.chat.id, msg.message_id)
        print(f"[LOGBOOK] Pesan konfirmasi draf #{draft_id} terkirim ke User ({chat_id}).")
    except Exception as e:
        print(f"[LOGBOOK - ERROR] Gagal mengirim pesan konfirmasi draf #{draft_id} ke {chat_id}: {e}")

def handle_edit_input(message, bot, draft_id: int):
    """Handler langkah berikutnya untuk menerima teks revisi ringkasan."""
    draft = get_draft(draft_id)
    if not draft:
        bot.send_message(message.chat.id, "❌ Draf tidak ditemukan.")
        return

    if draft.get('chat_id') and message.chat.id != draft.get('chat_id') and not is_admin(message.chat.id):
        bot.send_message(message.chat.id, "⛔ Akses ditolak. Ini bukan draf Anda.")
        return

    new_text = message.text.strip()
    if not new_text or new_text.startswith('/'):
        bot.send_message(message.chat.id, "❌ Perubahan dibatalkan atau format tidak valid.")
        return

    update_draft_summary(draft_id, new_text)
    updated_draft = get_draft(draft_id)

    text = format_draft_message(updated_draft)
    markup = build_draft_keyboard(draft_id)

    bot.send_message(
        message.chat.id,
        "✅ <b>Ringkasan berhasil diperbarui!</b>\nBerikut draf yang siap disetujui ulang:\n\n" + text,
        parse_mode="HTML",
        reply_markup=markup
    )

def render_logbook_menu(chat_id: int, user_id: int = None) -> tuple:
    """Helper untuk merender tampilan menu utama /logbook beserta Inline Keyboard."""
    user_meta = get_user_by_chat_id(chat_id)
    admin = is_admin(chat_id) or (user_id and is_admin(user_id))

    markup = types.InlineKeyboardMarkup(row_width=2)

    if not user_meta and not admin:
        text = (
            "📖 <b>Pusat Kendali Logbook DERMAGA</b>\n\n"
            "⚠️ <b>Akun Anda belum terdaftar.</b>\n\n"
            "Untuk mulai menggunakan otomatisasi logbook harian, daftarkan akun DERMAGA Anda:\n"
            "👉 <code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code>\n\n"
            "<i>Catatan: Pesan yang berisi password akan langsung dihapus otomatis oleh bot demi keamanan.</i>"
        )
        markup.add(types.InlineKeyboardButton("🔄 Refresh Status", callback_data="log_menu_refresh"))
        return text, markup

    drafts = get_recent_drafts(chat_id=chat_id, limit=5) if user_meta else []
    username_str = user_meta['username'] if user_meta else "(Admin Mode)"
    token_str = (user_meta['api_token'][:8] + "..." + user_meta['api_token'][-6:]) if (user_meta and user_meta.get('api_token')) else "-"

    text = (
        f"📖 <b>Pusat Kendali Logbook DERMAGA</b>\n"
        f"👤 Akun DERMAGA: <code>{username_str}</code>\n"
        f"🔑 Token CLI: <code>{token_str}</code>\n\n"
        f"<b>Riwayat Draf Anda Terakhir:</b>\n"
    )

    if not drafts:
        text += "<i>Belum ada draf logbook tercatat untuk akun Anda.</i>\n"
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

    if admin:
        total_users = len(get_all_users())
        text += f"\n👑 <b>Admin Panel:</b>\n• Total Pengguna Terdaftar: <b>{total_users}</b>\n"

    text += "\nSilakan pilih menu di bawah ini:"

    # Tombol interaktif utama
    btn_cek = types.InlineKeyboardButton("📋 Cek Logbook", callback_data="log_menu_cek")
    btn_token = types.InlineKeyboardButton("🔑 Token CLI", callback_data="log_menu_token")
    btn_refresh = types.InlineKeyboardButton("🔄 Refresh", callback_data="log_menu_refresh")
    btn_hapus = types.InlineKeyboardButton("🗑️ Hapus Akun", callback_data="log_menu_hapus")
    markup.add(btn_cek, btn_token)
    markup.add(btn_refresh, btn_hapus)

    if admin:
        btn_admin = types.InlineKeyboardButton("👥 Daftar Pengguna (Admin)", callback_data="log_menu_admin_users")
        markup.add(btn_admin)

    return text, markup

def init_logbook(bot):
    """Inisialisasi modul logbook, database, command Telegram, dan callback."""
    setup_database()
    print("[+] Module Logbook: Database & services ready (Multi-User enabled).")

    @bot.message_handler(commands=['logbook'])
    def cmd_logbook(message):
        from_id = getattr(message, 'from_user', None).id if getattr(message, 'from_user', None) else None
        text, markup = render_logbook_menu(message.chat.id, from_id)
        bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

    @bot.message_handler(commands=['daftar_logbook', 'login_logbook', 'set_dermaga_auth'])
    def cmd_daftar_logbook(message):
        # 1. Hapus pesan sensitif dari obrolan
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass

        parts = message.text.split()
        if len(parts) < 3:
            bot.send_message(
                message.chat.id,
                "❌ Format salah.\n"
                "Gunakan: <code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code>\n\n"
                "<i>Contoh:</i> <code>/daftar_logbook 2341720117 Rahasia123</code>",
                parse_mode="HTML"
            )
            return

        username = parts[1].strip()
        password = parts[2].strip()

        loading = bot.send_message(
            message.chat.id,
            f"⏳ <i>Sedang menguji autentikasi akun <code>{username}</code> ke portal DERMAGA...</i>",
            parse_mode="HTML"
        )

        ok, msg = test_dermaga_login(username, password)
        if not ok:
            bot.edit_message_text(
                f"❌ <b>Verifikasi DERMAGA Gagal!</b>\n\n{msg}\n\n"
                f"Silakan periksa kembali username/NIM dan password Anda.",
                message.chat.id,
                loading.message_id,
                parse_mode="HTML"
            )
            return

        try:
            token = register_user_credential(message.chat.id, username, password)
            success_text = (
                f"🎉 <b>Pendaftaran Logbook DERMAGA Berhasil!</b>\n\n"
                f"👤 Akun: <code>{username}</code>\n"
                f"🔑 <b>API Token CLI Anda:</b>\n"
                f"<code>{token}</code>\n\n"
                f"📦 <b>Download Logbook CLI:</b>\n"
                f"• <a href=\"https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-windows-x64.zip\">Windows (ZIP)</a> | <a href=\"https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-linux-x64.zip\">Linux (ZIP)</a>\n\n"
                f"📋 <b>Konfigurasi di Laptop / CLI Anda:</b>\n"
                f"Ekstrak ZIP, salin file <code>config.example.json</code> menjadi <code>config.json</code>, lalu sesuaikan field <code>api_token</code>:\n"
                f"<pre>"
                f'{{\n'
                f'  "vps_endpoint": "{get_logbook_public_url()}",\n'
                f'  "api_token": "{token}"\n'
                f'}}'
                f"</pre>\n"
                f"💡 <i>Token ini unik untuk Anda. Jika lupa, cek kapan saja melalui menu <code>/logbook</code> atau tombol '🔑 Token CLI'.</i>"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📖 Buka Menu Logbook", callback_data="log_menu_back"))
            bot.edit_message_text(success_text, message.chat.id, loading.message_id, parse_mode="HTML", reply_markup=markup)
            print(f"[LOGBOOK] User {message.chat.id} ({username}) berhasil terdaftar/update.")
        except Exception as e:
            bot.edit_message_text(f"❌ Terjadi kesalahan saat menyimpan akun: {e}", message.chat.id, loading.message_id)

    @bot.message_handler(commands=['token_logbook'])
    def cmd_token_logbook(message):
        user = get_user_by_chat_id(message.chat.id)
        if not user:
            bot.send_message(
                message.chat.id,
                "⚠️ Akun Anda belum terdaftar.\n"
                "Gunakan <code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code> untuk mendaftar.",
                parse_mode="HTML"
            )
            return

        token = user['api_token']
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Buat Ulang Token", callback_data="log_regen_token"))
        markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))

        text = (
            f"🔑 <b>API Token CLI Logbook Anda</b>\n\n"
            f"👤 Akun: <code>{user['username']}</code>\n"
            f"Token:\n<code>{token}</code>\n\n"
            f"📦 <b>Download Logbook CLI:</b>\n"
            f"• <a href=\"https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-windows-x64.zip\">Windows (ZIP)</a> | <a href=\"https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-linux-x64.zip\">Linux (ZIP)</a>\n\n"
            f"📋 <b>Konfigurasi di Laptop:</b>\n"
            f"Ekstrak ZIP, salin file <code>config.example.json</code> menjadi <code>config.json</code>, lalu sesuaikan field <code>api_token</code>:\n"
            f"<pre>"
            f'{{\n'
            f'  "vps_endpoint": "{get_logbook_public_url()}",\n'
            f'  "api_token": "{token}"\n'
            f'}}'
            f"</pre>"
        )
        bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

    @bot.message_handler(commands=['cek_logbook'])
    def cmd_cek_logbook(message):
        user = get_user_by_chat_id(message.chat.id)
        if not user:
            bot.send_message(
                message.chat.id,
                "⚠️ Akun DERMAGA Anda belum terdaftar di bot ini.\n"
                "Silakan daftar terlebih dahulu menggunakan:\n"
                "<code>/daftar_logbook &lt;username&gt; &lt;password&gt;</code>",
                parse_mode="HTML"
            )
            return

        loading = bot.send_message(message.chat.id, "⏳ <i>Sedang mengambil data tabel logbook dari DERMAGA...</i>", parse_mode="HTML")
        try:
            entries = fetch_dermaga_table(chat_id=message.chat.id)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))

            if not entries:
                bot.edit_message_text(
                    f"ℹ️ Belum ada entri logbook yang tercatat di tabel DERMAGA akun <code>{user['username']}</code>.",
                    message.chat.id,
                    loading.message_id,
                    parse_mode="HTML",
                    reply_markup=markup
                )
                return

            text = f"📋 <b>Daftar Logbook DERMAGA ({len(entries)} Entri) - {user['username']}:</b>\n\n"
            for e in entries[:10]:
                desc = html.escape(e['pekerjaan'])
                if len(desc) > 160:
                    desc = desc[:157] + "..."
                text += (
                    f"📅 <b>{e['tanggal_text']}</b> (ID: <code>#{e['web_id'] or '-'}</code>)\n"
                    f"⏱️ <code>{e['jam']}</code> | Ket: <b>{e['keterangan']}</b> | Status: <b>{e['status_verif']}</b>\n"
                    f"📝 <i>{desc}</i>\n\n"
                )

            if len(entries) > 10:
                text += f"<i>...dan {len(entries) - 10} entri lainnya di DERMAGA.</i>"

            bot.edit_message_text(text, message.chat.id, loading.message_id, parse_mode="HTML", reply_markup=markup)
        except Exception as err:
            bot.edit_message_text(f"❌ Gagal mengambil data DERMAGA: {err}", message.chat.id, loading.message_id)

    @bot.message_handler(commands=['hapus_akun_logbook'])
    def cmd_hapus_akun(message):
        user = get_user_by_chat_id(message.chat.id)
        if not user:
            bot.send_message(message.chat.id, "ℹ️ Anda belum terdaftar di sistem logbook.")
            return

        delete_user_credential(message.chat.id)
        bot.send_message(
            message.chat.id,
            f"✅ Kredensial dan API Token untuk akun <code>{user['username']}</code> telah dihapus dari sistem bot.",
            parse_mode="HTML"
        )

    @bot.message_handler(commands=['admin_logbook'])
    def cmd_admin_logbook(message):
        if not check_message_admin(message):
            bot.send_message(message.chat.id, "⛔ Akses ditolak. Hanya untuk Admin.")
            return

        users = get_all_users()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))

        if not users:
            bot.send_message(message.chat.id, "ℹ️ Belum ada pengguna logbook yang terdaftar.", reply_markup=markup)
            return

        text = f"👥 <b>Daftar Pengguna Logbook Terdaftar ({len(users)} User):</b>\n\n"
        for u in users:
            status = "🟢 Aktif" if u['is_active'] else "🔴 Nonaktif"
            token_snippet = u['api_token'][:6] + "..." + u['api_token'][-4:]
            text += (
                f"• 👤 <b>{u['username']}</b>\n"
                f"  Chat ID: <code>{u['chat_id']}</code>\n"
                f"  Token: <code>{token_snippet}</code> | Status: {status}\n"
                f"  Terdaftar: <code>{u['created_at']}</code>\n\n"
            )
        bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('log_'))
    def callback_logbook(call):
        data = call.data

        # --- MENU CALLBACKS (IN-PLACE NAVIGATION) ---
        if data in ("log_menu_refresh", "log_menu_back"):
            bot.answer_callback_query(call.id)
            text, markup = render_logbook_menu(call.message.chat.id, call.from_user.id)
            try:
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            except Exception:
                pass
            return

        elif data == "log_menu_cek":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.message.chat.id)
            if not user:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                bot.edit_message_text("⚠️ Akun DERMAGA Anda belum terdaftar.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                return

            try:
                bot.edit_message_text("⏳ <i>Sedang mengambil data tabel logbook dari DERMAGA...</i>", call.message.chat.id, call.message.message_id, parse_mode="HTML")
            except Exception:
                pass

            try:
                entries = fetch_dermaga_table(chat_id=call.message.chat.id)
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))

                if not entries:
                    text = f"ℹ️ Belum ada entri logbook yang tercatat di tabel DERMAGA akun <code>{user['username']}</code>."
                else:
                    text = f"📋 <b>Daftar Logbook DERMAGA ({len(entries)} Entri) - {user['username']}:</b>\n\n"
                    for e in entries[:10]:
                        desc = html.escape(e['pekerjaan'])
                        if len(desc) > 160:
                            desc = desc[:157] + "..."
                        text += (
                            f"📅 <b>{e['tanggal_text']}</b> (ID: <code>#{e['web_id'] or '-'}</code>)\n"
                            f"⏱️ <code>{e['jam']}</code> | Ket: <b>{e['keterangan']}</b> | Status: <b>{e['status_verif']}</b>\n"
                            f"📝 <i>{desc}</i>\n\n"
                        )
                    if len(entries) > 10:
                        text += f"<i>...dan {len(entries) - 10} entri lainnya di DERMAGA.</i>"

                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            except Exception as err:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                bot.edit_message_text(f"❌ Gagal mengambil data DERMAGA: {err}", call.message.chat.id, call.message.message_id, reply_markup=markup)
            return

        elif data == "log_menu_token":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.message.chat.id)
            if not user:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                bot.edit_message_text("⚠️ Akun Anda belum terdaftar.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                return

            token_val = user.get('api_token', '')
            text = (
                f"🔑 <b>API Token CLI Logbook Anda</b>\n\n"
                f"👤 Akun: <code>{user['username']}</code>\n"
                f"Token:\n<code>{token_val}</code>\n\n"
                f"📦 <b>Download Logbook CLI:</b>\n"
                f"• <a href=\"https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-windows-x64.zip\">Windows (ZIP)</a> | <a href=\"https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-linux-x64.zip\">Linux (ZIP)</a>\n\n"
                f"📋 <b>Konfigurasi di Laptop:</b>\n"
                f"Ekstrak ZIP, salin file <code>config.example.json</code> menjadi <code>config.json</code>, lalu sesuaikan field <code>api_token</code>:\n"
                f"<pre>"
                f'{{\n'
                f'  "vps_endpoint": "{get_logbook_public_url()}",\n'
                f'  "api_token": "{token_val}"\n'
                f'}}'
                f"</pre>"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔄 Buat Ulang Token", callback_data="log_regen_token"))
            markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            return

        elif data == "log_regen_token":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.from_user.id)
            if not user:
                bot.send_message(call.message.chat.id, "❌ Akun tidak ditemukan.")
                return

            new_token = regenerate_api_token(call.from_user.id)
            text = (
                f"🔄 <b>API Token Berhasil Dibuat Ulang!</b>\n\n"
                f"👤 Akun: <code>{user['username']}</code>\n"
                f"Token Baru:\n<code>{new_token}</code>\n\n"
                f"⚠️ Jangan lupa untuk memperbarui field <code>api_token</code> pada file <code>config.json</code> di laptop Anda."
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            return

        elif data == "log_menu_hapus":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.message.chat.id)
            if not user:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
                bot.edit_message_text("ℹ️ Anda belum terdaftar di sistem logbook.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                return

            text = (
                f"⚠️ <b>Konfirmasi Hapus Akun Logbook</b>\n\n"
                f"Apakah Anda yakin ingin menghapus kredensial DERMAGA akun <code>{user['username']}</code> dan API Token Anda dari bot?\n\n"
                f"<i>Tindakan ini tidak dapat dibatalkan. Riwayat draf logbook lama Anda juga akan terhapus.</i>"
            )
            markup = types.InlineKeyboardMarkup(row_width=2)
            btn_confirm = types.InlineKeyboardButton("⚠️ Ya, Hapus Akun", callback_data="log_confirm_hapus_akun")
            btn_cancel = types.InlineKeyboardButton("❌ Batal", callback_data="log_menu_back")
            markup.add(btn_confirm, btn_cancel)
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            return

        elif data == "log_confirm_hapus_akun":
            bot.answer_callback_query(call.id)
            user = get_user_by_chat_id(call.message.chat.id)
            if user:
                delete_user_credential(call.message.chat.id)
                text = f"✅ Akun <code>{user['username']}</code> dan token Anda berhasil dihapus dari sistem bot."
            else:
                text = "ℹ️ Akun tidak ditemukan atau sudah dihapus."
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            return

        elif data == "log_menu_admin_users":
            bot.answer_callback_query(call.id)
            if not is_admin(call.from_user.id) and not (call.message and is_admin(call.message.chat.id)):
                bot.answer_callback_query(call.id, "⛔ Akses ditolak. Hanya untuk Admin.", show_alert=True)
                return

            users = get_all_users()
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬅️ Kembali ke Menu Logbook", callback_data="log_menu_back"))

            if not users:
                text = "👥 <b>Admin Panel Logbook</b>\n\n<i>Belum ada pengguna logbook yang terdaftar.</i>"
            else:
                text = f"👥 <b>Daftar Pengguna Logbook Terdaftar ({len(users)} User):</b>\n\n"
                for u in users:
                    status = "🟢 Aktif" if u['is_active'] else "🔴 Nonaktif"
                    token_snippet = u['api_token'][:6] + "..." + u['api_token'][-4:]
                    text += (
                        f"• 👤 <b>{u['username']}</b>\n"
                        f"  Chat ID: <code>{u['chat_id']}</code>\n"
                        f"  Token: <code>{token_snippet}</code> | Status: {status}\n"
                        f"  Terdaftar: <code>{u['created_at']}</code>\n\n"
                    )
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            return

        # --- DRAFT CALLBACKS (SUBMIT / OVERRIDE / SKIP / EDIT / CANCEL) ---
        draft_id = None
        if data.startswith(('log_confirm_', 'log_skip_', 'log_edit_', 'log_cancel_')):
            draft_id = int(data.split('_')[2])
        elif data.startswith('log_over_'):
            draft_id = int(data.split('_')[2])

        if not draft_id:
            bot.answer_callback_query(call.id, "Data callback tidak valid.", show_alert=True)
            return

        draft = get_draft(draft_id)
        if not draft:
            bot.answer_callback_query(call.id, "Draf tidak ditemukan.", show_alert=True)
            return

        # Cek otorisasi user: hanya pemilik draft atau bot admin yang diizinkan
        is_owner = (draft.get('chat_id') and call.from_user.id == draft.get('chat_id'))
        is_bot_admin = is_admin(call.from_user.id) or (call.message and is_admin(call.message.chat.id))

        if not (is_owner or is_bot_admin):
            bot.answer_callback_query(call.id, "⛔ Akses ditolak. Anda bukan pemilik draf ini.", show_alert=True)
            return

        bot.answer_callback_query(call.id)

        # 1. Konfirmasi Submit
        if data.startswith('log_confirm_'):
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
            web_id = parts[3]

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
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            update_draft_status(draft_id, 'skipped')
            bot.send_message(call.message.chat.id, f"⏩ Draf logbook #{draft_id} ditandai selesai (dilewati). Data di DERMAGA tidak diubah.")

        # 4. Ubah draf
        elif data.startswith('log_edit_'):
            prompt_msg = bot.send_message(
                call.message.chat.id,
                f"✏️ <b>Edit Draf #{draft_id}</b>\nSilakan ketik atau tempel teks ringkasan logbook baru:",
                parse_mode="HTML"
            )
            bot.register_next_step_handler(prompt_msg, handle_edit_input, bot, draft_id)

        # 5. Batalkan draf
        elif data.startswith('log_cancel_'):
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
