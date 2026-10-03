#!/usr/bin/env python3
"""Safe, additive migration runner.

  python tools/migrate.py --check            # report only, changes nothing
  python tools/migrate.py --apply            # backup -> migrate -> verify
  python tools/migrate.py --apply --db /path/to/COPY_of_news.db   # rehearse on a copy

Never deletes or recreates the database. Aborts if the file is missing.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import db  # noqa: E402
from tools.backup import make_backup  # noqa: E402

MIG = Path(__file__).resolve().parent.parent / "migrations" / "001_upgrade.sql"


def snapshot(path):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    out = {
        "news_rows": c.execute("SELECT COUNT(*) FROM news").fetchone()[0],
        "category_rows": c.execute("SELECT COUNT(*) FROM categories").fetchone()[0],
        "max_id": c.execute("SELECT MAX(id) FROM news").fetchone()[0],
        "data_fingerprint": tuple(c.execute(
            "SELECT COUNT(*), SUM(LENGTH(COALESCE(title,''))+LENGTH(COALESCE(url,''))+LENGTH(COALESCE(content,'')) "
            "+LENGTH(COALESCE(source,''))+LENGTH(COALESCE(category,''))+LENGTH(COALESCE(image_url,''))) FROM news").fetchone()),
        "categories": tuple(c.execute("SELECT slug,label FROM categories ORDER BY id").fetchall()),
    }
    c.close()
    return out


def split_sql(sql):
    """One statement per item; CREATE TRIGGER ... END; blocks are kept whole."""
    stmts, buf, in_trig = [], [], False
    for line in sql.splitlines():
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        buf.append(line)
        if s.upper().startswith("CREATE TRIGGER"):
            in_trig = True
        if in_trig:
            if s.upper() == "END;":
                stmts.append("\n".join(buf))
                buf, in_trig = [], False
        elif s.endswith(";"):
            stmts.append("\n".join(buf))
            buf = []
    return stmts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    path = Path(a.db)
    if not path.is_file():
        print(f"ABORT: database not found at {path}. Nothing was created.")
        return 2
    print(f"Target database: {path.resolve()}")
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row
    ver = db.schema_version(ro)
    ro.close()
    before = snapshot(path)
    print(f"Schema version {ver} -> target {db.SCHEMA_VERSION}")
    print("Before:", {k: v for k, v in before.items() if k not in ("categories",)})
    if ver >= db.SCHEMA_VERSION:
        print("Already migrated. Nothing to do.")
        return 0
    if not a.apply:
        print("CHECK ONLY - nothing changed. Re-run with --apply to back up and migrate.")
        return 0
    backup = make_backup(path)
    print("Backup written:", backup)
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30)
    try:
        conn.execute("BEGIN IMMEDIATE")
        fts5 = True
        try:
            conn.execute("CREATE VIRTUAL TABLE temp._fts_probe USING fts5(x)")
            conn.execute("DROP TABLE temp._fts_probe")
        except sqlite3.Error:
            fts5 = False
            print("NOTE: this SQLite build has no FTS5 - skipping full-text index; search will use indexed LIKE.")
        for stmt in split_sql(MIG.read_text(encoding="utf-8")):
            if not fts5 and ("news_fts" in stmt):
                continue
            conn.execute(stmt)
        conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('schema_version',?,datetime('now')) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(db.SCHEMA_VERSION),))
        conn.execute("COMMIT")
    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        print("MIGRATION FAILED and was rolled back:", e)
        print("Your data is untouched. Backup:", backup)
        return 1
    finally:
        conn.close()
    after = snapshot(path)
    ic = sqlite3.connect(f"file:{path}?mode=ro", uri=True).execute("PRAGMA integrity_check").fetchone()[0]
    print("After: ", {k: v for k, v in after.items() if k not in ("categories",)})
    print("integrity_check:", ic)
    if after != before or ic != "ok":
        print("VERIFICATION FAILED - restore the backup:", backup)
        return 1
    print("VERIFIED: every existing article and category is unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
