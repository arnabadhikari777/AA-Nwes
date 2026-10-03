#!/usr/bin/env python3
"""Generate a strong admin password hash:  python tools/make_password_hash.py
Put the printed line in your private .env (PythonAnywhere: mysite/.env) as ADMIN_PASSWORD_HASH=..."""
import getpass
from werkzeug.security import generate_password_hash

pw = getpass.getpass("New admin password (min 12 chars): ")
if len(pw) < 12 or pw != getpass.getpass("Repeat: "):
    raise SystemExit("Too short or not matching.")
print("\nADMIN_PASSWORD_HASH=" + generate_password_hash(pw))
