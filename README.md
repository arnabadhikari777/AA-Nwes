# A.A.News — upgraded portal

Flask + SQLite + vanilla HTML/CSS/JS, for PythonAnywhere. Start with `docs/DEPLOY.md`.

## What I found in the original code
* **The "hourly" refresh was not a scheduler.** The API was fetched at import/start-up and again inside `/get_news` whenever more than **10 seconds** had passed (the comment said one hour), and category pages called the API on every first-page visit. So it only ever ran when someone visited, and spent API quota per visit.
* Admin password, Flask secret and the NewsData key were hard-coded fallbacks in `app.py`.
* `dedupe_existing_news()` ran `DELETE FROM news` on every start.
* Database: `news.db` — 479 articles, 8 categories (one custom: `marvel-studios`), 5 admin-written articles (empty `url`).

## New features
Redesigned responsive UI (light/dark, remembered) · homepage with featured hero, breaking banner (admin flag only), latest with load-more, trending (24h views), most-read (7d views), category sections · search with FTS5, category/source/date filters, sort, pagination, debounced suggestions · article pages (`/news/<id>/<slug>`, reading time, share/copy, font size, related, canonical/OG/JSON-LD) · bookmarks and reading history (this device only, no account) · PWA (manifest, icons, service worker, offline page, update prompt, install button; **no push**) · sitemap.xml, robots.txt, 404/500 pages · admin: dashboard stats, drafts, scheduled publishing, featured/breaking, image upload (validated, re-encoded), fetch status + "Fetch now" (cooldown), error log, activity log · security: CSRF on all POSTs, CSP with nonces, secure cookies, login lockout, hashed password support, no secrets in code, safe uploads · scheduled fetcher with lock, dedupe (API id → URL → title), daily call budget, key redaction.

## Existing features preserved
All original URLs (`/`, `/get_news`, `/category/<slug>` JSON, `/get_categories`, `/read/<id>` → 301 to the new page, `/login`, `/logout`, `/add_news`, `/admin`, `/admin/edit|delete|add_category|delete_category`, `/about`, `/privacy-policy`) · same NewsData endpoint (`country=in`) and categories · English title translation (deep-translator, applied to non-Latin titles on fetch) · category add/delete (news moves to `all`) · original admin password keeps working until you set `ADMIN_PASSWORD_HASH` · Google Analytics (not loaded for a logged-in admin) · your About and Privacy text, verbatim.

## Behaviour changes you should know about
* Imported stories now open an on-site page (headline, image, source, "Read full story" link) instead of jumping straight to the publisher. Pages for imported stories are `noindex` by default (they are headline-only); admin-written articles are indexed. `INDEX_AGGREGATED=1` changes that.
* Category feeds refresh by rotation (one category per run → each ~every 3 hours) instead of on every visit.
* Old rows have no dates, so they show none and are excluded from date filters.
* Removed the placeholder phone number from the footer; `CONTACT_EMAIL` still defaults to your `info@aanews.com` — set a real address. Terms/Contact pages are new starter text for you to review.
* No multiple admin accounts exist, so no role system was added. Login lockout is per web worker (approximate). Public endpoints are not rate-limited.

## Private configuration (`mysite/.env`, see `.env.example`)
`NEWSDATA_API_KEY` · `SECRET_KEY` · `ADMIN_PASSWORD_HASH` · `SITE_URL` · `CONTACT_EMAIL` · `GA_MEASUREMENT_ID` · `NEWSDATA_MAX_CALLS_PER_DAY` · optional `FETCH_CRON_TOKEN`, `INDEX_AGGREGATED`, `AA_NEWS_DB`, `AA_NEWS_BACKUP_DIR`.

## Layout
`mysite/` app (`app.py`, `config.py`, `db.py`, `queries.py`, `fetcher.py`, `admin_tools.py`, `utils.py`) · `mysite/tools/` (`migrate.py`, `backup.py`, `fetch_news.py`, `make_password_hash.py`) · `mysite/migrations/` · `mysite/tests/` · `docs/`. The ZIP intentionally does **not** contain `news.db`.
