"""A.A.News - Flask application (upgrade of the original single-file app).

Key differences from the original:
  * NO fetching on startup or on web requests - fetching is done by tools/fetch_news.py (scheduled).
  * Never creates / recreates / dedupes-by-deleting the database. Missing DB => clear error.
  * All original URLs keep working (see 'Legacy routes').
"""
import hmac
import logging
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import (Flask, Response, abort, g, jsonify, make_response, redirect, render_template,
                   request, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash
from xml.sax.saxutils import escape

import config
import db
import fetcher
import queries
import utils

app = Flask(__name__)
app.secret_key = config.load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(config.ENVIRONMENT == "production"),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=config.MAX_UPLOAD_BYTES + 512 * 1024,
    SEND_FILE_MAX_AGE_DEFAULT=timedelta(days=7),
    JSON_AS_ASCII=False,
)

# ---------------------------------------------------------------- logging
config.LOG_DIR.mkdir(parents=True, exist_ok=True)
_h = RotatingFileHandler(config.LOG_DIR / "app.log", maxBytes=500_000, backupCount=3)
_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
app.logger.addHandler(_h)
app.logger.setLevel(logging.INFO)

# ---------------------------------------------------------------- database guard
DB_PROBLEM = None
try:
    _c = db.connect()
    try:
        if db.schema_version(_c) < db.SCHEMA_VERSION:
            DB_PROBLEM = "needs_migration"
    finally:
        _c.close()
except db.DatabaseUnavailable as e:
    DB_PROBLEM = "missing"
    app.logger.error("DATABASE MISSING - refusing to create a new one: %s", e)


def get_db():
    if "db" not in g:
        g.db = db.connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    c = g.pop("db", None)
    if c is not None:
        c.close()


