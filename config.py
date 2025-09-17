import os
from dotenv import load_dotenv


load_dotenv()


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OVERSEERR_URL = (os.getenv("OVERSEERR_URL") or "").rstrip("/")
OVERSEERR_API_KEY = os.getenv("OVERSEERR_API_KEY")
TMDB_IMAGE_BASE = os.getenv("TMDB_IMAGE_BASE", "https://image.tmdb.org/t/p/w500").rstrip("/")
DEFAULT_IS_4K = (os.getenv("REQUEST_4K", "false").strip().lower() in ("1", "true", "yes", "y"))
OWNER_TELEGRAM_USER_ID = os.getenv("OWNER_TELEGRAM_USER_ID")
# OMDB_API_KEY removed


def validate_config() -> None:
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not OVERSEERR_URL:
        missing.append("OVERSEERR_URL")
    if not OVERSEERR_API_KEY:
        missing.append("OVERSEERR_API_KEY")
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

