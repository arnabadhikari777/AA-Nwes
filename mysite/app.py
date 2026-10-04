from flask import Flask, render_template, jsonify, request, session, redirect, url_for, send_from_directory
import requests
import sqlite3
import os
import hmac
import time
import json
import re
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# pywebpush is optional: if it is not installed the site still works,
# only the push notifications are switched off.
try:
    from pywebpush import webpush, WebPushException
except ImportError:
    webpush = None
    WebPushException = Exception

# Absolute path to the project folder, so the app works correctly
# no matter what the current working directory is (important on PythonAnywhere).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load secrets from the .env file that sits next to this app.py.
# The .env file is NEVER uploaded to GitHub (it is listed in .gitignore).
load_dotenv(os.path.join(BASE_DIR, '.env'))


def get_required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required setting '{name}'. "
            f"Add it to the .env file (see .env.example)."
        )
    return value


app = Flask(__name__)
# Secret key for session (required for the login system) - comes from .env
app.secret_key = get_required_env("SECRET_KEY")

# Your NewsData.io API KEY - comes from .env
api_key = get_required_env("NEWSDATA_API_KEY")

# Admin login password - comes from .env
ADMIN_PASSWORD = get_required_env("ADMIN_PASSWORD")

# Secret token that protects the scheduled /cron/fetch link - comes from .env
CRON_TOKEN = get_required_env("CRON_TOKEN")

# Push-notification keys (optional). Without them push is simply disabled.
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")
PUSH_ENABLED = bool(webpush and VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY)

# Notification limits, so readers are not spammed
MAX_PUSH_PER_DAY = 3          # at most 3 breaking-news alerts a day
MIN_MINUTES_BETWEEN_PUSH = 90 # and at least 90 minutes apart
QUIET_HOURS_IST = (23, 6)     # no alerts from 11 PM to 6 AM (India time)
MAX_SUBSCRIPTIONS = 5000

# Absolute path to the database file, so the app works correctly
# no matter what the current working directory is (important on PythonAnywhere).
DB_PATH = os.path.join(BASE_DIR, 'news.db')

# 1. Function to create the database and tables
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # url is not kept UNIQUE here, and a content column has been added
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            source TEXT,
            image_url TEXT,
            url TEXT,
            category TEXT,
            content TEXT
        )
    ''')

    # Categories table, so the admin can create/manage categories from the panel
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE,
            label TEXT
        )
    ''')

    # Push notification tables (new, harmless: they do not touch the news table)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint TEXT UNIQUE,
            p256dh TEXT,
            auth TEXT,
            created_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS push_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER,
            title TEXT,
            sent_at TEXT,
            recipients INTEGER
        )
    ''')

    # Seed the default categories only if the table is empty (first run),
    # so existing sites keep exactly the same categories as before.
    cursor.execute("SELECT COUNT(*) FROM categories")
    if cursor.fetchone()[0] == 0:
        default_categories = [
            ('all', 'All / Home'),
            ('business', 'Business'),
            ('technology', 'Technology'),
            ('sports', 'Sports'),
            ('entertainment', 'Entertainment'),
            ('health', 'Health'),
            ('science', 'Science'),
        ]
        cursor.executemany("INSERT INTO categories (slug, label) VALUES (?, ?)", default_categories)

    conn.commit()
    conn.close()

    # Remove any duplicate news that may already be in the database
    # (e.g. from before this fix), keeping the oldest copy of each title.
    dedupe_existing_news()

    # Enforce uniqueness by title (case-insensitive) at the database level.
    # This is the real fix for duplicates: even if the dedup check in the
    # fetch functions is somehow bypassed (e.g. two server workers running
    # at the same time), SQLite itself will now refuse a second copy.
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_news_title_unique
            ON news (title COLLATE NOCASE)
        ''')
        conn.commit()
    except sqlite3.IntegrityError:
        # In case dedupe_existing_news() missed something, don't crash the app;
        # duplicates just won't be fully blocked until the next cleanup pass.
        pass
    conn.close()

