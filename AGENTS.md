# AGENTS.md — bot-services

## Setup & run

```sh
pip install -r requirements.txt
# requires: TELEGRAM_TOKEN, MAGANG_SECRET_KEY / LOGBOOK_SECRET_KEY, ADMIN_CHAT_ID (di .env atau .env.bot)
python main.py
```

## Architecture (Modern aiogram v3 Async)

- **Framework**: `aiogram v3` (asyncio native) dengan `MemoryStorage` untuk FSM context.
- **Konfigurasi**: `pydantic-settings` (`app/core/config.py`) membaca `.env` dan `.env.bot`.
- **Logging**: `loguru` (`app/core/logger.py`) dengan sink konsol berwarna dan file rotasi (`logs/bot.log`). Interseptor standard logging aktif untuk library external (`aiogram`, `aiohttp`, `apscheduler`).
- **Database**: `aiosqlite` (`app/database/`) mengelola koneksi non-blocking ke database SQLite eksisting (`reminders.db`, `bensin.db`, `logbook.db`, `users.db`) dengan WAL mode & timeout 5000ms.
- **HTTP Receiver API**: `aiohttp.web` (`app/services/logbook_api.py`) terintegrasi langsung dalam event loop asyncio di port 8088.
- **Task Scheduling**: `APScheduler` (AsyncIOScheduler) untuk reminder agenda dan logbook, serta `asyncio.create_task` untuk network monitor.
- **No `__init__.py`** anywhere — relies on Python 3.3+ implicit namespace packages (keep this pattern).
- **Graceful Shutdown**: Menangkap sinyal `SIGINT` dan `SIGTERM` untuk menghentikan polling, scheduler, HTTP server, dan bot session secara bersih.

## Layout Struktur Direktori

```
bot-services/
├── app/
│   ├── bot/
│   │   ├── handlers/          # Router aiogram modular (common, network, reminder, fuel, logbook, admin, magang_archived)
│   │   ├── middlewares/       # Middleware auth admin, logging update, dan throttling
│   │   └── keyboards/         # Inline keyboards modular
│   ├── core/
│   │   ├── config.py          # Settings model (pydantic-settings)
│   │   └── logger.py          # Setup Loguru sink & formatting
│   ├── services/              # Pure business logic (network, reminder, fuel, logbook scraping, API, scheduler)
│   └── database/              # Engine async & repository per domain (aiosqlite)
├── tests/                     # Unit test asinkron untuk repositories dan API
├── .env.example               # Template environment variable yang bersih
├── requirements.txt           # Dependensi baru terkunci
├── Dockerfile                 # Multi-stage lightweight build (Python 3.12-slim + ookla speedtest CLI)
└── main.py                    # Entrypoint bot (Dispatcher, lifespans, graceful shutdown)
```

## Callback naming convention

Prefix all callback_data with module code to prevent collisions:
- `cb_` — main menu
- `mgg_` — magang
- `bsn_` — bensin
- `rmd_` — reminder
- `log_` — logbook

## Environment variables

| Variable | Needed by | Notes |
|---|---|---|
| `TELEGRAM_TOKEN` | `main.py` | Required, bot API token dari @BotFather |
| `ADMIN_CHAT_ID` | `network`, `logbook`, `auth` | Chat ID Telegram admin untuk speedtest, notifikasi downtime, dan admin panel |
| `LOGBOOK_SECRET_KEY` | `app/database/logbook_repo.py` | Fernet key untuk enkripsi kredensial DERMAGA; fallback ke `MAGANG_SECRET_KEY` |
| `MAGANG_SECRET_KEY` | `app/database/magang_repo.py` | Fernet key untuk modul magang |
| `LOGBOOK_API_PORT` | `app/services/logbook_api.py` | Port HTTP receiver (default: 8088) |
| `LOGBOOK_PUBLIC_URL` | `app/bot/handlers/logbook.py` | Endpoint publik yang disajikan ke CLI (default: `http://127.0.0.1:8088/api/logbook`) |
| `LOGBOOK_API_TOKEN` | `app/services/logbook_api.py` | Master fallback token untuk CLI |
| `LOG_LEVEL` | `app/core/logger.py` | Log level (INFO, DEBUG, WARNING, ERROR) |
| `TIMEZONE` | `app/core/config.py` | Default `Asia/Jakarta` (WIB) |
