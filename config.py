import os
from dotenv import load_dotenv

load_dotenv()


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if value is None or not value.strip():
        raise RuntimeError(
            f"Missing required environment variable: {name}"
        )

    return value.strip()


def get_optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None

    value = value.strip()
    return value or None

BOT_TOKEN = get_required_env("BOT_TOKEN")
ADMIN_ID = int(get_required_env("ADMIN_ID"))
API_ID = int(get_required_env("API_ID"))
API_HASH = get_required_env("API_HASH")

SUDO_USERS = [
    int(user_id.strip())
    for user_id in os.getenv("SUDO_USERS", str(ADMIN_ID)).split(",")
    if user_id.strip()
]

DB_PATH = os.getenv("DB_PATH", "data/bot.db")
SESSIONS_DIR = os.getenv("SESSIONS_DIR", "sessions")

RAILWAY_BUCKET_ENDPOINT = get_optional_env("RAILWAY_BUCKET_ENDPOINT")
RAILWAY_BUCKET_NAME = get_optional_env("RAILWAY_BUCKET_NAME")
RAILWAY_BUCKET_ACCESS_KEY = get_optional_env("RAILWAY_BUCKET_ACCESS_KEY")
RAILWAY_BUCKET_SECRET_KEY = get_optional_env("RAILWAY_BUCKET_SECRET_KEY")
RAILWAY_BUCKET_REGION = get_optional_env("RAILWAY_BUCKET_REGION")
RAILWAY_BUCKET_PREFIX = get_optional_env("RAILWAY_BUCKET_PREFIX")

DEFAULT_DELAY = os.getenv("DEFAULT_DELAY", "1s")
DEFAULT_LOOP_DELAY = os.getenv("DEFAULT_LOOP_DELAY", "1h")
DEFAULT_SCHEDULE = os.getenv("DEFAULT_SCHEDULE") or None
USE_RICH_MARKDOWN = (
    os.getenv("USE_RICH_MARKDOWN", "true").lower() in ("true", "1", "yes", "on")
)