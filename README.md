# mp3

Download audio from YouTube (and anything else `yt-dlp` supports) as mp3, either through a web UI or a Telegram bot. Runs entirely in Docker Compose. All requests are logged, and a small CLI summarizes the activity.

---

## Architecture

```
+-----------+      +----------------+
|  Browser  |----->|  web (Flask)   |--+
+-----------+      +----------------+  |
                                       |  shared
+-----------+      +----------------+  |  downloader.py
| Telegram  |<---->|  bot (PTB)     |--+  + history.log
+-----------+      +----------------+
```

- **`web`** — Flask + Gunicorn, serves the UI at `http://localhost:5050`.
- **`bot`** — `python-telegram-bot`, polls Telegram for messages and replies with the mp3.
- **`downloader.py`** — shared yt-dlp + ffmpeg wrapper used by both services.
- **`logs/history.log`** — append-only event log shared by both services (mounted as a volume).

---

## Prerequisites

- Docker Desktop (Compose v2)
- For the Telegram bot: a bot token from [@BotFather](https://t.me/BotFather)

---

## Setup

```bash
# 1. Provide a Telegram token (skip this if you only want the web app).
cp .env.example .env
# Open .env and paste your token after TELEGRAM_BOT_TOKEN=

# 2. Build and start everything.
docker compose up -d --build
```

If you skip `.env`, the `web` service still works; the `bot` container will restart-loop with the message `TELEGRAM_BOT_TOKEN env var is required` until you set one. To run only the web service:

```bash
docker compose up -d web
```

---

## Using the web app

Open <http://localhost:5050>, paste a URL, click **Download**. The browser auto-downloads `<video title>.mp3` once conversion is done. Quality is 192 kbps.

Playlists are disabled — pass a single-video URL.

---

## Using the Telegram bot

1. Find your bot on Telegram (the username you chose with BotFather, e.g. `@my_mp3_bot`).
2. Send `/start`.
3. Send any message containing a YouTube link.
4. The bot replies "Downloading…" → "Uploading…" → the audio file.

**File size limit:** Telegram's default Bot API caps uploads at 50 MB. Larger files are tracked as `oversized` in the log and the bot tells you to use the web app instead. (A local Bot API server can raise this to 2 GB — ask if you want it set up.)

---

## Viewing logs

Every request and outcome is written to `logs/history.log` (rotated at 1 MB × 5 backups). The same lines also stream to each container's stdout.

```bash
# Tail the persisted log file
tail -f logs/history.log

# Watch the live container output (same content)
docker compose logs -f                # both services
docker compose logs -f web
docker compose logs -f bot
```

Log line format:

```
2026-05-14T15:18:42 INFO    request url='...' source=telegram who=42:user job=<id>
2026-05-14T15:19:29 INFO    success title='...' duration=300 size=4194304 job=<id> source=telegram url='...'
2026-05-14T15:19:30 WARNING oversized job=<id> title='...' size=131234732 limit=52428800 source=telegram who=...
```

Event types: `request`, `success` (yt-dlp finished), `delivered` (file actually sent to user), `oversized`, `failed`, `rejected`, `error`.

---

## Statistics CLI (`mp3-stats`)

Installed inside the image at `/usr/local/bin/mp3-stats`. Runs against the shared log file.

```bash
docker compose exec web mp3-stats <subcommand> [options]
```

(Use `bot` instead of `web` — same image, same data, same result.)

### Subcommands

| Command | Description |
|---|---|
| `summary` | Overall counts and totals (bytes, audio time). |
| `recent [-n N]` | Last N successful downloads with size and duration. Default `N=20`. |
| `top [-n N]` | Most-downloaded titles. Default `N=10`. |
| `ip` | Request counts grouped by client (web IP or Telegram user id). |
| `sources` | Breakdown table by source: `web` vs `telegram`. |
| `failures [-n N]` | Recent failed / rejected requests with error reason. |

### Global filter

`--source {web,telegram,all}` works on any subcommand:

```bash
docker compose exec web mp3-stats --source telegram summary
docker compose exec web mp3-stats --source telegram recent
docker compose exec web mp3-stats --source web failures
```

### Example output

```
$ docker compose exec web mp3-stats sources
source      requests  downloaded  delivered  oversized  failures         size
-----------------------------------------------------------------------------
telegram           1           1          0          1         0     125.2 MB
web                2           1          1          0         2     125.2 MB

$ docker compose exec web mp3-stats --source telegram summary
requests    1
downloaded  1
delivered   0
oversized   1
failed      0
rejected    0
errors      0

total mp3 bytes:   125.2 MB
total audio time:  91m 8s
```

Read the columns as: `requests` = URLs received, `downloaded` = yt-dlp produced an mp3, `delivered` = file actually reached the user, `oversized` = produced but blocked by Telegram's 50 MB cap.

---

## Project layout

```
.
├── app.py                # Flask routes
├── bot.py                # Telegram bot handlers
├── downloader.py         # Shared yt-dlp wrapper + logger
├── stats.py              # CLI for log analysis
├── templates/
│   └── index.html        # Web UI
├── Dockerfile            # One image, two entrypoints (web / bot)
├── docker-compose.yml    # web + bot services
├── requirements.txt
├── .env.example          # Template for .env (no secrets)
├── .env                  # Your bot token (gitignored)
├── logs/                 # Runtime log file (volume-mounted, gitignored)
└── .venv/                # Local Python env for non-Docker dev (gitignored)
```

---

## Configuration

Settings via environment variables (set in `.env`):

| Variable | Default | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | _required for bot_ | Token from @BotFather. |
| `MP3_LOG` | `logs/history.log` | Log file path for `mp3-stats` (override only if running CLI outside `/app`). |

Audio quality is hardcoded to **192 kbps mp3** in `downloader.py` — change `preferredquality` there if you want different.

---

## Running without Docker

You can run either service directly with the included venv:

```bash
source .venv/bin/activate
python app.py            # web on http://127.0.0.1:5050
# or:
TELEGRAM_BOT_TOKEN=... python bot.py
```

Stats works the same way: `python stats.py summary`. Requires `ffmpeg` on `PATH` (`brew install ffmpeg`).

---

## Common operations

```bash
# Stop everything
docker compose down

# Rebuild after code changes
docker compose up -d --build

# Restart just the bot (e.g. after editing .env)
docker compose up -d bot

# Wipe and start fresh
docker compose down && rm -rf logs && docker compose up -d --build
```
