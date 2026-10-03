import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config

try:
    TZ = ZoneInfo(config.DISPLAY_TZ)
except Exception:  # pragma: no cover
    TZ = timezone.utc


def slugify(text, max_len=80):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text[:max_len].strip("-") or "news"


def pretty_source(src):
    if not src:
        return "News"
    s = str(src).replace("_", " ").replace("-", " ").strip()
    return s.title() if s.islower() else s


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def format_dt(value):
    """'2 Oct 2026, 4:30 PM' in the site's display time zone, or relative for <24h."""
    dt = parse_iso(value)
    if not dt:
        return None
    delta = datetime.now(timezone.utc) - dt
    if timedelta(0) <= delta < timedelta(hours=1):
        m = max(1, int(delta.total_seconds() // 60))
        return f"{m} min ago"
    if timedelta(0) <= delta < timedelta(hours=24):
        h = int(delta.total_seconds() // 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    local = dt.astimezone(TZ)
    return local.strftime("%-d %b %Y, %-I:%M %p")


def ist_day_to_utc(day, end=False):
    """'YYYY-MM-DD' (display tz) -> UTC ISO string at start (or end) of that day."""
    try:
        d = datetime.strptime(day, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    if end:
        d = d + timedelta(days=1) - timedelta(seconds=1)
    return d.replace(tzinfo=TZ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reading_minutes(text):
    words = len((text or "").split())
    return max(1, round(words / 200)) if words >= 40 else None


def https_url(url):
    """Upgrade http image URLs so they are not blocked as mixed content."""
    if url and url.startswith("http://"):
        return "https://" + url[7:]
    return url


def paragraphs(text):
    parts = re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n").strip())
    return [p.strip() for p in parts if p.strip()]


def build_fts_query(q):
    """Turn free text into a safe FTS5 query (every term quoted; prefix on the last)."""
    terms = re.findall(r"\w+", q or "", flags=re.UNICODE)[:8]
    if not terms:
        return None
    parts = [f'"{t}"' for t in terms]
    parts[-1] += "*"
    return " ".join(parts)


def like_escape(s):
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


BOT_WORDS = ("bot", "crawl", "spider", "slurp", "preview", "headless", "curl", "wget", "python-requests", "monitor")


def is_bot(ua):
    ua = (ua or "").lower()
    return (not ua) or any(w in ua for w in BOT_WORDS)


STOP = set("the a an and or of to in on for with at by from is are was were be as it its this that "
           "after over new says say will has have not but into out up more than their his her he she "
           "they you we our us about amid how what who why when".split())


def build_words(title):
    return [w for w in re.findall(r"[a-z0-9]{3,}", (title or "").lower()) if w not in STOP]
