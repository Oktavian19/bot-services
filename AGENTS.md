# AGENTS.md — bot-services

## Setup & run

```sh
pip install -r requirements.txt
# requires: TELEGRAM_TOKEN, MAGANG_SECRET_KEY, ADMIN_CHAT_ID
python main.py
```

## Architecture

- **Entrypoint**: `main.py` — monkey-patches urllib3 to IPv4-only, inits 5 modules, starts `bot.infinity_polling()`.
- **No `__init__.py`** anywhere — relies on Python 3.3+ implicit namespace packages (keep this pattern).
- **4 independent SQLite databases**: `modul/magang/users.db`, `modul/bensin/bensin.db`, `modul/reminder/reminders.db`, `modul/logbook/logbook.db` (all gitignored via `*.db`).
- **No tests, no linter, no formatter, no type checker** configured.

## Environment variables

| Variable | Needed by | Notes |
|---|---|---|
| `TELEGRAM_TOKEN` | `main.py` | Required, no fallback |
| `MAGANG_SECRET_KEY` | `modul/magang/database.py` | Fernet key; required if magang module is used |
| `ADMIN_CHAT_ID` | `modul/jaringan/main.py`, `modul/logbook/main.py` | Required for network alerts, speedtest guard, and logbook admin actions |
| `LOGBOOK_API_PORT` | `modul/logbook/server.py` | HTTP receiver port (default: 8088, bind to 127.0.0.1) |
| `LOGBOOK_PUBLIC_URL` | `modul/logbook/main.py` | Optional public HTTPS endpoint shown in Telegram CLI config (default: `http://127.0.0.1:8088/api/logbook`) |
| `LOGBOOK_SECRET_KEY` | `modul/logbook/database.py` | Fernet key for encrypting DERMAGA credentials; falls back to `MAGANG_SECRET_KEY` |
| `LOGBOOK_API_TOKEN` | `modul/logbook/server.py` | Optional fallback master token; users receive per-user API tokens on Telegram registration |

## Modules & registration

Each module exposes `init_*` called from `main.py`:

| Module | File | init function |
|---|---|---|
| magang | `modul/magang/main.py` | `init_magang(bot)` |
| jaringan | `modul/jaringan/main.py` | `init_jaringan(bot)` |
| reminder | `modul/reminder/main.py` | `init_reminder(bot)` |
| bensin | `modul/bensin/main.py` | `init_bensin(bot)` |
| logbook | `modul/logbook/main.py` | `init_logbook(bot)` |

## Callback naming convention

Prefix all callback_data with module code to prevent collisions:
- `cb_` — main menu
- `mgg_` — magang
- `bsn_` — bensin
- `rmd_` — reminder
- `log_` — logbook

## Quirks & gotchas

- **Main menu routes via `process_new_messages`** — inline callbacks in `main.py` set `call.message.text = "/cmd"` then call `bot.process_new_messages([call.message])` to trigger command handlers.
- **Date format is DD-MM-YYYY** throughout the reminder module.
- **`tools/migrasi_db.py`** script reads/writes `users.db` in its own directory (`tools/`), not `modul/magang/`. Move or symlink before running.
- **Logging uses `print()`** with bracketed prefixes (`[MAGANG]`, `[BENSIN]`, `[REMINDER]`, `[LOGBOOK]`, etc.) — no `logging` module in use.
- **Password handling**: magang & logbook modules encrypt credentials with Fernet before SQLite storage; Telegram messages with passwords are deleted upon receipt.
- **External deps**: requires `speedtest` CLI binary (Ookla) for `/speedtest` command; scrapes `jti.polinema.ac.id/jtiportal` for magang and `jti.polinema.ac.id/dermaga` for logbook monitoring & submission.

