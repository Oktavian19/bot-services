# bot-services

A multi-module Telegram bot that runs on a Debian server, providing network uptime alerts, reminders/agenda management, fuel consumption tracking, automated multi-user DERMAGA logbook submission, and internship monitoring.

## Features

| Module | Description |
|---|---|
| **Logbook** (DERMAGA) | Automated multi-user daily logbook hub for Politeknik Negeri Malang DERMAGA portal. Receives Git activity summaries from local developer laptops via CLI/timer, delivers interactive Telegram draft approvals, and submits verified entries with coordinates. |
| **Jaringan** (Network) | Pings `1.1.1.1` continuously. Detects downtime, measures duration, sends alerts to admin via Telegram. Also provides `/speedtest` command (requires Ookla Speedtest CLI). |
| **Reminder** | Create, list, and delete reminders with date/time. Sends notifications when reminders are due. Uses `Asia/Jakarta` timezone. |
| **Bensin** (Fuel) | Register a motorcycle with initial & current odometer readings. Log fuel refills, view/edit/delete history, and get statistics (km/L). |
| **Magang** (Internship) | *(Archived / Disabled)* Monitors student internship status by scraping `jti.polinema.ac.id/jtiportal`. See [`modul/magang/README.md`](modul/magang/README.md) to reactivate. |

## Logbook CLI (Client Downloads)

Bagi pengguna / rekan mahasiswa yang ingin menjalankan pemindai commit Git otomatis di laptop tanpa perlu mengklon seluruh repositori bot atau menginstal Python:

