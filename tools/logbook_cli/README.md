# 🚀 Git Logbook Automation CLI

Aplikasi mandiri (*standalone executable*) untuk mahasiswa magang / PKL: membaca commit Git lokal harian, menyusun ringkasan logbook otomatis, dan mengirimkannya ke bot VPS Telegram untuk pengisian otomatis ke portal **DERMAGA JTI Polinema**.

---

## 🧭 Cara Kerja Sistem

```
┌─────────────────────────────────┐
│  Laptop Mahasiswa               │
│  1. Koding & Git commit harian  │
│  2. Jalankan logbook_cli        │
└───────────────┬─────────────────┘
                │ (HTTP POST aman dengan API Token)
                ▼
┌─────────────────────────────────┐
│  Bot VPS Telegram               │
│  3. Terima draf aktivitas       │
│  4. Kirim notifikasi konfirmasi │
└───────────────┬─────────────────┘
                │
                ▼ (Mahasiswa klik [✅ Konfirmasi] di Telegram)
┌─────────────────────────────────┐
│  Portal DERMAGA Polinema        │
│  5. Bot otomatis mengisi form   │
│     logbook harian ke sistem    │
└─────────────────────────────────┘
```

---

## 📋 Panduan Step-by-Step Setup

### Langkah 1: Hubungkan Akun DERMAGA ke Bot Telegram

Sebelum menggunakan CLI di laptop, daftarkan akun DERMAGA Anda melalui bot Telegram untuk mendapatkan **API Token**:

1. Buka bot Telegram `bot-services`.
2. Kirim perintah pendaftaran dengan format:
   ```text
   /daftar_logbook <NIM_atau_Username> <Password_DERMAGA>
   ```
   *Contoh:*
   ```text
   /daftar_logbook 2341720117 Rahasia123
   ```
3. Bot akan menguji login langsung ke portal DERMAGA (`jti.polinema.ac.id/dermaga`).
4. Jika berhasil, bot akan membalas dengan **API Token Unik** Anda. Simpan token ini untuk Langkah 3.

> [!NOTE]  
> **🛡️ Jaminan Keamanan & Privasi Password:**
> - Pesan Telegram yang berisi password Anda akan **dihapus otomatis seketika** oleh bot dari riwayat chat demi privasi.
> - Kredensial Anda disimpan di server dengan enkripsi standar industri **Fernet (AES-128-CBC + HMAC)**.
> - File konfigurasi di laptop Anda **hanya** menyimpan API Token, sehingga password DERMAGA Anda tidak pernah tersimpan di laptop.

*(Tips: Jika Anda lupa API Token di kemudian hari, cukup kirim perintah `/token_logbook` atau cek menu `/logbook` di Telegram).*

---

### Langkah 2: Unduh Logbook CLI di Laptop

Tidak perlu menginstal Python atau dependensi apapun! Cukup unduh paket binary siap pakai dari GitHub Releases:

* 🪟 **Windows (x64)**: [logbook-cli-windows-x64.zip](https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-windows-x64.zip)
* 🐧 **Linux (x64)**: [logbook-cli-linux-x64.zip](https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-linux-x64.zip)

**Cara Ekstrak:**
* **Windows**: Klik kanan file ZIP ➡️ **Extract All...** ke folder pilihan Anda (misalnya `D:\LogbookCLI` atau `C:\Tools\LogbookCLI`).
* **Linux**: Ekstrak dengan perintah `unzip logbook-cli-linux-x64.zip -d ~/logbook-cli && chmod +x ~/logbook-cli/logbook_cli`.

---

### Langkah 3: Konfigurasi `config.json`

Di dalam folder hasil ekstrak, salin file template `config.example.json` menjadi `config.json`:
* **Windows**: Salin & ganti nama file `config.example.json` menjadi `config.json`.
* **Linux**: `cp config.example.json config.json`

