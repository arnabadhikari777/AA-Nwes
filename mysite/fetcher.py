"""News fetching, independent of the web app (run by tools/fetch_news.py on a schedule).

Reuses the ORIGINAL integration: NewsData.io, country=in, same API key (now from the
environment). Saves into the existing `news` table, never deletes anything.
"""
import logging
import re
import time
from datetime import datetime, timezone

import requests

try:
    import fcntl  # Linux (PythonAnywhere). Not on Windows: there the lock is skipped (local dev only).
except ImportError:  # pragma: no cover
    fcntl = None

import config
import db

log = logging.getLogger("aa_news.fetch")
LOCK_PATH = config.INSTANCE_DIR / "fetch.lock"
TIMEOUT = (5, 20)

try:  # the original app translated titles to English; keep that where available
    from deep_translator import GoogleTranslator
except Exception:  # pragma: no cover
    GoogleTranslator = None

_NON_LATIN = re.compile(r"[^\x00-\u024F\u2000-\u206F]")


class FetchLocked(RuntimeError):
    pass


class lock:
    """Non-blocking process lock: a second run exits immediately instead of overlapping."""

    def __enter__(self):
        config.INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
        self.f = open(LOCK_PATH, "w")
        if fcntl is None:
            return self
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.f.close()
            raise FetchLocked("another fetch is already running")
        return self

    def __exit__(self, *a):
        try:
            if fcntl is not None:
                fcntl.flock(self.f, fcntl.LOCK_UN)
        finally:
            self.f.close()


def _norm_time(s):
    """NewsData gives 'YYYY-MM-DD HH:MM:SS' in UTC -> store UTC ISO."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return None


def _budget_ok(conn):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = db.get_setting(conn, "api_calls_today", "")
    day, _, n = raw.partition(":")
    n = int(n) if day == today and n.isdigit() else 0
    return n < config.NEWSDATA_MAX_CALLS_PER_DAY, today, n


def _count_call(conn, today, n):
    db.set_setting(conn, "api_calls_today", f"{today}:{n + 1}")
    conn.commit()


def _call_api(params):
    r = requests.get(config.NEWSDATA_ENDPOINT, params=params, timeout=TIMEOUT,
                     headers={"User-Agent": "AA-News/2.0"})
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"API returned non-JSON (HTTP {r.status_code})")
    if r.status_code == 429:
        raise RuntimeError("API rate limit / quota reached (HTTP 429)")
    if r.status_code >= 400 or data.get("status") != "success":
        msg = ""
        res = data.get("results")
        if isinstance(res, dict):
            msg = res.get("message") or res.get("code") or ""
        raise RuntimeError(f"API error (HTTP {r.status_code}) {str(msg)[:120]}")
    return data.get("results") or []


def _maybe_translate(title):
    if GoogleTranslator and title and _NON_LATIN.search(title):
        try:
            return GoogleTranslator(source="auto", target="en").translate(title) or title
        except Exception:
            return title
    return title


def save_articles(conn, results, category):
    """Insert new articles; returns (new, duplicates, invalid). One transaction."""
    new = dup = bad = 0
    now = db.utcnow_iso()
    for art in results:
        title = (art.get("title") or "").strip()
        link = (art.get("link") or "").strip()
        if not title or not link.startswith(("http://", "https://")):
            bad += 1
            continue
        title = _maybe_translate(title)
        ext = art.get("article_id")
        exists = None
        if ext:
            exists = conn.execute("SELECT id FROM news WHERE external_id=?", (ext,)).fetchone()
        if not exists:
            exists = conn.execute("SELECT id FROM news WHERE url=? OR title=? COLLATE NOCASE",
                                  (link, title)).fetchone()
        if exists:
            dup += 1
            continue
        creators = art.get("creator")
        author = ", ".join(creators) if isinstance(creators, list) and creators else None
        desc = art.get("description")
        cur = conn.execute(
            "INSERT OR IGNORE INTO news (title, source, image_url, url, category, content, description, author, "
            "external_id, published_at, created_at, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,'published')",
            (title, art.get("source_id"), art.get("image_url"), link, category, "",
             (desc or None), author, ext, _norm_time(art.get("pubDate")), now))
        if cur.rowcount:
            new += 1
        else:
            dup += 1
    return new, dup, bad


def _site_categories(conn):
    slugs = [r["slug"] for r in conn.execute("SELECT slug FROM categories ORDER BY id")]
    return [s for s in slugs if s in config.API_CATEGORIES]


def run(trigger="scheduled"):
    """One fetch cycle. Always returns a summary dict; never raises for API problems."""
    if not config.NEWSDATA_API_KEY:
        raise SystemExit("NEWSDATA_API_KEY is not set (see .env.example).")
    summary = dict(status="success", api_calls=0, fetched=0, new_saved=0, duplicates=0, invalid=0, error=None)
    try:
        lk = lock()
        lk.__enter__()
    except FetchLocked:
        summary.update(status="skipped", error="another fetch is already running")
        return summary
    conn = db.connect()
    started = db.utcnow_iso()
    run_id = conn.execute("INSERT INTO fetch_runs(started_at, trigger, status) VALUES(?,?,'running')",
                          (started, trigger)).lastrowid
    conn.commit()
    errors = []
    try:
        # Call 1: the general Indian feed ('all'), exactly as the original app did.
        # Call 2: ONE category per run, rotating, so all categories refresh within a few hours
        # while staying inside the API quota (2 calls x 48 runs = 96 calls/day).
        cats = _site_categories(conn)
        idx = int(db.get_setting(conn, "category_cursor", "0") or 0)
        plan = [("all", {})]
        if cats:
            c = cats[idx % len(cats)]
            plan.append((c, {"category": c}))
            db.set_setting(conn, "category_cursor", (idx + 1) % len(cats))
            conn.commit()
        for cat, extra in plan:
            ok, today, n = _budget_ok(conn)
            if not ok:
                errors.append("daily API call budget reached (NEWSDATA_MAX_CALLS_PER_DAY)")
                break
            try:
                results = _call_api({"apikey": config.NEWSDATA_API_KEY, "country": "in", **extra})
                _count_call(conn, today, n)
                summary["api_calls"] += 1
                summary["fetched"] += len(results)
                conn.execute("BEGIN IMMEDIATE")
                try:
                    new, dup, bad = save_articles(conn, results, cat)
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                summary["new_saved"] += new
                summary["duplicates"] += dup
                summary["invalid"] += bad
            except Exception as e:  # requests errors, API errors, DB errors
                msg = str(e)
                if config.NEWSDATA_API_KEY:
                    msg = msg.replace(config.NEWSDATA_API_KEY, "***")
                errors.append(f"{cat}: {type(e).__name__}: {msg[:200]}")
                log.error("fetch failed for %s: %s", cat, msg)
            time.sleep(1)
        if errors:
            summary["status"] = "partial" if summary["api_calls"] and len(errors) < len(plan) else "error"
            summary["error"] = " | ".join(errors)
        else:
            db.set_setting(conn, "last_success_at", db.utcnow_iso())
        db.set_setting(conn, "last_run_at", db.utcnow_iso())
        conn.execute(
            "UPDATE fetch_runs SET finished_at=?, status=?, api_calls=?, fetched=?, new_saved=?, duplicates=?, "
            "invalid=?, error=? WHERE id=?",
            (db.utcnow_iso(), summary["status"], summary["api_calls"], summary["fetched"], summary["new_saved"],
             summary["duplicates"], summary["invalid"], summary["error"], run_id))
        conn.commit()
    finally:
        conn.close()
        lk.__exit__()
    return summary
