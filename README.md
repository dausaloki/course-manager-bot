# 📚 Course Manager Bot — All-in-One Telegram Course Management & Authorized Export System

## 1. Project overview

**ONE** Telegram bot that logs into your source application **through its
official/authorized API only**, lets you browse *Batch → Subject → Topic →
Lecture → Files*, select authorized videos/PDFs, and upload them to your
configured Telegram channel/group with unique sequential indexing, duplicate
detection, a persistent restart-safe queue, history, search, statistics and
admin settings.

> ⚖️ **Legal & ethical scope**
> This system is intended **only** for content you own or are explicitly
> authorized to export. It **never** bypasses DRM, encryption,
> authentication, subscriptions, certificate pinning or any access control.
> If the source application has no official API, the adapter **stops** and
> tells you exactly what documentation is required — it never guesses
> endpoints.

## 2. Architecture

```
Application / Official API
        ↓
Authorized Login (password used once, never stored)
        ↓
Authorized Batches → Subject → Topic/Chapter → Lecture → Video/PDF/Files
        ↓
File Selection (single / multi / lecture / topic / batch)
        ↓
Duplicate Detection → Upload Queue (persistent, restart-safe)
        ↓
Telegram Bot (rate-limited uploader, exponential-backoff retries)
        ↓
Configured Telegram Channel / Group
        ↓
Database (SQLite → PostgreSQL-ready) + Upload History + Unique Index
```

## 3. Features

- 🤖 **One bot, one token** — every feature integrated in a single bot
- 🔐 Login via official API; only the opaque session token is stored
- 📚 Batch/Subject/Topic/Lecture/File navigation with inline keyboards,
  pagination, ⬅️ Back / 🏠 Home / ❌ Cancel everywhere
- ☑️ Select one, many, all-in-lecture, all-in-topic, all-in-batch + confirmation screen
- 📤 Persistent upload queue: Start / Pause / Resume / Cancel / Retry Failed;
  survives crashes and restarts (interrupted items auto-recover)
- 🔢 Unique sequential index (transaction + lock protected, restart-safe)
- 📝 Admin-configurable caption template — original titles never modified:
  `{index} {title} {topic} {subject} {batch} {lecture} {file_type} {date}`
- ⚠️ Duplicate detection with **Skip / Upload Again** + Telegram `file_id`
  reuse (identical files are never re-uploaded unnecessarily)
- 🔁 Exponential-backoff retries for temporary errors only
- 🔍 Search by index, title, batch, subject, topic, lecture, type, message id
- 📜 History with All/Completed/Failed/Pending filters · 📊 Statistics
- 🛡️ Admin-only access, secret-redacting logs, parameterized queries
- 🧪 **TEST_MODE** — fully simulated source API and simulated uploads

## 4. Folder structure

```
course_manager_bot/
├── main.py                  # entry point
├── config.py                # env config + validation
├── requirements.txt
├── .env.example
├── Procfile                 # Railway/Heroku-style start
├── railway.json             # Railway build & deploy config
├── README.md
├── app_api/
│   ├── provider.py          # CourseProvider interface + errors
│   ├── official_provider.py # OfficialAppProvider (configure with real docs)
│   ├── auth.py              # session token persistence (no passwords)
│   ├── courses.py           # TestModeProvider (simulator)
│   └── models.py            # DTOs
├── telegram_bot/
│   ├── bot.py               # application factory + worker lifecycle
│   ├── keyboards.py         # inline keyboards + pagination
│   ├── handlers.py          # all handlers (menu/login/nav/queue/…)
│   ├── uploader.py          # background upload worker
│   └── formatter.py         # caption templates
├── database/
│   ├── db.py                # engine, sessions, settings, index allocator
│   ├── models.py            # 11 tables + index_counter
│   └── migrations.py        # init + crash recovery
├── services/
│   ├── course_service.py    # provider registry + DB mirror
│   ├── upload_service.py    # duplicate detection + upload records
│   ├── queue_service.py     # persistent queue state machine
│   ├── search_service.py    # search + history
│   └── statistics_service.py
├── utils/
│   ├── security.py          # admin_only guard
│   ├── logger.py            # secret-redacting logging + DB audit
│   ├── validators.py
│   └── helpers.py
└── tests/                   # 45 automated tests (pytest)
```

## 5. Requirements

- Python **3.11+**
- Packages (see `requirements.txt`): python-telegram-bot 21.6,
  SQLAlchemy 2.0, python-dotenv, httpx, pytest

## 6. Local installation

```bash
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux / Android Termux:
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env          # then edit .env
```

## 7. Environment variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | ✅ | Destination channel/group id (`-100…`) or `@username` |
| `ADMIN_USER_ID` | ✅ | Your numeric Telegram user id (only this user can use the bot) |
| `APP_API_BASE_URL` | when `TEST_MODE=false` | Base URL of the **official** authorized API |
| `APP_CLIENT_ID` | optional | API client id issued by the vendor |
| `APP_CLIENT_SECRET` | optional | API client secret issued by the vendor |
| `DATABASE_URL` | default `sqlite:///course_manager.db` | SQLAlchemy URL; PostgreSQL supported |
| `TEST_MODE` | default `true` | `true` = simulated source API + simulated uploads |
| `LOG_LEVEL` | default `INFO` | DEBUG / INFO / WARNING / ERROR |
| `INDEX_START` | default `1` | First upload index number |

Never commit `.env`. Secrets are read only from the environment and are
redacted from every log line.

## 8. BotFather setup

1. Open **@BotFather** → `/newbot` → pick name + username → copy token → `.env`.
2. *(Optional)* `/setcommands`:
   ```
   start - Open the main menu
   id - Show your Telegram user id
   cancel - Cancel current operation
   ```

## 9. Telegram channel/group setup

