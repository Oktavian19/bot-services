# Git Logbook Automation CLI

Script mandiri dan executable untuk membaca commit Git lokal, membuat ringkasan logbook naratif (OpenAI / non-AI), dan mengirimkannya ke bot VPS `bot-services` via HTTP POST idempoten.

---

## 📦 Unduh Binary Siap Pakai (Tanpa Install Python)

Anda bisa mengunduh file ZIP siap pakai langsung dari GitHub Releases:
- 🪟 **Windows (x64)**: [logbook-cli-windows-x64.zip](https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-windows-x64.zip)
- 🐧 **Linux (x64)**: [logbook-cli-linux-x64.zip](https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-linux-x64.zip)

Setelah di-ekstrak, file executable (`logbook_cli.exe` atau `logbook_cli`) dapat langsung dijalankan tanpa perlu menginstal Python atau pustaka tambahan apapun.

---

## 1. Setup Konfigurasi

Salin template `config.example.json` menjadi `config.json`:
- **Linux/macOS**: `cp config.example.json config.json`
- **Windows (PowerShell)**: `Copy-Item config.example.json config.json`

Sesuaikan isi `config.json`:
- `vps_endpoint`: URL endpoint VPS (misal `http://127.0.0.1:8088/api/logbook` atau domain HTTPS VPS Anda).
- `api_token`: Token autentikasi unik Anda (dapatkan via bot Telegram di menu `/token_logbook` atau `/daftar_logbook`).
- `openai_api_key`: API key OpenAI (opsional, jika kosong akan otomatis menggunakan format ringkasan non-AI).
- `repositories`: Pemetaan nama proyek ke path direktori git lokal di laptop. **Mendukung folder induk** (misal `"sai": "/home/oktavian/Project/sai"`), program akan otomatis memindai seluruh subfolder bersarang dan menamai proyek berdasarkan folder tingkat pertama di bawahnya.

---

## 2. Penggunaan CLI

### 🎮 Mode Menu Interaktif (TUI)
Cukup jalankan executable atau skrip **tanpa argumen apapun**, program akan otomatis membuka menu terminal interaktif modern dengan navigasi panah keyboard `[↑ / ↓]` dan `[Enter]`:
```bash
./logbook_cli          # Linux binary
.\logbook_cli.exe      # Windows binary (atau cukup klik dua kali pada file .exe)
python logbook_cli.py  # Skrip Python
```
Menu ini menyediakan opsi langsung untuk:
1. 🚀 **Jalankan & Kirim Logbook Hari Ini**
2. 👁️ **Preview Logbook Hari Ini (Tanpa Kirim)**
3. 🔍 **Scan Repositori Git Terdeteksi**
4. 🔄 **Kirim Ulang Draf Tertunda (Send Pending)**
5. 📅 **Jalankan untuk Tanggal Tertentu (Kustom)**
6. ❌ **Keluar**

---

### ⚡ Mode Perintah Langsung (CLI / Otomasi / Cron)
Jika ingin dijalankan otomatis oleh cron atau Task Scheduler, Anda bisa memberikan argumen sub-perintah langsung:
Melihat seluruh repositori Git yang terdeteksi beserta status commit hari ini:
```bash
# Binary Linux / Windows:
./logbook_cli scan        # Linux
.\logbook_cli.exe scan    # Windows

# Skrip Python:
python logbook_cli.py scan
```

### B. Preview (Tanpa kirim ke jaringan)
Melihat daftar commit dan draf ringkasan di terminal:
```bash
./logbook_cli preview --no-ai
```
Atau untuk tanggal tertentu:
```bash
./logbook_cli preview --date 2026-10-19
```

### C. Run (Kirim Draf ke VPS)
Membaca commit hari ini dan mengirim draf ke Telegram bot di VPS:
```bash
./logbook_cli run
```
Jika tidak ada commit pada hari tersebut, program akan keluar dengan status informatif tanpa mengirim request ke VPS. Jika VPS sedang offline, payload otomatis disimpan di `pending_queue.db`.

### D. Send Pending (Coba Ulang Kirim)
Mencoba mengirim ulang draf yang sebelumnya gagal terkirim karena masalah jaringan:
```bash
./logbook_cli send-pending
```


---

## 3. Penjadwalan Otomatis (Pukul 16.00 WIB)

### A. Linux (Cron)
Jalankan `crontab -e` dan tambahkan baris berikut untuk berjalan Senin–Jumat pukul 16:00:
```cron
0 16 * * 1-5 /usr/bin/python3 /path/to/tools/logbook_cli/logbook_cli.py run >> /tmp/logbook_cron.log 2>&1
```

### B. Linux (systemd User Timer)
Buat file `~/.config/systemd/user/git-logbook.service`:
```ini
[Unit]
Description=Git Logbook Daily Run

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /path/to/tools/logbook_cli/logbook_cli.py run
```
Buat file `~/.config/systemd/user/git-logbook.timer`:
```ini
[Unit]
Description=Run Git Logbook at 16:00 on weekdays

[Timer]
OnCalendar=Mon..Fri *-*-* 16:00:00
Persistent=true

[Install]
WantedBy=timers.target
```
Aktifkan timer:
```bash
systemctl --user daemon-reload
systemctl --user enable --now git-logbook.timer
```

### C. Windows (Task Scheduler)
1. Buka **Task Scheduler** (`taskschd.msc`).
2. Klik **Create Basic Task...**, beri nama `Git Logbook Daily`.
3. Trigger: **Weekly**, pilih **Monday through Friday**, pukul **16:00**.
4. Action: **Start a program**.
   - Program/script: `python` (atau path lengkap `C:\Python312\python.exe`)
   - Arguments: `tools\logbook_cli\logbook_cli.py run`
   - Start in: Folder project Anda
