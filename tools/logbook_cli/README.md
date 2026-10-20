# Git Logbook Automation CLI

Script mandiri berbasis Python standard library untuk membaca commit Git lokal, membuat ringkasan logbook naratif (OpenAI / non-AI), dan mengirimkannya ke bot VPS `bot-services` via HTTP POST idempoten.

---

## 1. Setup Konfigurasi

Salin template `config.example.json` menjadi `config.json`:
```bash
cp tools/logbook_cli/config.example.json tools/logbook_cli/config.json
```
Sesuaikan isi `config.json`:
- `vps_endpoint`: URL endpoint VPS (misal `http://127.0.0.1:8088/api/logbook` atau domain HTTPS VPS Anda).
- `api_token`: Token autentikasi yang sama dengan `LOGBOOK_API_TOKEN` di environment VPS.
- `openai_api_key`: API key OpenAI (opsional, jika kosong akan otomatis menggunakan format ringkasan non-AI).
- `repositories`: Pemetaan nama proyek ke path direktori git lokal di laptop.

---

## 2. Penggunaan CLI

### A. Preview (Tanpa kirim ke jaringan)
Melihat daftar commit dan draf ringkasan di terminal:
```bash
python tools/logbook_cli/logbook_cli.py preview --no-ai
```
Atau untuk tanggal tertentu:
```bash
python tools/logbook_cli/logbook_cli.py preview --date 2026-10-19
```

### B. Run (Kirim Draf ke VPS)
Membaca commit hari ini dan mengirim draf ke Telegram bot di VPS:
```bash
python tools/logbook_cli/logbook_cli.py run
```
Jika tidak ada commit pada hari tersebut, script akan keluar dengan status informatif tanpa mengirim request ke VPS. Jika VPS sedang offline, payload otomatis disimpan di `pending_queue.db`.

### C. Send Pending (Coba Ulang Kirim)
Mencoba mengirim ulang draf yang sebelumnya gagal terkirim karena masalah jaringan:
```bash
python tools/logbook_cli/logbook_cli.py send-pending
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