# ---------------------------------------------------------------- security helpers
@app.before_request
def guards():
    g.nonce = secrets.token_urlsafe(16)
    if request.endpoint == "static":
        return None
    if DB_PROBLEM:
        return render_template("error.html", code=503, title="Site is being upgraded",
                               message="The database is not ready. The site owner has been notified."), 503
    if request.method == "POST" and request.endpoint != "cron_fetch":
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
            app.logger.warning("CSRF rejected on %s", request.path)
            abort(400)
    return None


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    if request.endpoint != "static":
        n = getattr(g, "nonce", "")
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{n}' https://www.googletagmanager.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https: ; "
            "connect-src 'self' https://www.google-analytics.com https://*.google-analytics.com "
            "https://*.analytics.google.com https://www.googletagmanager.com; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'")
    if request.path.startswith(("/admin", "/login", "/add_news", "/logout")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def static_v(filename):
    p = Path(app.static_folder) / filename
    try:
        v = int(p.stat().st_mtime)
    except OSError:
        v = 0
    return url_for("static", filename=filename, v=v)


@app.context_processor
def inject():
    try:
        cats = queries.cached("cats", 60, lambda: queries.categories(get_db())) if not DB_PROBLEM else []
    except Exception:
        cats = []
    return dict(config=config, csrf_token=csrf_token, nonce=getattr(g, "nonce", ""), nav_cats=cats,
                static_v=static_v, is_admin=bool(session.get("is_admin")), year=datetime.now().year)


@app.template_global()
def pager_qs(base, page):
    from urllib.parse import urlencode
    d = dict(base)
    d["page"] = page
    return urlencode(d)


# ---------------------------------------------------------------- admin auth
_attempts = {}


def client_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    return (xff.split(",")[-1].strip() if xff else request.remote_addr) or "?"


def locked_out(ip):
    now = time.time()
    hits = [t for t in _attempts.get(ip, []) if now - t < config.LOGIN_WINDOW_SECONDS]
    _attempts[ip] = hits
    return len(hits) >= config.LOGIN_MAX_ATTEMPTS


def using_legacy_password():
    return not config.ADMIN_PASSWORD_HASH


def verify_password(pw):
    h = config.ADMIN_PASSWORD_HASH or config.LEGACY_ADMIN_HASH
    try:
        return check_password_hash(h, pw or "")
    except Exception:
        return False


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("is_admin"):
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


def log_admin(conn, action, detail=""):
    conn.execute("INSERT INTO admin_log(at, action, detail) VALUES (?,?,?)",
                 (db.utcnow_iso(), action, str(detail)[:300]))
    conn.commit()


# ================================================================ PUBLIC PAGES
def _home_data(conn):
    return dict(
        hero=queries.cached("hero", 120, lambda: queries.hero_articles(conn, 3)),
        breaking=queries.cached("breaking", 60, lambda: queries.breaking(conn, 3)),
        trending=queries.cached("trending", 300, lambda: queries.trending(conn, 24, 5)),
        most_read=queries.cached("most_read", 600, lambda: queries.most_read(conn, 7, 5)),
        sections=queries.cached("sections", 180, lambda: queries.category_sections(conn, 4)),
    )


@app.route("/")
def home():
    conn = get_db()
    data = _home_data(conn)
    hero_ids = [a["id"] for a in data["hero"]]
    latest, total = queries.list_articles(conn, per_page=12, exclude=hero_ids)
    last = db.get_setting(conn, "last_success_at")
    return render_template("home.html", latest=latest, total=total, hero_ids=hero_ids,
                           last_updated=utils.format_dt(last), **data,
                           title="A.A.News - Latest India Headlines",
                           description="Latest Indian headlines in business, technology, sports, entertainment, "
                                       "health and science, updated through the day.")


@app.route("/fragment/cards")
def fragment_cards():
    """HTML cards for 'load more' on the homepage and for bookmarks/history pages."""
    conn = get_db()
    ids = request.args.get("ids")
    if ids:
        want = [int(x) for x in ids.split(",")[:60] if x.isdigit()]
        items = []
        for i in want:
            a = queries.get_article(conn, i)
            if a:
                items.append(a)
        return render_template("partials/cards.html", items=items)
    exclude = [int(x) for x in request.args.get("exclude", "").split(",") if x.isdigit()][:10]
    items, total = queries.list_articles(
        conn, category=request.args.get("category"), page=request.args.get("page", 1, type=int),
        per_page=12, exclude=exclude)
    resp = make_response(render_template("partials/cards.html", items=items))
    resp.headers["X-Has-More"] = "1" if request.args.get("page", 1, type=int) * 12 < total else "0"
    return resp


@app.route("/section/<slug>")
def section(slug):
    conn = get_db()
    label = queries.category_label(conn, slug)
    if not label:
        abort(404)
    page = max(1, request.args.get("page", 1, type=int))
    items, total = queries.list_articles(conn, category=slug, page=page, per_page=12)
    return render_template("section.html", items=items, total=total, page=page, pages=-(-total // 12),
                           slug=slug, label=label, title=f"{label} News - A.A.News",
                           description=f"Latest {label.lower()} headlines from India on A.A.News.")


@app.route("/search")
def search():
    conn = get_db()
    f = dict(q=(request.args.get("q") or "").strip()[:100], category=request.args.get("category") or "",
             source=request.args.get("source") or "", date_from=request.args.get("from") or "",
             date_to=request.args.get("to") or "", sort=request.args.get("sort") or "new")
    page = max(1, request.args.get("page", 1, type=int))
    popular_ok = queries.has_view_data(conn)
    if f["sort"] not in ("new", "popular", "relevance") or (f["sort"] == "popular" and not popular_ok):
        f["sort"] = "new"
    if f["sort"] == "new" and f["q"] and request.args.get("sort") is None:
        f["sort"] = "relevance" if db.has_fts(conn) else "new"
    items, total = queries.list_articles(conn, category=f["category"], source=f["source"], q=f["q"],
                                         date_from=f["date_from"], date_to=f["date_to"], sort=f["sort"],
                                         page=page, per_page=12)
    pages = -(-total // 12)
    qs = {k: v for k, v in dict(q=f["q"], category=f["category"], source=f["source"], to=f["date_to"],
                                sort=request.args.get("sort") or "", **{"from": f["date_from"]}).items() if v}
    return render_template("search.html", items=items, total=total, page=page, pages=pages, f=f, qs=qs,
                           sources=queries.cached("sources", 300, lambda: queries.sources(conn)),
                           popular_ok=popular_ok, title="Search - A.A.News",
                           description="Search A.A.News headlines by keyword, category, source and date.",
                           noindex=True)


@app.route("/api/suggest")
def api_suggest():
    q = (request.args.get("q") or "").strip()[:60]
    if len(q) < 2:
        return jsonify([])
    return jsonify(queries.suggest(get_db(), q))


def _record_view(conn, article):
    if utils.is_bot(request.headers.get("User-Agent")) or request.headers.get("Purpose") == "prefetch":
        return
    seen = session.get("seen", [])
    if article["id"] in seen:
        return
    conn.execute("INSERT INTO article_views(article_id, viewed_at) VALUES (?,?)", (article["id"], db.utcnow_iso()))
    conn.commit()
    session["seen"] = (seen + [article["id"]])[-40:]


@app.route("/news/<int:article_id>")
@app.route("/news/<int:article_id>/<slug>")
def article(article_id, slug=None):
    conn = get_db()
    preview = bool(session.get("is_admin")) and request.args.get("preview") == "1"
    a = queries.get_article(conn, article_id, include_unpublished=preview)
    if not a:
        abort(404)
    if slug != a["slug"]:
        return redirect(a["href"], 301)
    if not preview:
        _record_view(conn, a)
    rel = queries.related(conn, a, 4)
    cat_label = queries.category_label(conn, a["category"]) if a["category"] else None
    body = utils.paragraphs(a["content"]) if a["content"] else []
    text = " ".join(body) or (a.get("description") or "")
    indexable = (a["is_own"] or config.INDEX_AGGREGATED) and a["status"] != "draft" and not preview
    return render_template(
        "article.html", a=a, related=rel, cat_label=cat_label, body=body, minutes=utils.reading_minutes(text),
        indexable=indexable, title=f"{a['title']} - A.A.News",
        description=(a.get("description") or (body[0] if body else a["title"]))[:180],
        og_image=a["img"], noindex=not indexable, og_type="article")


# ---------------- static-ish pages
def _static_page(tpl, title, desc):
    return render_template(tpl, title=title, description=desc)


@app.route("/about")
def about():
    return _static_page("about.html", "About Us - A.A.News", "About A.A.News, our mission and editorial approach.")


@app.route("/privacy-policy")
def privacy_policy():
    return _static_page("privacy.html", "Privacy Policy - A.A.News", "How A.A.News handles data and cookies.")


@app.route("/terms")
def terms():
    return _static_page("terms.html", "Terms of Use - A.A.News", "Terms of use for A.A.News.")


@app.route("/contact")
def contact():
    return _static_page("contact.html", "Contact - A.A.News", "How to contact the A.A.News team.")


@app.route("/saved")
def saved():
    return render_template("saved.html", title="Saved articles - A.A.News", mode="saved", noindex=True,
                           description="Articles you saved for later.")


@app.route("/history")
def history():
    return render_template("saved.html", title="Reading history - A.A.News", mode="history", noindex=True,
                           description="Articles you recently read.")


@app.route("/offline")
def offline():
    return render_template("offline.html", title="Offline - A.A.News", noindex=True, description="You are offline.")


# ---------------- Legacy routes (kept so old links / the old frontend keep working)
@app.route("/read/<int:news_id>")
def read_news(news_id):
    a = queries.get_article(get_db(), news_id)
    if not a:
        abort(404)
    return redirect(a["href"], 301)


def _legacy_json(rows):
    return jsonify([{"id": a["id"], "title": a["title"], "source": {"name": a["source"]},
                     "urlToImage": a["image_url"], "url": a["url"]} for a in rows])


@app.route("/get_news")
def get_news():
    limit = min(max(request.args.get("limit", 20, type=int), 1), 100)
    offset = max(request.args.get("offset", 0, type=int), 0)
    items, _ = queries.list_articles(get_db(), category="all_only", page=offset // limit + 1, per_page=limit)
    return _legacy_json(items)


@app.route("/category/<cat_name>")
def get_category_news(cat_name):
    limit = min(max(request.args.get("limit", 20, type=int), 1), 100)
    offset = max(request.args.get("offset", 0, type=int), 0)
    items, _ = queries.list_articles(get_db(), category=cat_name, page=offset // limit + 1, per_page=limit)
    return _legacy_json(items)


@app.route("/get_categories")
def get_categories():
    return jsonify(queries.categories(get_db()))


# ---------------- SEO / PWA
@app.route("/robots.txt")
def robots():
    body = (f"User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /login\nDisallow: /add_news\n"
            f"Disallow: /logout\nDisallow: /search\nDisallow: /api/\nDisallow: /fragment/\n"
            f"Sitemap: {config.SITE_URL}/sitemap.xml\n")
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    conn = get_db()
    urls = [(f"{config.SITE_URL}/", None)]
    urls += [(f"{config.SITE_URL}/section/{c['slug']}", None) for c in queries.categories(conn) if c["slug"] != "all"]
    urls += [(f"{config.SITE_URL}{p}", None) for p in ("/about", "/privacy-policy", "/terms", "/contact")]
    cond = "" if config.INDEX_AGGREGATED else " AND (n.url IS NULL OR n.url='')"
    rows = conn.execute(
        f"SELECT n.id, n.title, COALESCE(n.updated_at, n.published_at, n.created_at) lm FROM news n "
        f"WHERE {queries.PUB}{cond} ORDER BY n.id DESC LIMIT 5000", (db.utcnow_iso(),)).fetchall()
    for r in rows:
        urls.append((f"{config.SITE_URL}/news/{r['id']}/{utils.slugify(r['title'])}", r["lm"]))
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u, lm in urls:
        out.append(f"<url><loc>{escape(u)}</loc>" + (f"<lastmod>{lm}</lastmod>" if lm else "") + "</url>")
    out.append("</urlset>")
    return Response("\n".join(out), mimetype="application/xml")


@app.route("/manifest.webmanifest")
def manifest():
    resp = send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/sw.js")
def service_worker():
    resp = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache, max-age=0"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "icons/favicon.ico", mimetype="image/x-icon")


# ================================================================ ADMIN
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        ip = client_ip()
        if locked_out(ip):
            error = "Too many attempts. Please wait 15 minutes and try again."
        elif verify_password(request.form.get("password")):
            session.clear()
            session["is_admin"] = True
            session.permanent = True
            _attempts.pop(ip, None)
            log_admin(get_db(), "login", "")
            return redirect(url_for("add_news"))
        else:
            _attempts.setdefault(ip, []).append(time.time())
            app.logger.warning("failed admin login from %s", ip)
            error = "Wrong password! Please try again."
    return render_template("admin/login.html", error=error, title="Admin login", noindex=True, description="")


@app.route("/logout")
def logout():
    session.pop("is_admin", None)
    return redirect(url_for("home"))


from admin_tools import (UploadError, dashboard_data, parse_local_dt, save_upload,  # noqa: E402
                         to_local_input)


def _form_article(form, files, existing=None):
    """Validate and normalise an article form. Returns (values, error)."""
    title = (form.get("title") or "").strip()
    content = (form.get("content") or "").strip()
    if not title or not content:
        return None, "News title and detailed content are mandatory!"
    image = (form.get("image_url") or "").strip()
    up = files.get("image_file")
    if up and up.filename:
        try:
            image = save_upload(up)
        except UploadError as e:
            return None, str(e)
    if image and not (image.startswith(("http://", "https://", "/static/uploads/"))):
        return None, "Image URL must start with http(s)://"
    if not image:
        image = (existing or {}).get("image_url") or "https://dummyimage.com/600x300/131921/ff9d00.png&text=A.A.News"
    status = "draft" if form.get("status") == "draft" else "published"
    publish_at = parse_local_dt(form.get("publish_at"))
    return dict(title=title[:300], source=(form.get("source") or "").strip()[:100] or "A.A.News Exclusive",
                image_url=image, content=content, category=(form.get("category") or "all"),
                description=(form.get("description") or "").strip()[:400] or None,
                author=(form.get("author") or "").strip()[:100] or None, status=status, publish_at=publish_at,
                is_featured=1 if form.get("is_featured") else 0,
                is_breaking=1 if form.get("is_breaking") else 0), None


@app.route("/add_news", methods=["GET", "POST"])
@admin_required
def add_news():
    conn = get_db()
    message = ""
    if request.method == "POST":
        v, err = _form_article(request.form, request.files)
        if err:
            message = err
        else:
            now = db.utcnow_iso()
            try:
                cur = conn.execute(
                    "INSERT INTO news (title, source, image_url, url, category, content, description, author, status, "
                    "publish_at, is_featured, is_breaking, created_at, published_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (v["title"], v["source"], v["image_url"], "", v["category"], v["content"], v["description"],
                     v["author"], v["status"], v["publish_at"], v["is_featured"], v["is_breaking"], now,
                     v["publish_at"] or now))
                conn.commit()
                log_admin(conn, "create_article", f"id={cur.lastrowid}")
                queries.clear_cache()
                message = ("Saved as draft." if v["status"] == "draft"
                           else "The news has been successfully published on the website!")
            except sqlite3.IntegrityError:
                message = "A news item with this exact title already exists. Please change the title slightly."
    return render_template("admin/add_news.html", message=message, categories=queries.categories(conn),
                           title="Add news", noindex=True, description="")


@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = get_db()
    d = dashboard_data(conn)
    return render_template("admin/dashboard.html", categories=queries.categories(conn), legacy_pw=using_legacy_password(),
                           title="Admin dashboard", noindex=True, description="", **d)


@app.route("/admin/edit/<int:news_id>", methods=["GET", "POST"])
@admin_required
def edit_news(news_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM news WHERE id=?", (news_id,)).fetchone()
    if not row:
        abort(404)
    cur = dict(row)
    error = None
    if request.method == "POST":
        v, error = _form_article(request.form, request.files, cur)
        if not error:
            try:
                conn.execute(
                    "UPDATE news SET title=?, source=?, image_url=?, content=?, category=?, description=?, author=?, "
                    "status=?, publish_at=?, is_featured=?, is_breaking=?, updated_at=? WHERE id=?",
                    (v["title"], v["source"], v["image_url"], v["content"], v["category"], v["description"], v["author"],
                     v["status"], v["publish_at"], v["is_featured"], v["is_breaking"], db.utcnow_iso(), news_id))
                conn.commit()
                log_admin(conn, "edit_article", f"id={news_id}")
                queries.clear_cache()
                return redirect(url_for("admin_dashboard"))
            except sqlite3.IntegrityError:
                error = "A news item with this exact title already exists. Please change the title slightly."
        cur.update(request.form.to_dict())
    cur["publish_at_local"] = to_local_input(cur.get("publish_at"))
    return render_template("admin/edit_news.html", news=cur, error=error, categories=queries.categories(conn),
                           title="Edit news", noindex=True, description="")


@app.route("/admin/delete/<int:news_id>", methods=["POST"])
@admin_required
def delete_news(news_id):
    conn = get_db()
    conn.execute("DELETE FROM news WHERE id=?", (news_id,))
    conn.commit()
    log_admin(conn, "delete_article", f"id={news_id}")
    queries.clear_cache()
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/toggle/<int:news_id>/<flag>", methods=["POST"])
@admin_required
def toggle_flag(news_id, flag):
    if flag not in ("is_featured", "is_breaking"):
        abort(400)
    conn = get_db()
    conn.execute(f"UPDATE news SET {flag} = 1 - {flag}, updated_at=? WHERE id=?", (db.utcnow_iso(), news_id))
    conn.commit()
    log_admin(conn, "toggle_" + flag, f"id={news_id}")
    queries.clear_cache()
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/admin/add_category", methods=["POST"])
@admin_required
def add_category():
    label = (request.form.get("label") or "").strip()[:40]
    if label:
        slug = utils.slugify(label, 40)
        conn = get_db()
        try:
            conn.execute("INSERT INTO categories (slug, label) VALUES (?, ?)", (slug, label))
            conn.commit()
            log_admin(conn, "add_category", slug)
            queries.clear_cache()
        except sqlite3.IntegrityError:
            pass
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete_category/<slug>", methods=["POST"])
@admin_required
def delete_category(slug):
    if slug != "all":  # same rule as the original; its news moves to 'all', nothing is lost
        conn = get_db()
        conn.execute("UPDATE news SET category='all' WHERE category=?", (slug,))
        conn.execute("DELETE FROM categories WHERE slug=?", (slug,))
        conn.commit()
        log_admin(conn, "delete_category", slug)
        queries.clear_cache()
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/fetch_now", methods=["POST"])
@admin_required
def fetch_now():
    conn = get_db()
    last = float(db.get_setting(conn, "manual_fetch_ts", "0") or 0)
    wait = int(config.MANUAL_FETCH_COOLDOWN - (time.time() - last))
    if wait > 0:
        session["flash"] = f"Please wait {wait}s before fetching again."
        return redirect(url_for("admin_dashboard"))
    db.set_setting(conn, "manual_fetch_ts", time.time())
    conn.commit()
    if not config.NEWSDATA_API_KEY:
        session["flash"] = "NEWSDATA_API_KEY is not configured on the server."
        return redirect(url_for("admin_dashboard"))
    s = fetcher.run("manual")
    log_admin(conn, "fetch_now", f"{s['status']} new={s['new_saved']}")
    queries.clear_cache()
    session["flash"] = (f"Fetch {s['status']}: {s['new_saved']} new, {s['duplicates']} duplicates skipped."
                        + (" See error log below." if s["error"] else ""))
    return redirect(url_for("admin_dashboard"))


@app.route("/cron/fetch", methods=["POST"])
def cron_fetch():
    """OPTIONAL. Disabled unless FETCH_CRON_TOKEN is set. For an external scheduler (cron-job.org,
    GitHub Actions) when PythonAnywhere Scheduled Tasks are not available on your plan."""
    token = config.env("FETCH_CRON_TOKEN")
    given = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    if not token or len(token) < 20 or not hmac.compare_digest(given, token):
        abort(404)
    conn = get_db()
    last = float(db.get_setting(conn, "cron_fetch_ts", "0") or 0)
    if time.time() - last < 20 * 60:
        return jsonify(status="skipped", reason="ran recently"), 429
    db.set_setting(conn, "cron_fetch_ts", time.time())
    conn.commit()
    s = fetcher.run("scheduled")
    queries.clear_cache()
    return jsonify({k: s[k] for k in ("status", "new_saved", "duplicates", "api_calls")})


# ================================================================ errors
@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, title="Page not found",
                           message="We couldn't find that page. It may have moved or been removed."), 404


@app.errorhandler(400)
def bad_request(_e):
    return render_template("error.html", code=400, title="Request not accepted",
                           message="Your request could not be verified. Please go back, refresh and try again."), 400


@app.errorhandler(413)
def too_large(_e):
    return render_template("error.html", code=413, title="File too large",
                           message="That upload is too large."), 413


@app.errorhandler(Exception)
def server_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return render_template("error.html", code=e.code, title=e.name, message=e.description), e.code
    app.logger.exception("unhandled error on %s", request.path)
    return render_template("error.html", code=500, title="Something went wrong",
                           message="An unexpected error occurred. Please try again shortly."), 500


if __name__ == "__main__":
    app.run(debug=(config.ENVIRONMENT == "development"))
