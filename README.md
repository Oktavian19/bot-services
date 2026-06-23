# bot-services

A multi-module Telegram bot that runs on a Debian server, providing internship monitoring, network uptime alerts, reminders/agenda management, and fuel consumption tracking.

## Features

| Module | Description |
|---|---|
| **Magang** (Internship) | Monitors student internship status by scraping `jti.polinema.ac.id/jtiportal`. Stores encrypted credentials, runs periodic checks, and notifies on status changes. |
| **Jaringan** (Network) | Pings `1.1.1.1` continuously. Detects downtime, measures duration, sends alerts to admin via Telegram. Also provides `/speedtest` command (requires Ookla Speedtest CLI). |
| **Reminder** | Create, list, and delete reminders with date/time. Sends notifications when reminders are due. Uses `Asia/Jakarta` timezone. |
| **Bensin** (Fuel) | Register a motorcycle with initial & current odometer readings. Log fuel refills and get statistics (km/L). |

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
export MAGANG_SECRET_KEY="your_fernet_key"   # required only if using magang module
export ADMIN_CHAT_ID="your_chat_id"          # required for network alerts + speedtest

# 4. Run the bot
python main.py
```

## Environment Variables

| Variable | Required | Used By | Description |
|---|---|---|---|
| `TELEGRAM_TOKEN` | Yes | `main.py` | Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `MAGANG_SECRET_KEY` | If using magang | `modul/magang/database.py` | Fernet key for encrypting stored passwords |
| `ADMIN_CHAT_ID` | If using jaringan | `modul/jaringan/main.py` | Telegram chat ID for downtime alerts & speedtest guard |

## Project Structure

```
bot-services/
├── main.py                  # Entry point — monkey-patches IPv4, inits modules, starts polling
├── requirements.txt
├── AGENTS.md                # Notes for AI coding assistants
├── .gitignore
├── modul/
│   ├── magang/              # Internship monitoring
│   │   ├── main.py          #   Scrapes portal, periodic checking thread
│   │   └── database.py      #   SQLite + Fernet encryption
│   ├── jaringan/            # Network uptime monitoring
│   │   ├── main.py          #   Ping loop, speedtest command
│   │   └── database.py
│   ├── reminder/            # Reminders & agenda
│   │   ├── main.py          #   CRUD reminders, scheduler thread
│   │   └── database.py      #   SQLite with due/notification tracking
│   └── bensin/              # Fuel consumption tracker
│       ├── main.py          #   Register motor, log refills, stats
│       └── database.py      #   SQLite
└── tools/
    └── migrasi_db.py        # Migrates plaintext passwords to encrypted (legacy)
```

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Show main menu with inline buttons |
| `/magang` | Internship monitoring hub |
| `/reminder` | Manage reminders & agenda |
| `/bensin` | Fuel consumption tracker |
| `/ping` | Check server connectivity |

## Architecture Notes

- **No `__init__.py`** — uses Python 3.3+ implicit namespace packages.
- **3 independent SQLite databases** — one per module (all gitignored via `*.db`).
- **Logging** uses `print()` with bracketed prefixes (`[MAGANG]`, `[BENSIN]`, etc.).
- **Date format** is `DD-MM-YYYY` throughout the reminder module.
- **Main menu routing** — inline callbacks set `call.message.text` then call `bot.process_new_messages()` to trigger command handlers.
- **Callback prefixes** — `cb_` (main menu), `mgg_` (magang), `bsn_` (bensin), `rmd_` (reminder).

## Database Migration (Legacy)

If you have an existing `users.db` with plaintext passwords, run:

```sh
cp modul/magang/users.db tools/
python tools/migrasi_db.py
# Copy the generated Fernet key into your MAGANG_SECRET_KEY env var
```