1. Add the bot to your destination channel/group.
2. Promote it to **Administrator** with **Post messages** (channel) /
   **Send media** (group).
3. Get the chat id: forward a post to @userinfobot → the `-100…` id → `.env`.
4. On startup (non-test mode) the bot verifies it can post and logs a clear
   error if not. The destination can also be changed later in ⚙️ Settings
   (validated live before saving).

## 10. Database setup

Nothing to do for SQLite — the schema is created automatically on first run
(or manually: `python -c "from database.migrations import init_db; init_db()"`).

**PostgreSQL** (recommended for Railway) — the `psycopg` v3 driver ships in
`requirements.txt`, and `postgres://` / `postgresql://` URLs are normalized
automatically to `postgresql+psycopg://`:

```
DATABASE_URL=postgresql://user:pass@host:5432/coursebot   # works as-is
```

An empty `DATABASE_URL` safely falls back to SQLite instead of crashing.
Portable column types, proper foreign keys, and the index allocator uses
`SELECT … FOR UPDATE` where the engine supports it.

## 11. TEST_MODE

Keep `TEST_MODE=true` first. Then `/start` the bot and exercise everything:

- 🔐 Login — any username/password (password `wrong` simulates failure)
- 📚 3 sample batches → subjects → topics → lectures → 🎥/📄 files
- Selection, confirmation, queue, **simulated** uploads (no real file leaves
  the machine), real indexing, duplicate detection, history, search, stats

## 12. Official API configuration

Open `app_api/official_provider.py`. All HTTP/auth/retry plumbing is done;
fill in **only** configuration from the vendor's official documentation:

| Config point | What you need |
|---|---|
| `.env APP_API_BASE_URL` | Base URL of the authorized API |
| `ENDPOINTS["login"]` | Login path + method + body fields |
| `AUTH_STYLE` | bearer / header / cookie token transport |
| `ENDPOINTS["batches"…"download_url"]` | Resource path templates |
| `FIELD_MAP` | JSON field names (id/name/title/url/size/type/date) |

Until configured the bot **starts normally** and shows a clear
"Official API not configured" message whenever the source API is requested —
it never guesses endpoints and never bypasses access controls.

## 13. Running locally

```bash
python main.py
```

Then message your bot: `/start`.

## 14. Running on Railway

1. Push the project to a GitHub repo (never include `.env`).
2. Railway → **New Project → Deploy from GitHub repo**.
3. Build/start are auto-detected from `railway.json` / `Procfile`:
   - Build: `pip install -r requirements.txt`
   - Start: `python main.py`
4. *(Recommended)* Add the **PostgreSQL database** to the project, then on
   the bot service set `DATABASE_URL` to the reference
   `${{Postgres.DATABASE_URL}}` (the app normalizes the URL scheme and the
   psycopg driver is already in `requirements.txt`).
5. **Variables** tab → add: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
   `ADMIN_USER_ID`, `TEST_MODE`, `DATABASE_URL` (+ `APP_API_BASE_URL`,
   `APP_CLIENT_ID`, `APP_CLIENT_SECRET` for real mode).
6. Database initialization/migration runs automatically at startup
   (`init_db()` in `main.py`) — no extra command needed.
7. This is a **worker** service (long polling, no HTTP port). If Railway
   asks about health checks / public networking, disable them.
8. **Logs**: project → service → *Deployments* → *View logs* (secrets are
   redacted by the app).
9. **Restart**: service → ⋮ → *Restart* (or redeploy). The persistent queue
   resumes automatically; interrupted items return to PENDING.

⚠️ SQLite on Railway is ephemeral (wiped on redeploy) — use the PostgreSQL
plugin for anything you want to keep.

## 15. Troubleshooting

| Problem | Fix |
|---|---|
| `Configuration problems found` at start | Fill `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ADMIN_USER_ID` in `.env` / Railway variables. |
| Bot ignores `/start` | You are not `ADMIN_USER_ID`. Send `/id`, put the number in config, restart. |
| `Cannot access destination chat` | Add the bot as admin with post/media permission; check the `-100…` id. |
| Uploads stay PENDING | Queue paused? 📤 Upload Queue → ▶️ Start. Check logs. |
| `Official API not configured` | Expected until `ENDPOINTS`/`FIELD_MAP` are filled from official docs, or keep `TEST_MODE=true`. |
| `Session expired` | 🔐 Login again — tokens expire per vendor policy. |
| Duplicate warning | Choose ⏭ Skip or 🔄 Upload Again — nothing is duplicated silently. |
| Large video fails | Standard Bot API caps uploads ~50 MB; run a [local Bot API server](https://core.telegram.org/bots/api#using-a-local-bot-api-server) (2 GB) or split content. |
| `database is locked` | Run only one instance per SQLite file; or switch to PostgreSQL. |
| Conversation stuck | `/cancel`, then `/start`. |

## 16. Security notes

- No secrets in code — environment variables only; `.env` is git-ignored by you.
- Passwords: used once for the official login call, deleted from the chat,
  never stored, never logged. Only the opaque session token is persisted.
- Log redaction filter strips bot token / client secret from every log line.
- Single-admin authorization on every handler; unauthorized attempts audited.
- All SQL is parameterized through the SQLAlchemy ORM.
- Input validation on every free-text field (login, search, settings).

## 17. Limitations

- Standard Telegram Bot API upload limit ≈ 50 MB/file (2 GB with a local
  Bot API server).
- Real source integration requires the vendor's **official API
  documentation** — by design, nothing is guessed and no protection is
  bypassed.
- Single-admin model (one `ADMIN_USER_ID`); multi-admin would need a small
  extension of `utils/security.py`.
- Upload pacing is deliberately conservative (≥3 s between sends) to respect
  Telegram rate limits.
