"""Central configuration. Secrets come from environment variables or a private .env
file (never committed). Nothing secret is hard-coded here."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent


def _load_dotenv():
    """Tiny .env loader (no extra dependency). Real environment variables win."""
    for p in (BASE_DIR / ".env", PROJECT_ROOT / ".env"):
        try:
            if not p.is_file():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except OSError:
            pass


_load_dotenv()


def env(name, default=None):
    return os.environ.get(name, default)


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- Paths -------------------------------------------------------------------
# The ORIGINAL database file. Never changed to a new location silently: if this file
# is missing the app refuses to start rather than creating an empty replacement.
DB_PATH = Path(env("AA_NEWS_DB", str(BASE_DIR / "news.db")))
INSTANCE_DIR = BASE_DIR / "instance"          # private files (secret key, lock) - gitignored
LOG_DIR = BASE_DIR / "logs"                   # gitignored
# Backups live OUTSIDE the project/static tree (default: sibling of the project folder).
BACKUP_DIR = Path(env("AA_NEWS_BACKUP_DIR", str(PROJECT_ROOT.parent / "aa_news_backups")))
UPLOAD_DIR = BASE_DIR / "static" / "uploads"

# --- Site --------------------------------------------------------------------
SITE_URL = env("SITE_URL", "https://arnabadhikari125117y.pythonanywhere.com").rstrip("/")
SITE_NAME = "A.A.News"
SITE_TAGLINE = "Your Trusted News Source"
GA_ID = env("GA_MEASUREMENT_ID", "G-M4Q795Q81V")  # existing Google Analytics id (public by nature)
CONTACT_EMAIL = env("CONTACT_EMAIL", "info@aanews.com")  # existing footer value - set your real one
DISPLAY_TZ = env("DISPLAY_TZ", "Asia/Kolkata")
ENVIRONMENT = env("AA_NEWS_ENV", "production")  # set to "development" for local http testing
INDEX_AGGREGATED = env("INDEX_AGGREGATED", "0") == "1"  # see README (thin-content note)

# --- Auth --------------------------------------------------------------------
# Preferred: ADMIN_PASSWORD_HASH (generate with tools/make_password_hash.py).
# Until you set it, the ORIGINAL admin password keeps working (kept only as a salted hash)
# and the admin dashboard shows a warning. Once set, the old password stops working.
LEGACY_ADMIN_HASH = "scrypt:32768:8:1$17wj07evPng7Ebxf$cf6a110bddcfa258bce6a2e2fb544ddabf0a3f033f0d624170c751f923adadb3362ae89d16c29afd17efc7c7b2a20065f83c2be79f552ab3e15de23cff974298"
ADMIN_PASSWORD_HASH = env("ADMIN_PASSWORD_HASH")
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60

# --- Fetching ----------------------------------------------------------------
NEWSDATA_API_KEY = env("NEWSDATA_API_KEY")
NEWSDATA_ENDPOINT = "https://newsdata.io/api/1/news"   # same endpoint the original app used
NEWSDATA_MAX_CALLS_PER_DAY = env_int("NEWSDATA_MAX_CALLS_PER_DAY", 150)
MANUAL_FETCH_COOLDOWN = 300  # seconds between admin "Fetch Now" clicks
# Categories the NewsData API understands (custom admin categories are skipped).
API_CATEGORIES = {
    "business", "technology", "sports", "entertainment", "health", "science",
    "politics", "world", "environment", "food", "tourism", "crime", "education",
    "lifestyle", "domestic", "top", "other",
}

# --- Uploads -----------------------------------------------------------------
MAX_UPLOAD_BYTES = 3 * 1024 * 1024


def load_secret_key():
    key = env("SECRET_KEY")
    if key:
        return key
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    f = INSTANCE_DIR / "secret_key"
    if f.is_file():
        return f.read_text().strip()
    key = secrets.token_hex(32)
    f.write_text(key)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return key
