#!/usr/bin/env python3
"""Consistent SQLite backup (uses the sqlite3 backup API, safe while the site is live)."""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def make_backup(src=None, keep=20):
    src = Path(src or config.DB_PATH)
    if not src.is_file():
        raise SystemExit(f"Database not found: {src}")
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.BACKUP_DIR / f"news-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(str(dest))
    with d:
        s.backup(d)
    d.close()
    s.close()
    chk = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
    assert chk.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "backup failed integrity check"
    chk.close()
    for p in sorted(config.BACKUP_DIR.glob("news-*.db"))[:-keep]:  # prunes old BACKUPS only
        p.unlink()
    return dest


if __name__ == "__main__":
    print(make_backup())
