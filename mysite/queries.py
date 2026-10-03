"""All read queries. Everything is parameterised and filtered in SQL, never in Python."""
import time
from datetime import datetime, timedelta, timezone

import config
import db
import utils

COLS = ("n.id, n.title, n.source, n.image_url, n.url, n.category, n.content, n.description, "
        "n.author, n.published_at, n.created_at, n.publish_at, n.updated_at, n.status, "
        "n.is_featured, n.is_breaking")
PUB = "(n.status IS NULL OR n.status='published') AND (n.publish_at IS NULL OR n.publish_at<=?)"

_cache = {}


def cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def clear_cache():
    _cache.clear()


def to_article(row):
    a = dict(row)
    a["is_own"] = not (a.get("url") or "").strip()          # written in the admin panel
    a["display_source"] = utils.pretty_source(a.get("source"))
    a["slug"] = utils.slugify(a.get("title"))
    a["href"] = f"/news/{a['id']}/{a['slug']}"
    when = a.get("published_at") or a.get("created_at")
    a["date_label"] = utils.format_dt(when)
    a["date_iso"] = when
    a["img"] = utils.https_url(a.get("image_url")) or None
    return a


def _now():
    return db.utcnow_iso()


def list_articles(conn, category=None, source=None, q=None, date_from=None, date_to=None,
                  sort="new", page=1, per_page=12, exclude=()):
    where, params, joins = [PUB], [_now()], ""
    q = (q or "").strip()
    fts_q = utils.build_fts_query(q) if q else None
    use_fts = bool(fts_q) and db.has_fts(conn)
    if q:
        if use_fts:
            joins += " JOIN news_fts ON news_fts.rowid = n.id"
            where.append("news_fts MATCH ?")
            params.append(fts_q)
        else:
            like = f"%{utils.like_escape(q)}%"
            where.append("(n.title LIKE ? ESCAPE '\\' OR n.description LIKE ? ESCAPE '\\' "
                         "OR n.content LIKE ? ESCAPE '\\')")
            params += [like, like, like]
    if category == "all_only":          # legacy /get_news: exactly the original 'all' feed
        where.append("n.category='all'")
    elif category and category != "all":
        where.append("n.category=?")
        params.append(category)
    if source:
        where.append("n.source=?")
        params.append(source)
    start = utils.ist_day_to_utc(date_from)
    end = utils.ist_day_to_utc(date_to, end=True)
    if start:
        where.append("COALESCE(n.published_at, n.created_at) >= ?")
        params.append(start)
    if end:
        where.append("COALESCE(n.published_at, n.created_at) <= ?")
        params.append(end)
    if exclude:
        where.append("n.id NOT IN (%s)" % ",".join("?" * len(exclude)))
        params += list(exclude)

    if sort == "popular":
        since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        joins += (" LEFT JOIN (SELECT article_id, COUNT(*) c FROM article_views "
                  "WHERE viewed_at>=? GROUP BY article_id) v ON v.article_id=n.id")
        order = "ORDER BY COALESCE(v.c,0) DESC, n.id DESC"
        # join params come first in SQL text order -> prepend
        join_params = [since]
    elif sort == "relevance" and use_fts:
        order = "ORDER BY bm25(news_fts), n.id DESC"
        join_params = []
    else:
        order = "ORDER BY n.id DESC"
        join_params = []

    where_sql = " WHERE " + " AND ".join(where)
    # Placeholders appear in SQL order: joins (popular subquery) then WHERE.
    all_params = join_params + params
    total = conn.execute(f"SELECT COUNT(*) FROM news n{joins}{where_sql}", all_params).fetchone()[0]
    page = max(1, page)
    rows = conn.execute(
        f"SELECT {COLS} FROM news n{joins}{where_sql} {order} LIMIT ? OFFSET ?",
        all_params + [per_page, (page - 1) * per_page],
    ).fetchall()
    return [to_article(r) for r in rows], total


def get_article(conn, article_id, include_unpublished=False):
    sql = f"SELECT {COLS} FROM news n WHERE n.id=?"
    params = [article_id]
    if not include_unpublished:
        sql += " AND " + PUB
        params.append(_now())
    row = conn.execute(sql, params).fetchone()
    return to_article(row) if row else None