Buka file `config.json` dengan text editor (Notepad, VSCode, dsb.), lalu sesuaikan isinya:

```json
{
  "vps_endpoint": "https://logbook.oktavian.dev/api/logbook",
  "api_token": "MASUKKAN_API_TOKEN_DARI_TELEGRAM_DI_SINI",
  "openai_api_key": "",
  "openai_base_url": "https://api.openai.com/v1",
  "openai_model": "gpt-4o-mini",
  "jam_masuk": "07:10",
  "jam_pulang": "16:25",
  "repositories": {
    "proyek-magang": "D:/Project/magang"
  }
}
```

#### 💡 Penjelasan Pengaturan:
* **`vps_endpoint`**: Biarkan tetap `https://logbook.oktavian.dev/api/logbook` (sudah siap pakai).
* **`api_token`**: Tempelkan token yang Anda dapatkan dari Langkah 1.
* **`openai_api_key`**: *(Opsional)* Jika dikosongkan, CLI otomatis menggunakan peringkas commit bawaan (non-AI) yang tetap rapi dan informatif.
* **`jam_masuk` & `jam_pulang`**: Jam kerja default yang akan otomatis diisikan ke form DERMAGA.
* **`repositories`**: Lokasi folder Git proyek lokal di laptop Anda:
  * **Mendukung folder induk (*Auto-Discovery*)**: Jika Anda punya banyak repositori di dalam satu folder (misal `D:/Project/sai`), cukup masukkan folder induknya. CLI akan otomatis memindai seluruh sub-repositori di dalamnya!
  * *Catatan Windows*: Gunakan garis miring biasa `/` (misal `"D:/Project/aplikasi"`), bukan backslash `\`.

---

### Langkah 4: Uji Coba & Rutinitas Harian (*Daily Workflow*)

#### 🎮 Cara Penggunaan Harian:
1. Selesaikan pekerjaan koding dan lakukan `git commit` seperti biasa di repo proyek Anda.
2. Buka folder CLI, lalu:
   * **Windows**: Klik dua kali file `logbook_cli.exe`.
   * **Linux**: Jalankan `./logbook_cli` di terminal.
3. Menu interaktif akan tampil di terminal:
   ```text
   ┌────────────────────────────────────────────────────────┐
   │            🚀 Git Logbook Automation CLI               │
   │  📅 Tanggal : 2026-10-28                               │
   │  🟢 Antrean : Bersih (tidak ada draf tertunda)         │
   └────────────────────────────────────────────────────────┘

   PILIHAN MENU:
     [1] 🚀 Kirim Logbook Hari Ini
     [2] 👁️  Preview Draf Hari Ini
     [3] 🔍 Scan Repositori Git
     [4] 🔄 Kirim Ulang Draf Tertunda
     [5] 📅 Logbook Tanggal Tertentu
     [0] ❌ Keluar
   ```
4. Tekan angka **`3`** terlebih dahulu untuk memverifikasi repositori Anda terdeteksi dan commit hari ini terbaca.
5. Tekan angka **`1`** untuk mengirim logbook hari ini.
6. **Buka aplikasi Telegram:**
   * Bot akan mengirimkan pesan berisi jam kerja, daftar commit, dan draf rangkuman aktivitas.
   * Periksa draf tersebut, lalu klik tombol **`[✅ Konfirmasi]`**.
   * Bot langsung login dan menginputkan logbook ke portal DERMAGA! Selesai! 🎉

> [!TIP]  
> **Tetap Aman Saat Offline / Gangguan Sinyal:**  
> Jika saat mengirim logbook laptop Anda sedang offline atau koneksi internet terputus, draf logbook tidak akan hilang! Draf otomatis disimpan di antrean lokal (`pending_queue.db`) dan dapat dikirim ulang kapan saja melalui menu **`[4] Kirim Ulang Draf Tertunda`**.

---

## ⏰ Otomasi Penuh: Menjalankan Otomatis dengan Penjadwal Tugas

Jika Anda tidak ingin repot membuka CLI setiap sore, Anda dapat menjadwalkan CLI agar berjalan otomatis setiap hari kerja (Senin–Jumat) pukul **16:30**:

### Opsi A: Windows (Task Scheduler)

#### Cara 1: Menggunakan Perintah PowerShell (Paling Cepat)
Buka **PowerShell as Administrator**, lalu jalankan perintah berikut (sesuaikan path folder ke lokasi `logbook_cli.exe` Anda):

```powershell
$action = New-ScheduledTaskAction -Execute "D:\LogbookCLI\logbook_cli.exe" -Argument "run" -WorkingDirectory "D:\LogbookCLI"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 4:30PM
Register-ScheduledTask -TaskName "GitLogbookAutomation" -Action $action -Trigger $trigger -Description "Kirim Draf Logbook DERMAGA Otomatis"
```

#### Cara 2: Melalui Tampilan GUI Windows
1. Tekan tombol `Win + R`, ketik `taskschd.msc`, lalu tekan **Enter**.
2. Di panel kanan, klik **Create Basic Task...**.
3. Beri nama: `Git Logbook Otomatis`, klik **Next**.
4. Pilih **Weekly**, centang hari **Monday s.d. Friday**, atur jam ke **16:30:00**, klik **Next**.
5. Pilih **Start a program**, klik **Next**:
   * **Program/script**: Pilih file `D:\LogbookCLI\logbook_cli.exe`.
   * **Add arguments**: Isi `run`
   * **Start in**: Isi folder tempat file exe berada, misal `D:\LogbookCLI\`.
6. Klik **Finish**. Setiap jam 16:30, logbook akan terkirim ke Telegram Anda dan Anda tinggal klik **Konfirmasi**.

---

### Opsi B: Linux (Cron / systemd Timer)

#### Menggunakan Cron
Jalankan perintah `crontab -e`, lalu tambahkan baris berikut di baris paling bawah:

```cron
30 16 * * 1-5 cd /home/username/logbook-cli && ./logbook_cli run >> /tmp/logbook_cron.log 2>&1
```

#### Menggunakan systemd User Timer
1. Buat service unit `~/.config/systemd/user/logbook-cli.service`:
   ```ini
   [Unit]
   Description=Git Logbook Automation Daily Run

   [Service]
   Type=oneshot
   WorkingDirectory=/home/username/logbook-cli
   ExecStart=/home/username/logbook-cli/logbook_cli run
   ```

2. Buat timer unit `~/.config/systemd/user/logbook-cli.timer`:
   ```ini
   [Unit]
   Description=Jalankan Logbook CLI Senin-Jumat pukul 16:30 WIB

   [Timer]
   OnCalendar=Mon..Fri *-*-* 16:30:00
   Persistent=true

   [Install]
   WantedBy=timers.target
   ```

3. Aktifkan timer:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now logbook-cli.timer
   ```

---

## 🛠️ Ringkasan Perintah CLI (Mode Argumen)

Selain mode menu interaktif, Anda juga bisa menjalankan fungsi tertentu langsung dari terminal/command prompt:

| Perintah | Deskripsi |
|---|---|
| `logbook_cli scan` | Pindai semua folder proyek Git lokal & cek status commit hari ini. |
| `logbook_cli preview` | Tampilkan draf ringkasan logbook hari ini di terminal (tanpa kirim ke Telegram). |
| `logbook_cli preview --date 2026-10-25` | Preview draf logbook untuk tanggal spesifik lampau. |
| `logbook_cli run` | Baca commit hari ini, buat ringkasan, dan langsung kirim draf ke Telegram. |
| `logbook_cli run --no-ai` | Kirim draf dengan format peringkas manual tanpa OpenAI API. |
| `logbook_cli send-pending` | Kirim ulang semua draf yang sebelumnya tertunda di antrean lokal. |
