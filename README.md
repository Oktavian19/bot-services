# bot-services

A multi-module Telegram bot that runs on a Debian server, built with modern Python async stack (**aiogram v3**, **pydantic-settings**, **loguru**, **aiosqlite**, and **APScheduler**). It provides network uptime alerts, reminders/agenda management, fuel consumption & oil tracking, automated multi-user DERMAGA logbook submission, and internship monitoring.

## Features

| Module | Description |
|---|---|
| **Logbook** (DERMAGA) | Automated multi-user daily logbook hub for Politeknik Negeri Malang DERMAGA portal. Receives Git activity summaries from local developer laptops via CLI, delivers interactive Telegram draft approvals, and submits verified entries with GPS coordinates. |
| **Jaringan** (Network) | Pings `1.1.1.1` continuously via non-blocking async socket. Detects downtime, measures duration, and sends alerts to admin via Telegram. Also provides `/speedtest` command (requires Ookla Speedtest CLI). |
| **Reminder** | Create, list, edit, and delete agenda reminders with preparation days countdown (H-x). Sends automated notifications when due using `Asia/Jakarta` timezone. |
| **Bensin** (Fuel) | Register motorcycle with initial & current odometer readings. Log fuel refills, accumulate partial refills without odometer, view/edit/delete history with automatic cascade recalculation, and track oil maintenance intervals (every 3,000 km). |
| **Magang** (Internship) | *(Archived / Disabled)* Monitors student internship status by scraping `jti.polinema.ac.id/jtiportal`. |


## Requirements

