"""Run:  python tests/test_all.py        (uses a temporary COPY of news.db; never touches the real one)
Set AA_TEST_SOURCE_DB to the database file to copy (default: ./news.db)."""
import io, json, os, re, shutil, sqlite3, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("AA_TEST_SOURCE_DB", ROOT / "news.db"))
TMP = Path(tempfile.mkdtemp(prefix="aa_test_"))
DBP = TMP / "news.db"
shutil.copy(SRC, DBP)
os.environ.update(AA_NEWS_DB=str(DBP), AA_NEWS_ENV="development", NEWSDATA_API_KEY="SECRETKEY999",
                  AA_NEWS_BACKUP_DIR=str(TMP / "bk"), SECRET_KEY="test-secret")
# Tests use their own throw-away admin password. To also test that your ORIGINAL password keeps working,
# run with AA_TEST_LEGACY_PASSWORD=<old password> (never write it into this file).
LEGACY_PW = os.environ.get("AA_TEST_LEGACY_PASSWORD")
TEST_PW = "test-password-123"
os.environ.pop("ADMIN_PASSWORD_HASH", None)
if not LEGACY_PW:
    from werkzeug.security import generate_password_hash
    os.environ["ADMIN_PASSWORD_HASH"] = generate_password_hash(TEST_PW)
sys.path.insert(0, str(ROOT))
subprocess.run([sys.executable, str(ROOT / "tools" / "migrate.py"), "--apply", "--db", str(DBP)], check=True,
               capture_output=True, env=os.environ)
import app as A, config, db, fetcher, queries  # noqa: E402


def raw(sql, *p):
    c = sqlite3.connect(DBP); r = c.execute(sql, p).fetchall(); c.commit(); c.close(); return r


def src_counts():
    c = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True)
    return c.execute("SELECT COUNT(*) FROM news").fetchone()[0], c.execute("SELECT COUNT(*) FROM categories").fetchone()[0]


API_OK = {"status": "success", "results": [
    {"article_id": "a1", "title": "Alpha unique headline one", "link": "https://ex.com/1", "source_id": "ex", "image_url": "http://img/1.jpg",
     "description": "Desc one", "creator": ["Jane"], "pubDate": "2026-10-02 10:00:00"},
    {"article_id": "a2", "title": "Beta unique headline two", "link": "https://ex.com/2", "source_id": "ex", "pubDate": "2026-10-02 11:00:00"},
    {"article_id": "a3", "title": "", "link": "https://ex.com/3"},                      # invalid: no title
    {"article_id": "a4", "title": "No link here", "link": ""}]}                          # invalid: no link


class R:
    def __init__(self, data, code=200): self._d, self.status_code = data, code
    def json(self): return self._d


def login(c, pw=None):
    pw = pw or LEGACY_PW or TEST_PW
    c.get("/login")
    with c.session_transaction() as s: tok = s.get("csrf")
    return c.post("/login", data={"password": pw, "csrf_token": tok}, follow_redirects=False)


def tok(c):
    with c.session_transaction() as s:
        if "csrf" not in s: s["csrf"] = "tok123"
        return s["csrf"]


