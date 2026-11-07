"""Configuration loaded from environment variables (.env supported, no extra dependency)."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).parent


def _load_dotenv():
    f = BASE_DIR / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_dotenv()

SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)  # sessions reset on restart if unset
CODE_PEPPER = os.environ.get("CODE_PEPPER", "dev-only-pepper-change-me")
DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "loyalty.db"))
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
PORT = int(os.environ.get("PORT", "5000"))

# Anti-fraud limits (see ASSUMPTIONS.md)
MAX_CODE_FAILS_PER_USER = 5      # failed code attempts allowed per 15 minutes
MAX_CODE_FAILS_PER_IP = 20       # failed code attempts allowed per hour
MAX_LOGIN_FAILS_PER_IP = 10      # failed logins allowed per 15 minutes
MAX_BATCH_SIZE = 5000
