#!/usr/bin/env python3
"""Scheduled news fetch. Run by a PythonAnywhere Scheduled Task - NOT by web requests.

Exit codes: 0 ok / skipped, 1 API errors recorded (data kept), 2 cannot use database.
"""
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import db  # noqa: E402
import fetcher  # noqa: E402


def main():
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(config.LOG_DIR / "fetch.log", maxBytes=500_000, backupCount=3)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger("aa_news").addHandler(h)
    logging.getLogger("aa_news").setLevel(logging.INFO)
    log = logging.getLogger("aa_news.fetch")
    try:
        s = fetcher.run("scheduled")
    except db.DatabaseUnavailable as e:
        log.error("database unavailable: %s", e)
        print("ERROR:", e)
        return 2
    except Exception as e:
        log.exception("unexpected failure")
        print("ERROR:", type(e).__name__)
        return 1
    log.info("fetch %s", json.dumps(s))
    print(json.dumps(s))
    return 0 if s["status"] in ("success", "skipped", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