# Removes duplicate news rows (same title, case-insensitive), keeping the
# earliest one (lowest id) of each. Safe to run every time the app starts.
def dedupe_existing_news():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM news ORDER BY id ASC")
    rows = cursor.fetchall()

    seen_titles = set()
    duplicate_ids = []
    for news_id, title in rows:
        key = (title or '').strip().lower()
        if key in seen_titles:
            duplicate_ids.append(news_id)
        else:
            seen_titles.add(key)

    if duplicate_ids:
        cursor.executemany("DELETE FROM news WHERE id=?", [(i,) for i in duplicate_ids])
        conn.commit()
        print(f"Removed {len(duplicate_ids)} duplicate news rows.")

    conn.close()
def get_all_categories():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT slug, label FROM categories ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [{"slug": r[0], "label": r[1]} for r in rows]

# ---------------------------------------------------------------------------
# 2. News fetching (runs ONLY from the scheduled /cron/fetch route)
# ---------------------------------------------------------------------------

# Only these two languages are allowed on the site.
# NewsData.io language codes: en = English, bn = Bengali.
API_LANGUAGES = "en,bn"
ALLOWED_API_LANGUAGE_NAMES = {"english", "bengali"}

# Categories that NewsData.io actually understands. Custom categories that the
# admin creates by hand are skipped by the scheduled fetch (they hold manual news).
NEWSDATA_CATEGORIES = {
    "business", "entertainment", "environment", "food", "health", "politics",
    "science", "sports", "technology", "top", "tourism", "world",
}

DEFAULT_IMAGE = "https://dummyimage.com/600x300/131921/ff9d00.png&text=A.A.News"


def is_english_or_bengali(text):
    """Safety net on top of the API language filter.

    The API sometimes mislabels a story, so we also look at the actual letters
    of the headline: it must be (almost) entirely Bengali script or Latin
    (English) letters. Hindi, Urdu, Arabic, Chinese, etc. are rejected.
    """
    if not text:
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    bengali = sum(1 for c in letters if '\u0980' <= c <= '\u09FF')
    latin = sum(1 for c in letters if c.isascii())
    other = len(letters) - bengali - latin
    return other / len(letters) <= 0.1 and (bengali + latin) > 0


