"""Database access. Opens the EXISTING SQLite file only - it never creates a database."""
import sqlite3
from datetime import datetime, timezone
from urllib.parse import quote

import config

SCHEMA_VERSION = 1


class DatabaseUnavailable(RuntimeError):
    pass


def connect(path=None):
    path = path or config.DB_PATH
    if not path.is_file():
        # Deliberately do NOT create a new empty database.
        raise DatabaseUnavailable(f"Database file not found: {path}")
    conn = sqlite3.connect(f"file:{quote(str(path))}?mode=rw", uri=True, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_setting(conn, key, default=None):
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return default
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, str(value), utcnow_iso()),
    )


def schema_version(conn):
    try:
        return int(get_setting(conn, "schema_version", 0) or 0)
    except ValueError:
        return 0


def has_fts(conn):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='news_fts'"
    ).fetchone()
    return bool(row)
