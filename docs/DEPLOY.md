# Deploying to PythonAnywhere (nothing here is automatic — you run each step)

Assumed username `arnabadhikari125117y` (taken from your site URL; adjust if different).

## 0. Test locally first
```bash
cd AA_News && python -m venv venv && source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp /path/to/your/news.db /tmp/news_copy.db                      # a COPY
AA_NEWS_BACKUP_DIR=/tmp/bk python mysite/tools/migrate.py --apply --db /tmp/news_copy.db
cd mysite && AA_NEWS_DB=/tmp/news_copy.db AA_NEWS_ENV=development python app.py     # http://127.0.0.1:5000
AA_TEST_SOURCE_DB=/path/to/your/news.db python tests/test_all.py                      # 25 tests, uses a copy
```
(Windows: the site runs locally; only the fetch-overlap lock is skipped there. Use `python` instead of `python3`.)

## 1. Rotate secrets (do this first)
The old source contained the NewsData API key, the admin password and a Flask secret in plain text, and it is in your repo history. Create a **new** NewsData key and a **new** admin password; treat the old ones as public.

## 2. Backup (see BACKUP_RECOVERY.md)

## 3. Upload the code
Bash console: keep `~/mysite/news.db` exactly where it is. Copy the new files from the ZIP over `~/mysite/` (app.py, config.py, db.py, fetcher.py, queries.py, utils.py, admin_tools.py, templates/, static/, tools/, migrations/). **Do not upload or overwrite news.db.** Old unused templates (`news_portal_frontend.html`, `read_news.html`, old `admin_dashboard.html`, `add_news.html`, `edit_news.html`, `login.html`) can stay until you are happy, then delete them.
```bash
pip3 install --user -r requirements.txt
```

## 4. Private configuration: create `~/mysite/.env` (see `.env.example`)
`NEWSDATA_API_KEY`, `SECRET_KEY`, `ADMIN_PASSWORD_HASH` (from `python3 tools/make_password_hash.py`), `SITE_URL`, `CONTACT_EMAIL`. `chmod 600 ~/mysite/.env`.

## 5. Migrate (needs your explicit go-ahead)
```bash
cd ~/mysite
python3 tools/migrate.py            # check only
python3 tools/migrate.py --apply    # backup → migrate → verify → "VERIFIED"
```
Until this is done the site shows a 503 page by design.

## 6. Reload the web app
Web tab → Reload. Your WSGI file should still contain `from app import app as application` (path `/home/arnabadhikari125117y/mysite`). Visit `/`, `/admin` (log in), `/manifest.webmanifest`, `/sitemap.xml`.

## 7. Scheduled fetch every 30 minutes
Test once by hand: `cd ~/mysite && python3 tools/fetch_news.py` (prints a JSON summary; see `logs/fetch.log`).

PythonAnywhere Scheduled Tasks only offer **hourly or daily** schedules, and free accounts get no hourly tasks. So "every 30 minutes" = **two hourly tasks**, one at minute 00 and one at minute 30 (Tasks tab → Hourly → set the minute):

```
cd /home/arnabadhikari125117y/mysite && python3.13 tools/fetch_news.py     # task A: hourly at :00
cd /home/arnabadhikari125117y/mysite && python3.13 tools/fetch_news.py     # task B: hourly at :30
```
(Use `python3.xx` matching your web app's Python, or your virtualenv's `bin/python`.) A lock file prevents overlap. Each run makes 2 API calls (the general feed plus one rotating category), i.e. ~96/day at 48 runs; confirm that fits your NewsData plan (`NEWSDATA_MAX_CALLS_PER_DAY` caps it).

If your plan has no scheduled tasks: set `FETCH_CRON_TOKEN` in `.env` and use an external scheduler to POST `/cron/fetch` with `Authorization: Bearer <token>` (example: `docs/optional-github-actions-fetch.yml`). It runs independently of visitors but timing is not guaranteed.

Verify: Admin → "News fetch status" shows last successful fetch and counts after the first run.

## 8. Update GitHub safely
```bash
git checkout -b upgrade
git rm --cached mysite/news.db        # stop tracking the DB (file stays on disk)
git add .gitignore README.md requirements.txt docs mysite
git status                            # confirm: no .env, no *.db, no logs/instance/uploads, no dot-folders
git commit -m "Upgrade: search, PWA, scheduled fetch, security" && git push -u origin upgrade
```
Open a pull request and merge when happy. Note old commits still contain the previous DB, key and password.