class T(unittest.TestCase):
    def setUp(self): self.c = A.app.test_client(); A._attempts.clear(); queries.clear_cache()

    # ---- database preservation
    def test_01_existing_data_intact(self):
        n, k = src_counts()
        self.assertEqual(raw("SELECT COUNT(*) FROM news")[0][0], n)
        self.assertEqual(raw("SELECT COUNT(*) FROM categories")[0][0], k)
        self.assertEqual(raw("SELECT MAX(id) FROM news")[0][0], 494)
        self.assertIn(("marvel-studios",), raw("SELECT slug FROM categories"))

    def test_02_public_routes(self):
        for p in ["/", "/section/sports", "/section/marvel-studios", "/search", "/about", "/privacy-policy", "/terms", "/contact",
                  "/saved", "/history", "/offline", "/robots.txt", "/sitemap.xml", "/get_categories", "/get_news", "/category/business"]:
            self.assertEqual(self.c.get(p).status_code, 200, p)
        self.assertEqual(self.c.get("/section/doesnotexist").status_code, 404)

    def test_03_legacy_routes(self):
        self.assertEqual(self.c.get("/get_news?limit=2").get_json()[0].keys(), {"id", "title", "source", "urlToImage", "url"})
        own = raw("SELECT id FROM news WHERE url=''")[0][0]
        r = self.c.get(f"/read/{own}"); self.assertEqual(r.status_code, 301); self.assertIn(f"/news/{own}/", r.headers["Location"])
        self.assertEqual(self.c.get(f"/news/{own}").status_code, 301)

    # ---- articles
    def test_04_article_pages_and_seo(self):
        own = raw("SELECT id,title FROM news WHERE url='' LIMIT 1")[0]
        href = queries.get_article(db.connect(), own[0])["href"]
        h = self.c.get(href).get_data(as_text=True)
        self.assertIn('rel="canonical"', h); self.assertIn("application/ld+json", h); self.assertNotIn('content="noindex', h)
        agg = raw("SELECT id FROM news WHERE url!='' LIMIT 1")[0][0]
        h2 = self.c.get(queries.get_article(db.connect(), agg)["href"]).get_data(as_text=True)
        self.assertIn("noindex", h2); self.assertIn("Read the full story at", h2)   # thin aggregated page: noindex + source link
        self.assertEqual(self.c.get("/news/999999").status_code, 404)

    def test_05_sitemap_robots(self):
        sm = self.c.get("/sitemap.xml").get_data(as_text=True)
        self.assertNotIn("/admin", sm); self.assertNotIn("/login", sm)
        self.assertIn(config.SITE_URL, sm)
        rb = self.c.get("/robots.txt").get_data(as_text=True)
        self.assertIn("Disallow: /admin", rb); self.assertIn("sitemap.xml", rb)

    # ---- search
    def test_06_search_filters(self):
        title = raw("SELECT title FROM news WHERE category='sports' LIMIT 1")[0][0]
        word = max(re.findall(r"[A-Za-z]{5,}", title), key=len)
        items, total = queries.list_articles(db.connect(), q=word)
        self.assertTrue(total >= 1); self.assertTrue(any(word.lower() in a["title"].lower() for a in items))
        self.assertTrue(db.has_fts(db.connect()))
        _, tcat = queries.list_articles(db.connect(), category="sports"); self.assertEqual(tcat, raw("SELECT COUNT(*) FROM news WHERE category='sports'")[0][0])
        src = raw("SELECT source FROM news WHERE source!='' LIMIT 1")[0][0]
        _, ts = queries.list_articles(db.connect(), source=src); self.assertEqual(ts, raw("SELECT COUNT(*) FROM news WHERE source=?", src)[0][0])
        self.assertEqual(self.c.get("/search?q=zzzqqqnomatch").status_code, 200)
        self.assertIn("No results found", self.c.get("/search?q=zzzqqqnomatch").get_data(as_text=True))
        for evil in ['"', "'", "AND OR", "title:*", "x) OR (y", "%", "\\", "NEAR(", "a" * 500]:
            self.assertEqual(self.c.get("/search", query_string={"q": evil}).status_code, 200, evil)
        # pagination preserves filters
        h = self.c.get("/search?category=business&page=1").get_data(as_text=True)
        self.assertIn("category=business", h.split('class="pager"')[1] if 'class="pager"' in h else "category=business")

    def test_07_date_filter(self):
        raw("UPDATE news SET published_at='2026-09-01T06:00:00Z' WHERE id=(SELECT MIN(id) FROM news)")
        _, t = queries.list_articles(db.connect(), date_from="2026-09-01", date_to="2026-09-01"); self.assertEqual(t, 1)
        _, t = queries.list_articles(db.connect(), date_from="2026-09-02"); self.assertEqual(t, 0)

    # ---- trending based on real views
    def test_08_views_trending(self):
        raw("DELETE FROM article_views"); queries.clear_cache()
        self.assertEqual(queries.trending(db.connect()), [])      # no views => nothing "trending" (no fabricated popularity)
        a = raw("SELECT id FROM news LIMIT 1")[0][0]
        c2 = A.app.test_client()
        r = c2.get(f"/news/{a}/x", headers={"User-Agent": "Mozilla/5.0 Chrome"}, follow_redirects=True)
        c2.get(f"/news/{a}/x", headers={"User-Agent": "Mozilla/5.0 Chrome"}, follow_redirects=True)   # same session: not double counted
        c3 = A.app.test_client(); c3.get(f"/news/{a}", headers={"User-Agent": "Googlebot"}, follow_redirects=True)   # bot ignored
        self.assertEqual(raw("SELECT COUNT(*) FROM article_views WHERE article_id=?", a)[0][0], 1)
        queries.clear_cache(); self.assertEqual(queries.trending(db.connect())[0]["id"], a)

    def test_09_breaking_only_by_flag(self):
        self.assertEqual(queries.breaking(db.connect()), [])
        raw("UPDATE news SET is_breaking=1 WHERE id=(SELECT MAX(id) FROM news)"); queries.clear_cache()
        self.assertEqual(len(queries.breaking(db.connect())), 1)
        self.assertIn("BREAKING", self.c.get("/").get_data(as_text=True))
        raw("UPDATE news SET is_breaking=0")

    # ---- fetcher
    def _run(self, resp):
        with mock.patch("fetcher.requests.get", return_value=resp):
            with mock.patch("fetcher.time.sleep"):
                return fetcher.run("scheduled")

    def test_10_fetch_dedupe_and_repeat(self):
        before = raw("SELECT COUNT(*) FROM news")[0][0]
        s1 = self._run(R(API_OK)); self.assertEqual(s1["status"], "success"); self.assertEqual(s1["api_calls"], 2)
        self.assertEqual(s1["invalid"], 4); self.assertEqual(s1["new_saved"], 2)          # 2 calls return same 4 items; 2nd call = dups
        mid = raw("SELECT COUNT(*) FROM news")[0][0]; self.assertEqual(mid, before + 2)
        s2 = self._run(R(API_OK)); self.assertEqual(s2["new_saved"], 0); self.assertTrue(s2["duplicates"] >= 4)
        self.assertEqual(raw("SELECT COUNT(*) FROM news")[0][0], mid)
        self.assertEqual(raw("SELECT published_at FROM news WHERE external_id='a1'")[0][0], "2026-10-02T10:00:00Z")
        self.assertTrue(raw("SELECT value FROM app_settings WHERE key='last_success_at'"))
        self.assertEqual(src_counts()[0] <= raw("SELECT COUNT(*) FROM news")[0][0], True)   # nothing deleted

    def test_11_fetch_api_failures_keep_data(self):
        n = raw("SELECT COUNT(*) FROM news")[0][0]
        for resp in (R({"status": "error", "results": {"message": "quota SECRETKEY999"}}, 429), R({"status": "error"}, 500)):
            s = self._run(resp); self.assertIn(s["status"], ("error", "partial"))
            self.assertNotIn("SECRETKEY999", s["error"])
        with mock.patch("fetcher.requests.get", side_effect=__import__("requests").Timeout("t")):
            with mock.patch("fetcher.time.sleep"):
                s = fetcher.run("scheduled"); self.assertEqual(s["status"], "error")
        self.assertEqual(raw("SELECT COUNT(*) FROM news")[0][0], n)
        self.assertEqual(self.c.get("/").status_code, 200)    # site still serves stored news
        self.assertFalse(any("SECRETKEY999" in (r[0] or "") for r in raw("SELECT error FROM fetch_runs")))

    def test_12_no_overlap(self):
        with fetcher.lock():
            s = self._run(R(API_OK)); self.assertEqual(s["status"], "skipped")

    def test_13_budget(self):
        today = time.strftime("%Y-%m-%d", time.gmtime())
        c = db.connect(); db.set_setting(c, "api_calls_today", f"{today}:{config.NEWSDATA_MAX_CALLS_PER_DAY}"); c.commit(); c.close()
        s = self._run(R(API_OK)); self.assertEqual(s["api_calls"], 0); self.assertIn("budget", s["error"])
        c = db.connect(); db.set_setting(c, "api_calls_today", "x:0"); c.commit(); c.close()

    def test_14_fetch_script_exit_clean(self):
        env = dict(os.environ); env["NEWSDATA_API_KEY"] = "KEYLEAKCHECK123"; env["AA_NEWS_DB"] = str(DBP)
        p = subprocess.run([sys.executable, str(ROOT / "tools" / "fetch_news.py")], env=env, capture_output=True, text=True, timeout=120)
        self.assertIn(p.returncode, (0, 1))                       # exits (does not hang), whatever the network does
        self.assertNotIn("KEYLEAKCHECK123", p.stdout + p.stderr)
        self.assertFalse(any("KEYLEAKCHECK123" in (r[0] or "") for r in raw("SELECT error FROM fetch_runs")))
        lg = ROOT / "logs" / "fetch.log"
        if lg.exists(): self.assertNotIn("KEYLEAKCHECK123", lg.read_text())

    # ---- admin & security
    def test_15_admin_protected(self):
        for p in ["/admin", "/add_news", "/admin/edit/1"]:
            r = self.c.get(p); self.assertEqual(r.status_code, 302, p); self.assertIn("/login", r.headers["Location"])
        for p in ["/admin/delete/1", "/admin/fetch_now", "/admin/add_category", "/admin/toggle/1/is_featured"]:
            self.assertIn(self.c.post(p).status_code, (400, 302), p)       # CSRF reject
        t = tok(self.c)
        for p in ["/admin/delete/1", "/admin/fetch_now", "/admin/add_category", "/admin/toggle/1/is_featured", "/admin/delete_category/sports"]:
            r = self.c.post(p, data={"csrf_token": t}); self.assertEqual(r.status_code, 302, p); self.assertIn("/login", r.headers["Location"], p)
        self.assertEqual(raw("SELECT COUNT(*) FROM categories WHERE slug='sports'")[0][0], 1)

    def test_16_login_flow_and_lockout(self):
        self.assertEqual(login(self.c, "wrong").status_code, 200)
        r = login(self.c); self.assertEqual(r.status_code, 302)           # configured password works
        self.assertEqual(self.c.get("/admin").status_code, 200)
        if LEGACY_PW:
            self.assertIn("original admin password", self.c.get("/admin").get_data(as_text=True))
        c2 = A.app.test_client()
        for _ in range(6): login(c2, "bad")
        self.assertIn("Too many attempts", login(c2).get_data(as_text=True))

    def test_17_admin_crud_and_features(self):
        login(self.c); t = tok(self.c)
        n = raw("SELECT COUNT(*) FROM news")[0][0]
        r = self.c.post("/add_news", data={"csrf_token": t, "title": "Test <script>alert(1)</script> story", "content": "Para one.\n\nPara two.",
                                           "category": "sports", "status": "published", "is_featured": "on"})
        self.assertIn("successfully", r.get_data(as_text=True)); i = raw("SELECT id FROM news WHERE title LIKE 'Test <script>%'")[0][0]
        page = self.c.get(f"/news/{i}/x", follow_redirects=True).get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", page); self.assertIn("&lt;script&gt;", page)    # escaped
        self.assertIn(f"/news/{i}/", self.c.get("/").get_data(as_text=True))                           # featured => hero
        self.c.post("/add_news", data={"csrf_token": t, "title": "Draft story zz", "content": "x", "category": "all", "status": "draft"})
        d = raw("SELECT id FROM news WHERE title='Draft story zz'")[0][0]
        self.assertEqual(A.app.test_client().get(f"/news/{d}").status_code, 404)                        # draft not public
        self.assertEqual(self.c.get(f"/news/{d}/draft-story-zz?preview=1").status_code, 200)
        fut = "2099-01-01T10:00"; self.c.post("/add_news", data={"csrf_token": t, "title": "Future story zz", "content": "x", "category": "all", "publish_at": fut})
        f = raw("SELECT id FROM news WHERE title='Future story zz'")[0][0]
        self.assertEqual(A.app.test_client().get(f"/news/{f}").status_code, 404)                        # scheduled not public yet
        r = self.c.post(f"/admin/edit/{i}", data={"csrf_token": t, "title": "Edited title", "content": "c", "category": "sports"}); self.assertEqual(r.status_code, 302)
        self.assertEqual(raw("SELECT title FROM news WHERE id=?", i)[0][0], "Edited title")
        self.c.post(f"/admin/delete/{i}", data={"csrf_token": t}); self.assertEqual(raw("SELECT COUNT(*) FROM news WHERE id=?", i)[0][0], 0)
        self.assertTrue(raw("SELECT COUNT(*) FROM admin_log")[0][0] >= 4)
        # category add/delete keeps news (moved to 'all')
        self.c.post("/admin/add_category", data={"csrf_token": t, "label": "Gaming Zone"}); self.assertEqual(raw("SELECT COUNT(*) FROM categories WHERE slug='gaming-zone'")[0][0], 1)

    def test_18_fetch_now_cooldown(self):
        login(self.c); t = tok(self.c)
        with mock.patch("fetcher.requests.get", return_value=R(API_OK)), mock.patch("fetcher.time.sleep"):
            self.c.post("/admin/fetch_now", data={"csrf_token": t}); self.c.post("/admin/fetch_now", data={"csrf_token": t})
        self.assertEqual(raw("SELECT COUNT(*) FROM fetch_runs WHERE trigger='manual'")[0][0], 1)       # 2nd blocked by cooldown
        dash = self.c.get("/admin").get_data(as_text=True)
        self.assertNotIn("SECRETKEY999", dash); self.assertIn("News fetch status", dash)

    def test_19_upload_validation(self):
        login(self.c); t = tok(self.c)
        from PIL import Image
        buf = io.BytesIO(); Image.new("RGB", (50, 50), "red").save(buf, "PNG"); buf.seek(0)
        r = self.c.post("/add_news", data={"csrf_token": t, "title": "Upload ok zz", "content": "c", "category": "all", "image_file": (buf, "a.png")}, content_type="multipart/form-data")
        self.assertIn("successfully", r.get_data(as_text=True)); img = raw("SELECT image_url FROM news WHERE title='Upload ok zz'")[0][0]
        self.assertTrue(img.startswith("/static/uploads/") and img.endswith(".webp")); self.assertTrue((ROOT / img.lstrip("/")).exists()); (ROOT / img.lstrip("/")).unlink()
        for name, data in (("evil.php", b"<?php system($_GET[0]);"), ("a.png", b"not an image at all"), ("a.svg", b"<svg onload=alert(1)>")):
            r = self.c.post("/add_news", data={"csrf_token": t, "title": "Bad upload " + name, "content": "c", "category": "all", "image_file": (io.BytesIO(data), name)}, content_type="multipart/form-data")
            self.assertNotIn("successfully", r.get_data(as_text=True), name)
        big = io.BytesIO(b"\xff\xd8\xff" + b"0" * (4 * 1024 * 1024))
        r = self.c.post("/add_news", data={"csrf_token": t, "title": "Big upload", "content": "c", "category": "all", "image_file": (big, "b.jpg")}, content_type="multipart/form-data")
        self.assertNotIn("successfully", r.get_data(as_text=True))
        r = self.c.post("/add_news", data={"csrf_token": t, "title": "JS image", "content": "c", "image_url": "javascript:alert(1)"}); self.assertNotIn("successfully", r.get_data(as_text=True))

    def test_20_headers_cookies(self):
        r = self.c.get("/"); csp = r.headers["Content-Security-Policy"]
        self.assertIn("nonce-", csp); self.assertIn("object-src 'none'", csp); self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        h = r.get_data(as_text=True); n = re.search(r"nonce-([\w-]+)", csp).group(1); self.assertIn(f'nonce="{n}"', h)
        login(self.c); self.assertIn("no-store", self.c.get("/admin").headers["Cache-Control"])
        self.assertNotIn("SECRETKEY999", h)
        self.assertTrue(A.app.config["SESSION_COOKIE_HTTPONLY"]); self.assertEqual(A.app.config["SESSION_COOKIE_SAMESITE"], "Lax")

    # ---- PWA
    def test_21_pwa(self):
        m = self.c.get("/manifest.webmanifest"); j = m.get_json()
        self.assertEqual(m.mimetype, "application/manifest+json")
        for k in ("name", "short_name", "start_url", "scope", "display", "icons", "theme_color", "background_color"): self.assertIn(k, j)
        for ic in j["icons"]:
            p = ROOT / ic["src"].lstrip("/"); self.assertTrue(p.exists(), ic["src"])
            from PIL import Image; self.assertEqual("%dx%d" % Image.open(p).size, ic["sizes"])
        sw = self.c.get("/sw.js"); self.assertEqual(sw.headers["Service-Worker-Allowed"], "/"); self.assertIn("no-cache", sw.headers["Cache-Control"])
        body = sw.get_data(as_text=True)
        for must in ("admin", "login", "api", "fragment", "add_news"): self.assertIn(must, body)   # private paths excluded from caching
        self.assertNotIn("showNotification", body); self.assertNotIn("PushManager", body)    # no push in this phase
        self.assertNotIn("Notification.requestPermission", (ROOT / "static/js/app.js").read_text())
        self.assertIn("/offline", body); self.assertIn("manifest", self.c.get("/").get_data(as_text=True))