[![Release](https://img.shields.io/badge/Release-cli--latest-brightgreen)](https://github.com/Oktavian19/bot-services/releases/tag/cli-latest)

| Platform | Format | Link Unduhan |
|---|---|---|
| **Windows (x64)** | ZIP (`logbook_cli.exe` standalone) | [logbook-cli-windows-x64.zip](https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-windows-x64.zip) |
| **Linux (x64)** | ZIP (`logbook_cli` binary standalone) | [logbook-cli-linux-x64.zip](https://github.com/Oktavian19/bot-services/releases/download/cli-latest/logbook-cli-linux-x64.zip) |

> 📖 Dokumentasi konfigurasi dan penjadwalan otomatis (Task Scheduler / systemd timer) tersedia lengkap di [`tools/logbook_cli/README.md`](tools/logbook_cli/README.md).

## Requirements

- Python 3.8+
- [Ookla Speedtest CLI](https://www.speedtest.net/apps/cli) (for `/speedtest` command)

## Setup

```sh
# 1. Clone the repository
git clone <repo-url>
cd bot-services

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Set environment variables
export TELEGRAM_TOKEN="your_bot_token"
export ADMIN_CHAT_ID="your_chat_id"          # required for network alerts, speedtest & logbook admin
export MAGANG_SECRET_KEY="your_fernet_key"   # required if using magang module (used as fallback by logbook)
export LOGBOOK_SECRET_KEY="your_fernet_key"  # optional, defaults to MAGANG_SECRET_KEY
export LOGBOOK_API_PORT="8088"               # optional, HTTP receiver port (default: 8088)

# 4. Run the bot
python main.py
```

## Environment Variables

| Variable | Required | Used By | Description |
|---|---|---|---|
| `TELEGRAM_TOKEN` | Yes | `main.py` | Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `ADMIN_CHAT_ID` | Yes | `modul/jaringan/main.py`, `modul/logbook/main.py` | Telegram chat ID for downtime alerts, speedtest guard, and logbook admin actions |
| `LOGBOOK_API_PORT` | No (default: 8088) | `modul/logbook/server.py` | HTTP receiver port bound to `127.0.0.1` for receiving logbook drafts |
| `LOGBOOK_SECRET_KEY` | No (fallback) | `modul/logbook/database.py` | Fernet key for encrypting DERMAGA credentials; falls back to `MAGANG_SECRET_KEY` |
| `LOGBOOK_API_TOKEN` | No | `modul/logbook/server.py` | Optional fallback master token (users normally use individual tokens generated via Telegram) |
| `MAGANG_SECRET_KEY` | If using magang | `modul/magang/database.py` | Fernet key for encrypting stored credentials in magang module |

## Project Structure

```
bot-services/
├── main.py                  # Entry point — monkey-patches IPv4, inits modules, starts polling & background threads
├── requirements.txt
├── AGENTS.md                # Notes for AI coding assistants
├── README.md
├── .gitignore
├── modul/
│   ├── logbook/             # Multi-user DERMAGA logbook module
│   │   ├── main.py          #   Interactive Telegram commands, callbacks & in-place menu navigation
│   │   ├── database.py      #   Multi-user SQLite schema, credentials encryption & token management
│   │   ├── server.py        #   HTTP API receiver with Bearer token authentication
│   │   └── website.py       #   Web scraping & submission with coordinates and live verification
│   ├── jaringan/            # Network uptime monitoring
│   │   ├── main.py          #   Ping loop, speedtest command
│   │   └── database.py
│   ├── reminder/            # Reminders & agenda
│   │   ├── main.py          #   CRUD reminders, scheduler thread
│   │   └── database.py      #   SQLite with due/notification tracking
│   ├── bensin/              # Fuel consumption tracker
│   │   ├── main.py          #   Register motor, log refills, stats
│   │   └── database.py      #   SQLite
│   └── magang/              # Internship monitoring (Archived)
│       ├── main.py          #   Scrapes portal, periodic checking thread
│       ├── database.py      #   SQLite + Fernet encryption
│       └── README.md        #   Reactivation & module documentation
└── tools/
    ├── logbook_cli/         # Developer CLI & automated Git activity scanner
    │   ├── logbook_cli.py   #   Commit scanner, AI summary generator, and SSH tunnel pusher
    │   ├── config.json      #   Local developer configuration (endpoint, repos, token)
    │   └── config.example.json
    ├── test_logbook.py      # Comprehensive test suite for logbook module and CLI (14 unit tests)
    └── migrasi_db.py        # Migrates plaintext passwords to encrypted (legacy magang)
```

## Bot Commands

| Command | Module | Description |
|---|---|---|
| `/start` | Core | Show main menu with inline buttons |
| `/logbook` | Logbook | Interactive logbook control center with in-place action buttons |
| `/daftar_logbook <user> <pass>` | Logbook | Register or update DERMAGA credentials; verifies login & returns CLI API token |
| `/token_logbook` | Logbook | View your CLI API token or generate a new one |
| `/cek_logbook` | Logbook | View your recent logbook entries scraped directly from DERMAGA |
| `/hapus_akun_logbook` | Logbook | Delete your registered account & credentials from the bot |
| `/admin_logbook` | Logbook | *(Admin only)* List all registered users and their status |
| `/reminder` | Reminder | Manage reminders & agenda |
| `/bensin` | Bensin | Fuel consumption tracker & statistics |
| `/ping` | Core | Check Debian server connectivity |
| `/speedtest` | Jaringan | *(Admin only)* Run Ookla internet speed test |

## Local Logbook CLI (`tools/logbook_cli/`)

Developers working across multiple repositories can automatically generate and submit daily logbooks:

1. **Register with the bot**: Send `/daftar_logbook <username> <password>` to the bot in Telegram to receive your unique `api_token`.
2. **Configure CLI**: Create or update `tools/logbook_cli/config.json`:
   ```json
   {
     "vps_endpoint": "http://127.0.0.1:8088/api/logbook",
     "api_token": "YOUR_PERSONAL_TOKEN_FROM_TELEGRAM",
     "openai_api_key": "optional-key-if-using-ai",
     "openai_base_url": "optional-url",
     "openai_model": "optional-model",
     "jam_masuk": "07:10",
     "jam_pulang": "16:25",
     "repositories": {
       "my-project": "/path/to/my-project/"
     }
   }
   ```
3. **Usage**:
   - `python tools/logbook_cli/logbook_cli.py scan`: Scan configured repositories and discover nested Git directories.
   - `python tools/logbook_cli/logbook_cli.py preview`: Preview today's commits and generated summary without sending.
   - `python tools/logbook_cli/logbook_cli.py run`: Collect commits, generate summary, open SSH tunnel if needed, and push draft to the VPS.
   - `python tools/logbook_cli/logbook_cli.py send-pending`: Retry sending payloads saved locally during network downtime.

## Architecture Notes

- **No `__init__.py`** — relies on Python 3.3+ implicit namespace packages.
- **4 independent SQLite databases** — `modul/logbook/logbook.db`, `modul/reminder/reminders.db`, `modul/bensin/bensin.db`, and `modul/magang/users.db` (all gitignored via `*.db`).
- **Logging** uses `print()` with bracketed prefixes (`[LOGBOOK]`, `[LOGBOOK-API]`, `[REMINDER]`, `[BENSIN]`, etc.).
- **Date format** is `DD-MM-YYYY` throughout the reminder module and `YYYY-MM-DD` in the logbook module.
- **Main menu routing** — inline callbacks set `call.message.text` then call `bot.process_new_messages()` to trigger command handlers.
- **Callback prefixes** — `cb_` (main menu), `log_` (logbook), `rmd_` (reminder), `bsn_` (bensin), `mgg_` (magang).
- **Security & Privacy** — sensitive credentials (passwords) are encrypted using Fernet cryptography before being saved to SQLite; Telegram messages containing passwords are deleted immediately upon receipt.