def hero_articles(conn, n=3):
    rows = conn.execute(
        f"SELECT {COLS} FROM news n WHERE n.is_featured=1 AND {PUB} ORDER BY n.id DESC LIMIT ?",
        (_now(), n),
    ).fetchall()
    out = [to_article(r) for r in rows]
    for a in out:
        a["featured"] = True
    if len(out) < n:
        have = [a["id"] for a in out]
        ph = ",".join("?" * len(have)) or "0"
        more = conn.execute(
            f"SELECT {COLS} FROM news n WHERE n.image_url IS NOT NULL AND n.image_url!='' "
            f"AND n.id NOT IN ({ph}) AND {PUB} ORDER BY n.id DESC LIMIT ?",
            (*have, _now(), n - len(out)),
        ).fetchall()
        out += [to_article(r) for r in more]
    return out


def breaking(conn, n=3):
    rows = conn.execute(
        f"SELECT {COLS} FROM news n WHERE n.is_breaking=1 AND {PUB} ORDER BY n.id DESC LIMIT ?",
        (_now(), n),
    ).fetchall()
    return [to_article(r) for r in rows]


def _popular(conn, since, limit):
    rows = conn.execute(
        f"SELECT {COLS}, COUNT(v.id) AS views FROM article_views v JOIN news n ON n.id=v.article_id "
        f"WHERE v.viewed_at>=? AND {PUB} GROUP BY n.id ORDER BY views DESC, n.id DESC LIMIT ?",
        (since, _now(), limit),
    ).fetchall()
    out = []
    for r in rows:
        a = to_article(r)
        a["views"] = r["views"]
        out.append(a)
    return out


def trending(conn, hours=24, limit=5):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _popular(conn, since, limit)


def most_read(conn, days=7, limit=5):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _popular(conn, since, limit)


def categories(conn):
    return [dict(r) for r in conn.execute("SELECT slug, label FROM categories ORDER BY id ASC")]


def category_label(conn, slug):
    for c in categories(conn):
        if c["slug"] == slug:
            return c["label"]
    return None


def sources(conn, limit=60):
    rows = conn.execute(
        f"SELECT n.source, COUNT(*) c FROM news n WHERE n.source IS NOT NULL AND n.source!='' "
        f"AND {PUB} GROUP BY n.source ORDER BY c DESC, n.source LIMIT ?", (_now(), limit)).fetchall()
    return [{"value": r["source"], "label": utils.pretty_source(r["source"]), "count": r["c"]} for r in rows]


def has_view_data(conn):
    return conn.execute("SELECT 1 FROM article_views LIMIT 1").fetchone() is not None


def category_sections(conn, per=4):
    out = []
    for c in categories(conn):
        if c["slug"] == "all":
            continue
        items, total = list_articles(conn, category=c["slug"], per_page=per)
        if items:
            out.append({"slug": c["slug"], "label": c["label"], "items": items, "total": total})
    return out


def related(conn, article, limit=4):
    words = set(utils.build_words(article["title"]))
    rows = conn.execute(
        f"SELECT {COLS} FROM news n WHERE n.id!=? AND (n.category=? OR n.source=?) AND {PUB} "
        f"ORDER BY n.id DESC LIMIT 150", (article["id"], article["category"], article["source"], _now())
    ).fetchall()
    scored = []
    for r in rows:
        a = to_article(r)
        score = (2 if a["category"] == article["category"] and article["category"] != "all" else 0)
        score += (1 if a["source"] == article["source"] else 0)
        score += 2 * len(words & set(utils.build_words(a["title"])))
        scored.append((score, a["id"], a))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    picks = [a for s, _, a in scored[:limit]]
    if len(picks) < limit:  # top up with the newest other stories
        have = {a["id"] for a in picks} | {article["id"]}
        extra, _ = list_articles(conn, per_page=limit + len(have))
        picks += [a for a in extra if a["id"] not in have][: limit - len(picks)]
    return picks


def suggest(conn, q, limit=6):
    items, _ = list_articles(conn, q=q, per_page=limit)
    return [{"title": a["title"], "href": a["href"]} for a in items]
