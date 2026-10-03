# Test report (what was actually run, and what was not)

Environment: Linux sandbox, Python 3.12, SQLite 3.45 (FTS5 available), headless Chromium 141. All tests ran against **copies** of your `news.db`; the original was never written to.

## Passed — automated (`python tests/test_all.py`, 25 tests)
Database: row/category/max-id/content fingerprint identical after migration; migration rehearsed on a copy, re-run is a no-op; missing DB → app returns 503 and **creates nothing**; un-migrated DB → 503 and file left byte-identical; migrator aborts on missing file.
Routes: every public page, legacy JSON routes, `/read/<id>` 301, 404 handling.
Search: FTS match, category and source counts equal SQL counts, date range (display-timezone aware), hostile queries (quotes, operators, 500 chars), no-results page, pager keeps filters.
Popularity: nothing "trending" with zero views; counts real views once per session; bots ignored. Breaking banner only via flag.
Fetching (mocked API): saves new items, rejects invalid, dedupes on repeat runs (0 new on 2nd run), API 429/500/timeout keep existing data and site still serves, key never appears in errors/logs, lock prevents overlap, daily budget enforced, script exits cleanly, cooldown on "Fetch now", optional cron endpoint disabled without token / 404 on bad token / rate-limited.
Security: admin routes redirect when logged out; all POSTs rejected without CSRF; original password still works; lockout after 5 failures; XSS in titles escaped; drafts and scheduled posts not public; upload validation (php/svg/garbage/oversize/`javascript:` URL rejected, valid PNG re-encoded to WebP); CSP nonce, nosniff, no-store on admin, cookie flags.
PWA: manifest fields, icon files exist with declared sizes, MIME types, SW scope header, SW excludes admin/login/api paths, no push code.

## Passed — browser (Chromium, scripts in `tests/browser/`)
No horizontal overflow and no JS errors on home/search/section/article at 390, 768 and 1280 px, light and dark. Dark mode persists; bookmarks add/remove/badge; saved and history pages; font-size control; load-more; debounced suggestions; search → results; service worker registers and creates caches; with the server stopped, a visited page loads from cache, an unvisited page shows the offline page, and `/admin` is **not** served from cache.

## NOT verified — you need to check
* Real NewsData responses and quota: the sandbox could not reach the API; fetch tests used mocked responses shaped like NewsData's documented fields. Run `python3 tools/fetch_news.py` once on PythonAnywhere and read the JSON it prints.
* PythonAnywhere scheduled tasks, your plan's limits, and whether your Python/SQLite there has FTS5 (the migrator handles absence).
* The migration on your **production** file (rehearsed only on copies of the uploaded one).
* Real Android/iOS devices, the browser "Install" prompt, Lighthouse scores, image loading from publishers (sandbox blocked external images, so only the fallback placeholder was seen).
* HTTPS cookies in production (tests ran with `AA_NEWS_ENV=development`).
* Social-preview rendering (Facebook/WhatsApp debuggers), Google Search Console sitemap submission.
* Windows: not tested. The fetch lock is skipped there (no `fcntl`); the site itself should run.
