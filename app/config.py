import os
from dotenv import load_dotenv

load_dotenv()

PLACEHOLDER_PREFIX = "change-me"


class Config:
    """Reads settings from environment variables (see .env.example)."""

    def __init__(self):
        e = os.environ.get
        self.SECRET_KEY = e("SECRET_KEY", "")
        self.CODE_PEPPER = e("CODE_PEPPER", "")
        self.DATABASE_PATH = e("DATABASE_PATH", "loyalty.db")
        self.ADMIN_USERNAME = e("ADMIN_USERNAME", "")
        self.ADMIN_PASSWORD = e("ADMIN_PASSWORD", "")
        self.MAX_FAILED_ATTEMPTS_PER_USER = int(e("MAX_FAILED_ATTEMPTS_PER_USER", "5"))
        self.MAX_FAILED_ATTEMPTS_PER_IP = int(e("MAX_FAILED_ATTEMPTS_PER_IP", "20"))
        self.LOCKOUT_WINDOW_MINUTES = int(e("LOCKOUT_WINDOW_MINUTES", "15"))
        self.CODE_VALID_DAYS = int(e("CODE_VALID_DAYS", "365"))
        self.NUM_PROXIES = int(e("NUM_PROXIES", "0"))
        self.COOKIE_SECURE = e("COOKIE_SECURE", "0") == "1"
        self.TESTING = False

    def as_dict(self):
        return {k: v for k, v in vars(self).items() if k.isupper()}


def validate_secrets(cfg: dict):
    """Refuse to start with missing or placeholder secrets (outside tests)."""
    if cfg.get("TESTING"):
        return
    for key in ("SECRET_KEY", "CODE_PEPPER"):
        v = cfg.get(key, "")
        if not v or v.startswith(PLACEHOLDER_PREFIX) or len(v) < 16:
            raise RuntimeError(
                f"{key} is missing, too short, or still the placeholder. "
                "Run `python scripts/init_env.py` to generate a .env file."
            )
