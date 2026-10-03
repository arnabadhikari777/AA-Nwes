# Backup & recovery

Backups go to `../aa_news_backups/` (outside the project and outside `static/`; gitignored; last 20 kept).

```bash
cd ~/mysite && python3 tools/backup.py          # consistent online backup + integrity check
```
`tools/migrate.py --apply` makes its own backup first and verifies row counts, a content fingerprint, categories and `PRAGMA integrity_check` afterwards; on any error it rolls back.

## If something goes wrong
1. Reload-pause the site (PythonAnywhere Web tab → Disable) so nothing writes while you restore.
2. `cp ~/aa_news_backups/news-YYYYMMDD-HHMMSS.db ~/mysite/news.db`
3. Re-enable and reload. The old code also works with the migrated or un-migrated database (the migration only adds things).

## Pre-upgrade backup (do this by hand before anything else)
```bash
mkdir -p ~/aa_news_backups && python3 - <<'PY'
import sqlite3, os, time
src = sqlite3.connect(os.path.expanduser('~/mysite/news.db'))
dst = sqlite3.connect(os.path.expanduser(f'~/aa_news_backups/news-pre-upgrade-{int(time.time())}.db'))
src.backup(dst); dst.close(); print('ok')
PY
```
Also download a copy to your computer. Never commit `.db` files to GitHub.
