# Modul Pemantauan Magang (Status: Diarsipkan / Nonaktif)

Dokumen ini berisi panduan teknis mengenai modul **Magang**, status pengarsipannya, serta langkah-langkah untuk mengaktifkannya kembali di aplikasi `bot-services`.

---

## 📌 Deskripsi Modul

Modul Magang berfungsi untuk melakukan *scraping* dan pemantauan otomatis status pendaftaran magang mahasiswa pada portal JTI (`jti.polinema.ac.id/jtiportal`). Modul ini menyimpan kredensial terenkripsi (menggunakan Fernet) dan memberikan notifikasi Telegram saat terjadi perubahan status magang.

---

## ⚙️ Syarat Environment Variable

Jika modul ini diaktifkan, pastikan environment variable berikut telah dikonfigurasi:

```sh
export MAGANG_SECRET_KEY="kunci_fernet_anda"
```

---

## 🚀 Panduan Mengaktifkan Kembali Modul Magang

Untuk mengaktifkan kembali modul magang agar berjalan di bot, buka file **`main.py`** dan lakukan perubahan berikut:

### 1. Un-comment Import Modul (Baris ~11)
```python
# Hapus tanda # pada baris import
from modul.magang import main as magang
```

### 2. Un-comment Command Telegram (Baris ~30)
```python
# Pada fungsi setup_bot_commands():
types.BotCommand("magang", "Pusat kendali pemantauan magang"),
```

### 3. Un-comment Tombol Menu Utama (Baris ~46 & ~51)
```python
# Pada fungsi send_menu_utama(message):
tombol_magang = types.InlineKeyboardButton("🎓 Pusat Magang", callback_data="cb_magang")

# Dan tambahkan tombol_magang kembali ke markup:
markup.add(tombol_ping, tombol_magang, tombol_reminder, tombol_speed, tombol_bensin)
```

### 4. Un-comment Callback Handler (Baris ~71–73)
```python
# Pada fungsi callback_listener(call):
elif call.data == "cb_magang":
    call.message.text = "/magang"
    bot.process_new_messages([call.message])
```

### 5. Un-comment Inisialisasi Modul (Baris ~94)
```python
# Pada blok if __name__ == '__main__':
magang.init_magang(bot)
```

---

## 📁 Struktur File Modul Magang

- `modul/magang/main.py`: Logika scraping portal JTI, pengolah command `/magang`, dan background thread pemantauan.
- `modul/magang/database.py`: Operasi database SQLite (`users.db`) dan enkripsi/dekripsi password dengan Fernet.
- `tools/migrasi_db.py`: Script pembantu untuk migrasi database lama (plaintext ke Fernet encrypted).
