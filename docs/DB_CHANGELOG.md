# Database change log

Existing database inspected: `mysite/news.db` — tables `news` (479 rows, ids 1–494), `categories` (8 rows, includes your custom `marvel-studios`), `sqlite_sequence`; unique index `idx_news_title_unique` (title, NOCASE).

## Migration 001 (`migrations/001_upgrade.sql`, schema_version 1) — additive only
Nothing is dropped, renamed, truncated or deleted. Existing columns, rows, ids and the unique title index are untouched.

**New columns on `news`** (all nullable or defaulted; old rows get NULL/defaults, nothing is invented):
`description`, `author`, `external_id`, `published_at`, `created_at`, `updated_at`, `publish_at`, `status` (default `published`), `is_featured` (0), `is_breaking` (0).
Old rows have no publish date, so no date is shown for them and date filters exclude them.

**New tables:** `article_views` (article_id, viewed_at — no IP/user data), `app_settings` (key/value; holds schema_version, last fetch time, API call counter), `fetch_runs` (one row per fetch), `admin_log`.

**New indexes:** category, source, url, external_id, published_at, flags, views(time) and views(article, time).

**Full-text search:** `news_fts` (SQLite FTS5, external-content on `news`) + three triggers keeping it in sync. If the SQLite build lacks FTS5, the migrator skips it and search falls back to indexed LIKE.

## Code behaviour that deliberately changed
* The old `dedupe_existing_news()` ran `DELETE FROM news` at every start. It is **removed**. Duplicates are still blocked by the existing unique title index and by URL / API-id checks on insert.
* No database is ever created by the app. Missing file → site shows a 503 and logs the problem. Un-migrated database → 503 until you run the migration.