def fetch_and_store(category=None, save_as=None):
    """Pull one batch of news from NewsData.io and save it in the database.

    Returns a dict like {"category": "all", "saved": 7, "skipped": 3}.
    Nothing is translated: English stories stay English and Bengali stories
    stay Bengali, exactly as the publisher wrote them.
    """
    params = {
        "apikey": api_key,
        "country": "in",
        "language": API_LANGUAGES,
    }
    if category and category != "all":
        params["category"] = category

    response = requests.get("https://newsdata.io/api/1/news", params=params, timeout=20)
    data = response.json()

    if data.get("status") != "success":
        raise RuntimeError(f"NewsData API error: {data.get('results')}")

    save_as = save_as or category or "all"
    saved = 0
    skipped = 0
    new_items = []

    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        cursor = conn.cursor()
        for article in data.get("results", []):
            title = (article.get("title") or "").strip()
            news_url = article.get("link")
            language = (article.get("language") or "").strip().lower()

            # Language filter: API label first, then the real letters as a safety net
            if language and language not in ALLOWED_API_LANGUAGE_NAMES:
                skipped += 1
                continue
            if not title or not news_url or not is_english_or_bengali(title):
                skipped += 1
                continue

            cursor.execute(
                "SELECT id FROM news WHERE url=? OR LOWER(TRIM(title))=?",
                (news_url, title.lower())
            )
            if cursor.fetchone():
                skipped += 1
                continue

            # INSERT OR IGNORE: the unique title index quietly blocks duplicates
            cursor.execute(
                """
                INSERT OR IGNORE INTO news (title, source, image_url, url, category, content)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (title, article.get("source_id"), article.get("image_url") or DEFAULT_IMAGE,
                 news_url, save_as, "")
            )
            if cursor.rowcount:
                saved += 1
                new_items.append({
                    "id": cursor.lastrowid, "title": title, "url": news_url,
                    "image": article.get("image_url") or "",
                })
        conn.commit()
    finally:
        conn.close()

    return {"category": category or "all", "saved": saved, "skipped": skipped, "new_items": new_items}


def pick_categories_for_this_run(full=False):
    """Decides which API calls to make in one scheduled run.

    Returns a list of (api_category, save_as) pairs.
    - 'top' is fetched first and saved on the home feed: these are the
      candidates for the breaking-news notification.
    - 'all' (general news) is fetched every run.
    - ONE more category is fetched per run, rotating every 30 minutes.
    That is 3 API calls x 48 runs = 144 calls a day (free plan: 200 credits).
    Pass full=True (/cron/fetch?full=1) to fetch every category once.
    """
    site_categories = [c["slug"] for c in get_all_categories()]
    rotating = [c for c in site_categories if c in NEWSDATA_CATEGORIES and c != "top"]
    picks = [("top", "all"), (None, "all")]
    if full:
        picks += [(c, c) for c in rotating]
    elif rotating:
        c = rotating[int(time.time() // 1800) % len(rotating)]
        picks.append((c, c))
    return picks


# ---------------------------------------------------------------------------
# 2b. Push notifications (breaking news to readers' phones)
# ---------------------------------------------------------------------------

def _ist_now():
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)


def in_quiet_hours():
    start, end = QUIET_HOURS_IST
    h = _ist_now().hour
    return h >= start or h < end


def load_subscriptions():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    rows = conn.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions").fetchall()
    conn.close()
    return [{"endpoint": r[0], "keys": {"p256dh": r[1], "auth": r[2]}} for r in rows]


def send_push_to_all(payload):
    """Sends one notification to every subscribed phone.

    Dead subscriptions (user uninstalled / blocked notifications) are removed.
    Returns {"sent": n, "removed": n, "failed": n}.
    """
    subs = load_subscriptions()
    if not subs:
        return {"sent": 0, "removed": 0, "failed": 0}
    body = json.dumps(payload)

    def send_one(sub):
        try:
            webpush(
                subscription_info=sub,
                data=body,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
                ttl=3600,      # a breaking alert older than an hour is useless
                timeout=10,
            )
            return ("ok", sub["endpoint"])
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            return ("gone" if status in (404, 410) else "fail", sub["endpoint"])
        except Exception:
            return ("fail", sub["endpoint"])

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(send_one, subs))

    gone = [ep for status, ep in results if status == "gone"]
    if gone:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.executemany("DELETE FROM push_subscriptions WHERE endpoint=?", [(g,) for g in gone])
        conn.commit()
        conn.close()
    return {
        "sent": sum(1 for r in results if r[0] == "ok"),
        "removed": len(gone),
        "failed": sum(1 for r in results if r[0] == "fail"),
    }


def maybe_send_breaking_push(candidates):
    """Takes the newly saved 'top' stories and sends at most ONE notification.

    Returns a short text describing what happened (shown in the cron response).
    """
    if not PUSH_ENABLED:
        return "push disabled"
    if not candidates:
        return "no new top story"
    if in_quiet_hours():
        return "quiet hours"

    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        today_start_ist = _ist_now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = (today_start_ist - timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        sent_today = conn.execute("SELECT COUNT(*) FROM push_log WHERE sent_at >= ?", (today_start_utc,)).fetchone()[0]
        last = conn.execute("SELECT sent_at FROM push_log ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()

    if sent_today >= MAX_PUSH_PER_DAY:
        return "daily limit reached"
    if last:
        last_dt = datetime.strptime(last[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last_dt < timedelta(minutes=MIN_MINUTES_BETWEEN_PUSH):
            return "too soon after the last alert"

    story = candidates[0]   # the API lists the newest story first
    result = send_push_to_all({
        "title": "🔴 Breaking · A.A.News",
        "body": story["title"],
        "image": story["image"] if str(story["image"]).startswith("https://") else "",
        "url": story["url"],
        "tag": "breaking-news",
    })

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute(
        "INSERT INTO push_log (news_id, title, sent_at, recipients) VALUES (?, ?, ?, ?)",
        (story["id"], story["title"], datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), result["sent"])
    )
    conn.commit()
    conn.close()
    return f"sent to {result['sent']} phones (removed {result['removed']}, failed {result['failed']})"


# The database tables are created when the server starts.
# (No news is fetched here any more - the scheduled job does that.)
init_db()

# 3. Route to display the main website
@app.route('/')
def home():
    return render_template('news_portal_frontend.html')

# 4. Route to fetch news from the database and send it to the website (for All / Home)
# Supports infinite scrolling via ?offset= and ?limit=.
# This route only READS the database; fresh news arrives via /cron/fetch.
@app.route('/get_news')
def get_news():
    limit = request.args.get('limit', default=20, type=int)
    offset = request.args.get('offset', default=0, type=int)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, title, source, image_url, url, content FROM news WHERE category='all' ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset)
    )
    rows = cursor.fetchall()
    conn.close()

    news_list = []
    for row in rows:
        news_list.append({
            "id": row[0],
            "title": row[1],
            "source": {"name": row[2]},
            "urlToImage": row[3],
            "url": row[4]
        })

    return jsonify(news_list)

# 5. Route to read news of one category from the database
# Supports infinite scrolling via ?offset= and ?limit=
@app.route('/category/<cat_name>')
def get_category_news(cat_name):
    limit = request.args.get('limit', default=20, type=int)
    offset = request.args.get('offset', default=0, type=int)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, title, source, image_url, url, content FROM news WHERE category=? ORDER BY id DESC LIMIT ? OFFSET ?',
        (cat_name, limit, offset)
    )
    rows = cursor.fetchall()
    conn.close()

    news_list = []
    for row in rows:
        news_list.append({
            "id": row[0],
            "title": row[1],
            "source": {"name": row[2]},
            "urlToImage": row[3],
            "url": row[4]
        })

    return jsonify(news_list)

# Public route: returns all categories as JSON, used by the frontend to build the menu
@app.route('/get_categories')
def get_categories():
    return jsonify(get_all_categories())

# Scheduled fetch: called every 30 minutes by cron-job.org, even when nobody
# is visiting the site. Protected by a secret token that lives in .env.
def _token_ok():
    token = request.args.get('token', '')
    return hmac.compare_digest(token.encode('utf-8'), CRON_TOKEN.encode('utf-8'))


@app.route('/cron/fetch')
def cron_fetch():
    if not _token_ok():
        return jsonify({"status": "forbidden"}), 403

    full = request.args.get('full') == '1'
    results = []
    top_new_items = []
    for api_cat, save_as in pick_categories_for_this_run(full=full):
        try:
            r = fetch_and_store(api_cat, save_as)
            if api_cat == "top":
                top_new_items = r["new_items"]
            r.pop("new_items", None)
            results.append(r)
        except Exception as e:
            results.append({"category": api_cat or "all", "error": str(e)})

    try:
        push_info = maybe_send_breaking_push(top_new_items)
    except Exception as e:
        push_info = f"push error: {e}"

    ok = any("error" not in r for r in results)
    print("Scheduled fetch:", results, "| push:", push_info)
    return jsonify({"status": "ok" if ok else "failed", "results": results, "push": push_info}), (200 if ok else 502)


# Sends a test notification to every subscribed phone (token protected)
@app.route('/cron/test_push')
def cron_test_push():
    if not _token_ok():
        return jsonify({"status": "forbidden"}), 403
    if not PUSH_ENABLED:
        return jsonify({"status": "push disabled", "hint": "check pywebpush and the VAPID keys in .env"}), 503
    result = send_push_to_all({
        "title": "A.A.News test",
        "body": "Notifications are working. ✅",
        "url": "/",
        "tag": "test",
    })
    return jsonify({"status": "ok", **result})


# ---------------------------------------------------------------------------
# PWA files and subscription routes
# ---------------------------------------------------------------------------

@app.route('/manifest.webmanifest')
def manifest():
    data = {
        "id": "/",
        "name": "AA News",
        "short_name": "AA News",
        "description": "Latest news in English and Bengali, updated around the clock.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#0e1a30",
        "theme_color": "#0e1a30",
        "lang": "en",
        "categories": ["news"],
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-maskable-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    resp = jsonify(data)
    resp.mimetype = 'application/manifest+json'
    return resp


# The service worker must be served from the site root so it can control every page
@app.route('/sw.js')
def service_worker():
    resp = send_from_directory(os.path.join(BASE_DIR, 'static'), 'sw.js', mimetype='application/javascript')
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.route('/offline')
def offline():
    return render_template('offline.html')


@app.route('/push/public-key')
def push_public_key():
    return jsonify({"key": VAPID_PUBLIC_KEY if PUSH_ENABLED else ""})


@app.route('/push/subscribe', methods=['POST'])
def push_subscribe():
    if not PUSH_ENABLED:
        return jsonify({"status": "push disabled"}), 503
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint", "")
    keys = data.get("keys") or {}
    p256dh, auth = keys.get("p256dh", ""), keys.get("auth", "")
    if not (isinstance(endpoint, str) and endpoint.startswith("https://") and len(endpoint) < 1000
            and isinstance(p256dh, str) and isinstance(auth, str)
            and 0 < len(p256dh) < 200 and 0 < len(auth) < 100):
        return jsonify({"status": "invalid subscription"}), 400

    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        count = conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]
        exists = conn.execute("SELECT 1 FROM push_subscriptions WHERE endpoint=?", (endpoint,)).fetchone()
        if not exists and count >= MAX_SUBSCRIPTIONS:
            return jsonify({"status": "subscription limit reached"}), 503
        conn.execute(
            "INSERT OR REPLACE INTO push_subscriptions (endpoint, p256dh, auth, created_at) VALUES (?, ?, ?, ?)",
            (endpoint, p256dh, auth, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"status": "subscribed"})


@app.route('/push/unsubscribe', methods=['POST'])
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint", "")
    if isinstance(endpoint, str) and endpoint:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))
        conn.commit()
        conn.close()
    return jsonify({"status": "unsubscribed"})


# 6. Login page
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password')
        # Constant-time comparison; the password itself lives in .env
        if password and hmac.compare_digest(password.encode('utf-8'), ADMIN_PASSWORD.encode('utf-8')):
            session['is_admin'] = True
            return redirect(url_for('add_news'))
        else:
            error = "Wrong password! Please try again."
    return render_template('login.html', error=error)

# 7. Logout
@app.route('/logout')
def logout():
    session.pop('is_admin', None)
    return redirect(url_for('home'))

# 8. Admin panel (for manually writing news)
@app.route('/add_news', methods=['GET', 'POST'])
def add_news():
    # Login check: if not logged in, redirect straight to the login page
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    message = ""
    if request.method == 'POST':
        title = request.form.get('title')
        source = request.form.get('source')
        image_url = request.form.get('image_url')
        content = request.form.get('content')
        category = request.form.get('category')

        # If no image is given, a default image will be used
        if not image_url:
            image_url = "https://dummyimage.com/600x300/131921/ff9d00.png&text=A.A.News"

        if title and content:
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                # URL is being kept empty, because we will show the content
                cursor.execute('''
                    INSERT INTO news (title, source, image_url, url, category, content)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (title, source, image_url, "", category, content))
                conn.commit()
                conn.close()
                message = "The news has been successfully published on the website!"
            except Exception as e:
                message = f"An error occurred: {e}"
        else:
            message = "News title and detailed content are mandatory!"

    return render_template('add_news.html', message=message, categories=get_all_categories())

# 8b. Admin Dashboard - shows every news item with Edit / Delete buttons,
# plus category management (add / delete categories)
@app.route('/admin')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    # Only one page of news is sent to the browser (thousands of rows made the page slow)
    per_page = 20
    q = request.args.get('q', '').strip()[:100]
    where, params = '', []
    if q:
        where = 'WHERE title LIKE ? OR source LIKE ?'
        params = ['%' + q + '%', '%' + q + '%']

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    total_all = cursor.execute('SELECT COUNT(*) FROM news').fetchone()[0]
    total_news = cursor.execute('SELECT COUNT(*) FROM news ' + where, params).fetchone()[0]
    pages = max(1, -(-total_news // per_page))
    page = min(max(request.args.get('page', 1, type=int), 1), pages)
    cursor.execute(
        'SELECT id, title, source, category FROM news ' + where + ' ORDER BY id DESC LIMIT ? OFFSET ?',
        params + [per_page, (page - 1) * per_page]
    )
    news_rows = cursor.fetchall()
    conn.close()

    news_items = [
        {"id": r[0], "title": r[1], "source": r[2], "category": r[3]}
        for r in news_rows
    ]

    return render_template(
        'admin_dashboard.html',
        news_items=news_items,
        categories=get_all_categories(),
        total_all=total_all, total_news=total_news,
        page=page, pages=pages, q=q,
        start=(page - 1) * per_page + (1 if news_items else 0),
        end=(page - 1) * per_page + len(news_items)
    )

# 8c. Edit an existing news item
@app.route('/admin/edit/<int:news_id>', methods=['GET', 'POST'])
def edit_news(news_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if request.method == 'POST':
        title = request.form.get('title')
        source = request.form.get('source')
        image_url = request.form.get('image_url')
        content = request.form.get('content')
        category = request.form.get('category')

        if not image_url:
            image_url = "https://dummyimage.com/600x300/131921/ff9d00.png&text=A.A.News"

        try:
            cursor.execute('''
                UPDATE news
                SET title=?, source=?, image_url=?, content=?, category=?
                WHERE id=?
            ''', (title, source, image_url, content, category, news_id))
            conn.commit()
            conn.close()
            return redirect(url_for('admin_dashboard'))
        except sqlite3.IntegrityError:
            conn.close()
            # Happens if the new title matches another existing news item's title
            error = "A news item with this exact title already exists. Please change the title slightly."
            news_item = {
                "id": news_id, "title": title, "source": source,
                "image_url": image_url, "url": "", "category": category, "content": content
            }
            return render_template('edit_news.html', news=news_item, categories=get_all_categories(), error=error)

    cursor.execute('SELECT id, title, source, image_url, url, category, content FROM news WHERE id=?', (news_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return "News not found!", 404

    news_item = {
        "id": row[0], "title": row[1], "source": row[2],
        "image_url": row[3], "url": row[4], "category": row[5], "content": row[6]
    }

    return render_template('edit_news.html', news=news_item, categories=get_all_categories())

# 8d. Delete a news item
@app.route('/admin/delete/<int:news_id>', methods=['POST'])
def delete_news(news_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM news WHERE id=?', (news_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))

# 8e. Add a new category
@app.route('/admin/add_category', methods=['POST'])
def add_category():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    label = (request.form.get('label') or '').strip()
    if label:
        # Build a simple slug: lowercase, spaces -> hyphens, only letters/numbers/hyphens kept
        slug = ''.join(c if c.isalnum() else '-' for c in label.lower()).strip('-')
        while '--' in slug:
            slug = slug.replace('--', '-')

        if slug:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO categories (slug, label) VALUES (?, ?)", (slug, label))
                conn.commit()
            except sqlite3.IntegrityError:
                pass  # category with this slug already exists, ignore silently
            conn.close()

    return redirect(url_for('admin_dashboard'))

# 8f. Delete a category (any news in it is moved back to 'all' so nothing is lost)
@app.route('/admin/delete_category/<slug>', methods=['POST'])
def delete_category(slug):
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    # The 'all' category is the site's default feed and cannot be removed
    if slug != 'all':
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE news SET category='all' WHERE category=?", (slug,))
        cursor.execute("DELETE FROM categories WHERE slug=?", (slug,))
        conn.commit()
        conn.close()

    return redirect(url_for('admin_dashboard'))

# 9. Page for reading self-written news
@app.route('/read/<int:news_id>')
def read_news(news_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT title, source, image_url, content FROM news WHERE id=?', (news_id,))
    news = cursor.fetchone()
    conn.close()

    if news:
        return render_template('read_news.html', news=news)
    else:
        return "News not found!", 404

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy.html')


# ---------------------------------------------------------------
# Live presence: how many people are on the site right now
# ---------------------------------------------------------------
# Every open page sends a small "I'm here" ping every ~12 seconds (static/presence.js).
# A person who closes the page sends a "leave" message, and anyone who goes quiet for
# PRESENCE_TTL seconds is counted as gone. Visitors and dashboard viewers are kept apart,
# so the admin looking at the dashboard never shows up in the visitor count.
# Stored in its own small file (presence.db) so it never touches news.db.
PRESENCE_DB = os.path.join(BASE_DIR, 'presence.db')
PRESENCE_TTL = 45
_presence_ready = False
_ID_RE = re.compile(r'^[A-Za-z0-9_-]{8,64}$')


def presence_conn():
    global _presence_ready
    conn = sqlite3.connect(PRESENCE_DB, timeout=5)
    if not _presence_ready:
        conn.execute(
            'CREATE TABLE IF NOT EXISTS presence ('
            'tab TEXT PRIMARY KEY, browser TEXT NOT NULL, role TEXT NOT NULL, '
            'page TEXT, device TEXT, first_seen REAL NOT NULL, last_seen REAL NOT NULL)'
        )
        conn.commit()
        _presence_ready = True
    return conn


def page_label(path):
    path = path or '/'
    if path == '/':
        return 'Home'
    if path.startswith('/read/'):
        return 'Reading an article'
    if path.startswith('/about'):
        return 'About page'
    if path.startswith('/privacy'):
        return 'Privacy page'
    if path.startswith('/admin'):
        return 'Dashboard'
    return path[:40]


@app.route('/presence/ping', methods=['POST'])
def presence_ping():
    data = request.get_json(silent=True, force=True) or {}
    tab, browser = str(data.get('tab', '')), str(data.get('browser', ''))
    if not (_ID_RE.match(tab) and _ID_RE.match(browser)):
        return '', 400
    role = 'admin' if data.get('role') == 'admin' else 'visitor'
    if role == 'admin' and not session.get('is_admin'):
        return '', 403            # only a logged-in admin can be counted as a dashboard viewer
    page = str(data.get('page', '/'))[:80]
    if not page.startswith('/'):
        page = '/'
    ua = request.headers.get('User-Agent', '').lower()
    device = 'Mobile' if any(k in ua for k in ('mobi', 'android', 'iphone', 'ipad')) else 'Desktop'
    now = time.time()
    conn = presence_conn()
    try:
        conn.execute(
            'INSERT INTO presence (tab, browser, role, page, device, first_seen, last_seen) '
            'VALUES (?, ?, ?, ?, ?, ?, ?) '
            'ON CONFLICT(tab) DO UPDATE SET browser = excluded.browser, page = excluded.page, '
            'device = excluded.device, '
            'first_seen = CASE WHEN presence.role = excluded.role AND excluded.last_seen - presence.last_seen < ? '
            'THEN presence.first_seen ELSE excluded.first_seen END, '
            'role = excluded.role, last_seen = excluded.last_seen',
            (tab, browser, role, page, device, now, now, PRESENCE_TTL)
        )
        conn.commit()
    finally:
        conn.close()
    return '', 204


@app.route('/presence/leave', methods=['POST'])
def presence_leave():
    data = request.get_json(silent=True, force=True) or {}
    tab = str(data.get('tab', ''))
    if _ID_RE.match(tab):
        conn = presence_conn()
        try:
            conn.execute('DELETE FROM presence WHERE tab = ?', (tab,))
            conn.commit()
        finally:
            conn.close()
    return '', 204


@app.route('/admin/presence')
def admin_presence():
    if not session.get('is_admin'):
        return jsonify({'error': 'login required'}), 401
    now = time.time()
    conn = presence_conn()
    try:
        conn.execute('DELETE FROM presence WHERE last_seen < ?', (now - 300,))   # tidy up old rows
        conn.commit()
        rows = conn.execute(
            'SELECT role, browser, page, device, first_seen FROM presence '
            'WHERE last_seen >= ? ORDER BY first_seen', (now - PRESENCE_TTL,)
        ).fetchall()
    finally:
        conn.close()

    visitors, admins = [], []
    seen = {'visitor': set(), 'admin': set()}
    for role, browser, page, device, first_seen in rows:
        if browser in seen[role]:
            continue              # same person with several tabs open counts once
        seen[role].add(browser)
        item = {'device': device, 'page': page_label(page), 'seconds': int(now - first_seen)}
        (admins if role == 'admin' else visitors).append(item)

    resp = jsonify({
        'visitors': len(visitors), 'admins': len(admins),
        'visitor_list': visitors[:40], 'admin_list': admins[:10],
    })
    resp.headers['Cache-Control'] = 'no-store'
    return resp

if __name__ == '__main__':
    # This block only runs when you start the app locally with `python app.py`.
    # PythonAnywhere does NOT use this block — it imports the `app` object
    # directly through the WSGI configuration file instead.
    # Debug mode only when explicitly enabled in .env (FLASK_DEBUG=1)
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1')
