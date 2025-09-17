## Telegram bot for Overseerr (search and requests)

The bot searches movies/TV in Overseerr and lets you submit download requests (auto-approved).

### Environment variables

Copy `.env.example` to `.env` and fill in:

- `TELEGRAM_BOT_TOKEN` — bot token from BotFather
- `OVERSEERR_URL` — Overseerr base URL (e.g. `http://localhost:5055`)
- `OVERSEERR_API_KEY` — Overseerr API key (Settings → API)
- `TMDB_IMAGE_BASE` — TMDB image base (default `https://image.tmdb.org/t/p/w500`)
- `REQUEST_4K` — request 4K profiles (true/false)
- `OWNER_TELEGRAM_USER_ID` — (optional) limit bot to your Telegram user ID

### Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

### Run (local)

```bash
export $(grep -v '^#' .env | xargs) # or use direnv/dotenv
python -m app
```

Send a movie or TV title to the bot. It returns up to 10 results with poster, year, type, and library status. The “⏬ Download” button creates a request in Overseerr and auto-approves it. For TV and movies, a “👀 Recommendations” button shows up to 10 recommendations with the same formatting.

### Notes

- Library availability is based on `mediaInfo.status`. If already available, the Download button is hidden.

### Docker/Portainer

1. Build image locally (optional):

```bash
docker build -f docker/Dockerfile -t overseerr-tg-bot:latest .
```

2. Environment variables (set via Portainer UI or docker-compose):

- `TELEGRAM_BOT_TOKEN`
- `OVERSEERR_URL` (e.g. `http://overseerr:5055` if on the same network)
- `OVERSEERR_API_KEY`
- `TMDB_IMAGE_BASE` (optional)
- `REQUEST_4K` (true/false)
- `OWNER_TELEGRAM_USER_ID` (optional)

3. docker-compose.yml example:

```yaml
services:
  overseerr-tg-bot:
    image: overseerr-tg-bot:latest
    restart: unless-stopped
    environment:
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      OVERSEERR_URL: ${OVERSEERR_URL}
      OVERSEERR_API_KEY: ${OVERSEERR_API_KEY}
      TMDB_IMAGE_BASE: ${TMDB_IMAGE_BASE:-https://image.tmdb.org/t/p/w500}
      REQUEST_4K: ${REQUEST_4K:-false}
      OWNER_TELEGRAM_USER_ID: ${OWNER_TELEGRAM_USER_ID:-}
```

In Portainer, create a Stack, paste this compose, and supply environment variables in the UI.