- Python 3.10+ (Tested up to Python 3.14)
- [Ookla Speedtest CLI](https://www.speedtest.net/apps/cli) (for `/speedtest` command)


## Setup

```sh
# 1. Clone the repository
git clone <repo-url>
cd bot-services

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Set environment variables
cp .env.example .env
# Edit .env and configure TELEGRAM_TOKEN, ADMIN_CHAT_ID, LOGBOOK_SECRET_KEY

# 4. Run the bot
python main.py
```


## Environment Variables

| Variable | Required | Used By | Description |
|---|---|---|---|
| `TELEGRAM_TOKEN` | Yes | `main.py` | Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `ADMIN_CHAT_ID` | Yes | `network`, `logbook`, `auth` | Telegram chat ID for downtime alerts, speedtest guard, and logbook admin actions |
| `LOGBOOK_API_PORT` | No (default: 8088) | `app/services/logbook_api.py` | HTTP receiver port bound for receiving logbook drafts from CLI |
| `LOGBOOK_PUBLIC_URL` | No | `app/bot/handlers/logbook.py` | Public HTTPS URL (e.g. `http://127.0.0.1:8088/api/logbook`) shown in Telegram setup snippets |
| `LOGBOOK_SECRET_KEY` | No (fallback) | `app/database/logbook_repo.py` | Fernet key for encrypting DERMAGA credentials; falls back to `MAGANG_SECRET_KEY` |
| `LOGBOOK_API_TOKEN` | No | `app/services/logbook_api.py` | Optional fallback master token for CLI |
| `MAGANG_SECRET_KEY` | If using magang | `app/database/magang_repo.py` | Fernet key for encrypting stored credentials in magang module |
| `LOG_LEVEL` | No (default: INFO) | `app/core/logger.py` | Log level for Loguru (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `TIMEZONE` | No (default: Asia/Jakarta) | `app/core/config.py` | Timezone for reminders and scheduler |


## Project Structure

```
bot-services/
├── app/
│   ├── bot/
│   │   ├── handlers/          # Modular aiogram routers (common, network, reminder, fuel, logbook, admin, magang_archived)
│   │   ├── middlewares/       # Auth admin, Loguru update logging, & throttling
│   │   └── keyboards/         # Inline keyboards modular
│   ├── core/
│   │   ├── config.py          # Settings model (pydantic-settings)
│   │   └── logger.py          # Setup Loguru sink & formatting
│   ├── services/              # Pure business logic (network, reminder, fuel, logbook scraping, API, scheduler)
│   └── database/              # Async database repositories (aiosqlite)
├── data/                      # SQLite databases (reminders.db, bensin.db, logbook.db, users.db)
├── tests/                     # Asynchronous unit test suites
├── scripts/                   # Database migration & integrity verification utilities
├── backups/                   # Safe physical backups of databases and legacy code
├── .env.example               # Clean environment variable template
├── requirements.txt           # Locked Python dependencies
├── Dockerfile                 # Multi-stage lightweight build (Python 3.12-slim + speedtest CLI)
├── AGENTS.md                  # Architecture & engineering notes
└── main.py                    # Entrypoint bot (Dispatcher, polling, graceful shutdown)
```


## Bot Commands

| Command | Module | Description |
|---|---|---|
| `/start` | Core | Show main menu with inline buttons |
| `/logbook` | Logbook | Interactive logbook control center with in-place action buttons |
| `/daftar_logbook <user> <pass>` | Logbook | Register or update DERMAGA credentials; verifies login & returns CLI API token |
| `/set_jam_logbook <HH:MM>` | Logbook | Set daily logbook reminder time (default: 16:05 WIB) |
| `/set_hari_logbook <pilihan>` | Logbook | Set active reminder days (e.g. `senin-jumat`, `setiap-hari`, `nonaktif`) |
| `/set_lokasi_logbook` | Logbook | Set GPS coordinates for internship location (office, home, other) |
| `/token_logbook` | Logbook | View your CLI API token or generate a new one |
| `/cek_logbook` | Logbook | View your recent logbook entries scraped directly from DERMAGA |
| `/hapus_akun_logbook` | Logbook | Delete your registered account & credentials from the bot |
| `/admin_logbook` | Logbook | *(Admin only)* List all registered users and their status |
| `/reminder` | Reminder | Manage reminders & agenda |
| `/bensin` | Bensin | Fuel consumption tracker & statistics |
| `/ping` | Core | Check Debian server connectivity |
| `/speedtest` | Jaringan | *(Admin only)* Run Ookla internet speed test |


## Local Logbook CLI

Aplikasi CLI pengembang untuk mengumpulkan aktivitas Git dan mengirimkan logbook harian dikelola di repositori mandiri:
👉 **[Oktavian19/logbook-cli](https://github.com/Oktavian19/logbook-cli)**

1. **Register with the bot**: Kirim `/daftar_logbook <username> <password>` ke bot di Telegram untuk mendapatkan `api_token` pribadi Anda.
2. **Setup CLI**: Kloning atau unduh binary standalone dari repositori [logbook-cli](https://github.com/Oktavian19/logbook-cli), lalu sesuaikan file `config.json`.
3. **Usage**:
   - `python logbook_cli.py scan`: Pindai repositori terkonfigurasi.
   - `python logbook_cli.py preview`: Lihat draf logbook dan ringkasan AI sebelum dikirim.
   - `python logbook_cli.py run`: Kumpulkan commit, buat ringkasan, dan kirim draf ke API bot.
   - `python logbook_cli.py send-pending`: Kirim ulang logbook tertunda jika sempat offline.


## Architecture Notes

- **No `__init__.py`** — relies on Python 3.3+ implicit namespace packages.
- **Dedicated Data Directory** — databases stored in `data/` (`reminders.db`, `bensin.db`, `logbook.db`, `users.db`) with WAL mode.
- **Logging** uses `loguru` with colored console output and rotating file sink (`logs/bot.log`).
- **Date format** is `DD-MM-YYYY` throughout the reminder module and `YYYY-MM-DD` in the logbook module.
- **Callback prefixes** — `cb_` (main menu), `log_` (logbook), `rmd_` (reminder), `bsn_` (bensin), `mgg_` (magang).
- **Security & Privacy** — sensitive credentials (passwords) are encrypted using Fernet cryptography before being saved to SQLite; Telegram messages containing passwords are deleted immediately upon receipt.
- **Graceful Shutdown** — cleanly handles `SIGINT` and `SIGTERM` signals, terminating polling, background scheduler, and HTTP receiver without hanging tasks.