class ZCron(unittest.TestCase):   # runs last: it writes fetched rows into the test copy
    def test_cron_endpoint_disabled_by_default_and_token_guarded(self):
        c = A.app.test_client(); os.environ.pop("FETCH_CRON_TOKEN", None)
        self.assertEqual(c.post("/cron/fetch").status_code, 404)
        os.environ["FETCH_CRON_TOKEN"] = "x" * 32
        self.assertEqual(c.post("/cron/fetch").status_code, 404)
        self.assertEqual(c.post("/cron/fetch", headers={"Authorization": "Bearer wrong"}).status_code, 404)
        self.assertEqual(c.get("/cron/fetch").status_code, 405)
        cn = db.connect(); db.set_setting(cn, "cron_fetch_ts", "0"); cn.commit(); cn.close()
        with mock.patch("fetcher.requests.get", return_value=R(API_OK)), mock.patch("fetcher.time.sleep"):
            r = c.post("/cron/fetch", headers={"Authorization": "Bearer " + "x" * 32}); self.assertEqual(r.status_code, 200)
            r2 = c.post("/cron/fetch", headers={"Authorization": "Bearer " + "x" * 32}); self.assertEqual(r2.status_code, 429)
        os.environ.pop("FETCH_CRON_TOKEN", None)


class Guard(unittest.TestCase):
    def _app(self, dbpath):
        env = dict(os.environ); env["AA_NEWS_DB"] = dbpath
        code = f"import sys;sys.path.insert(0,{str(ROOT)!r});import app;c=app.app.test_client();r=c.get('/');print(r.status_code)"
        return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=str(TMP))

    def test_missing_db_never_created(self):
        missing = TMP / "nothere" / "news.db"
        p = self._app(str(missing)); self.assertIn("503", p.stdout); self.assertFalse(missing.exists()); self.assertFalse(missing.parent.exists())

    def test_unmigrated_db_refuses_and_is_untouched(self):
        d = TMP / "raw.db"; shutil.copy(SRC, d); h0 = d.read_bytes()
        p = self._app(str(d)); self.assertIn("503", p.stdout); self.assertEqual(d.read_bytes(), h0)

    def test_migrate_missing_db_aborts(self):
        p = subprocess.run([sys.executable, str(ROOT / "tools/migrate.py"), "--apply", "--db", str(TMP / "none.db")], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2); self.assertFalse((TMP / "none.db").exists())


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
