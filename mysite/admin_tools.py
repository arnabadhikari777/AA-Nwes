"""Admin helpers: upload validation, date parsing, dashboard statistics."""
import io
import secrets
from datetime import datetime, timedelta, timezone

import config
import db
import utils


class UploadError(ValueError):
    pass


def save_upload(fs):
    """Validate with Pillow, re-encode (strips any embedded payload), random file name."""
    from PIL import Image, UnidentifiedImageError
    raw = fs.read(config.MAX_UPLOAD_BYTES + 1)
    if len(raw) > config.MAX_UPLOAD_BYTES:
        raise UploadError("Image is too large (max 3 MB).")
    try:
        img = Image.open(io.BytesIO(raw))
        fmt = (img.format or "").upper()
        if fmt not in ("JPEG", "PNG", "WEBP"):
            raise UploadError("Only JPEG, PNG or WebP images are allowed.")
        img.load()
    except UnidentifiedImageError:
        raise UploadError("That file is not a valid image.")
    except UploadError:
        raise
    except Exception:
        raise UploadError("That image could not be processed.")
    if img.width * img.height > 40_000_000:
        raise UploadError("Image dimensions are too large.")
    img.thumbnail((1600, 1600))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(8)}.webp"
    img.save(config.UPLOAD_DIR / name, "WEBP", quality=82)
    return f"/static/uploads/{name}"


def parse_local_dt(value):
    """<input type=datetime-local> (display tz) -> UTC ISO, or None."""
    if not value:
        return None
    try:
        d = datetime.strptime(value, "%Y-%m-%dT%H:%M").replace(tzinfo=utils.TZ)
    except ValueError:
        return None
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_local_input(iso):
    d = utils.parse_iso(iso)
    return d.astimezone(utils.TZ).strftime("%Y-%m-%dT%H:%M") if d else ""


def dashboard_data(conn):
    now = db.utcnow_iso()
    one = lambda sql, *p: conn.execute(sql, p).fetchone()[0]
    d7 = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stats = dict(
        total=one("SELECT COUNT(*) FROM news"),
        drafts=one("SELECT COUNT(*) FROM news WHERE status='draft'"),
        scheduled=one("SELECT COUNT(*) FROM news WHERE status!='draft' AND publish_at>?", now),
        own=one("SELECT COUNT(*) FROM news WHERE url IS NULL OR url=''"),
        featured=one("SELECT COUNT(*) FROM news WHERE is_featured=1"),
        breaking=one("SELECT COUNT(*) FROM news WHERE is_breaking=1"),
        views7=one("SELECT COUNT(*) FROM article_views WHERE viewed_at>=?", d7),
    )
    items = [dict(r) for r in conn.execute(
        "SELECT id, title, source, category, status, publish_at, is_featured, is_breaking, "
        "(url IS NULL OR url='') AS own FROM news ORDER BY id DESC LIMIT 200")]
    for i in items:
        i["scheduled"] = bool(i["publish_at"] and i["publish_at"] > now and i["status"] != "draft")
        i["slug"] = utils.slugify(i["title"])
    top = [dict(r) for r in conn.execute(
        "SELECT n.id, n.title, COUNT(v.id) views FROM article_views v JOIN news n ON n.id=v.article_id "
        "WHERE v.viewed_at>=? GROUP BY n.id ORDER BY views DESC LIMIT 8", (d7,))]
    last_run = conn.execute("SELECT * FROM fetch_runs WHERE status!='running' ORDER BY id DESC LIMIT 1").fetchone()
    runs = [dict(r) for r in conn.execute("SELECT * FROM fetch_runs ORDER BY id DESC LIMIT 10")]
    errors = [dict(r) for r in conn.execute(
        "SELECT started_at, trigger, error FROM fetch_runs WHERE error IS NOT NULL ORDER BY id DESC LIMIT 8")]
    log = [dict(r) for r in conn.execute("SELECT at, action, detail FROM admin_log ORDER BY id DESC LIMIT 15")]
    return dict(stats=stats, items=items, top=top, last_run=dict(last_run) if last_run else None, runs=runs,
                errors=errors, admin_log=log, last_success=db.get_setting(conn, "last_success_at"),
                api_calls_today=db.get_setting(conn, "api_calls_today", ""))
