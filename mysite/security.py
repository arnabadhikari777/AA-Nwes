# -*- coding: utf-8 -*-
"""A.A.News security layer: HTTPS redirect, CSRF protection, security headers and CSP.

Usage (already wired in app.py):
    from security import init_security
    init_security(app)

Optional .env settings:
    FORCE_HTTPS=1          redirect http -> https (never on localhost) + HSTS + Secure cookies
    CSP_MODE=report        send the CSP as Report-Only (nothing is blocked, only logged in the
                           browser console). Default is "enforce".
"""

import hmac
import os
import secrets
from urllib.parse import urlparse

from flask import g, jsonify, redirect, request, session

# The Email Sender API that powers the public Contact form
EMAIL_SENDER_ORIGIN = "https://email-sender-wy5o.onrender.com"

# These endpoints are called by JavaScript (sendBeacon cannot add a CSRF header), so instead of a
# token they must come from our own site: the Origin/Referer header has to match this host.
SAME_ORIGIN_ONLY = ("/presence/", "/push/")


def _env_flag(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _is_local_host():
    host = (request.host or "").split(":")[0].lower()
    return host in ("localhost", "127.0.0.1", "[::1]", "::1")


def _is_secure():
    # PythonAnywhere / Render sit behind a proxy that tells us the original scheme
    return request.is_secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"


def build_csp(nonce):
    return "; ".join([
        "default-src 'self'",
        # own files, Google Analytics loader, and inline <script nonce="..."> blocks of THIS request
        "script-src 'self' 'nonce-%s' https://www.googletagmanager.com" % nonce,
        # no inline event handlers (onclick=...): they are handled by templates/_guard.html
        "script-src-attr 'none'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com",
        "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com",
        # news thumbnails come from many publishers, so any https image is allowed
        "img-src 'self' data: blob: https:",
        "connect-src 'self' %s https://www.google-analytics.com https://*.google-analytics.com "
        "https://*.analytics.google.com https://www.googletagmanager.com "
        "https://stats.g.doubleclick.net" % EMAIL_SENDER_ORIGIN,
        "manifest-src 'self'",
        "worker-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self' %s" % EMAIL_SENDER_ORIGIN,
        "frame-ancestors 'self'",
    ])


def init_security(app):
    force_https = _env_flag("FORCE_HTTPS")
    report_only = os.environ.get("CSP_MODE", "enforce").strip().lower() == "report"

    # Safer session cookie (the admin login lives in it)
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    if force_https:
        app.config["SESSION_COOKIE_SECURE"] = True

    # ---- CSP nonce: one random value per request, used by templates and the header ----
    def csp_nonce():
        n = getattr(g, "csp_nonce", None)
        if not n:
            n = g.csp_nonce = secrets.token_urlsafe(18)
        return n

    # ---- CSRF token: stored in the session, written into every POST form ----
    def csrf_token():
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        return token

    app.jinja_env.globals["csp_nonce"] = csp_nonce
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def enforce_https():
        if force_https and not _is_secure() and not _is_local_host():
            return redirect(request.url.replace("http://", "https://", 1), code=301)

    def _same_origin():
        src = request.headers.get("Origin") or request.headers.get("Referer") or ""
        if not src:
            return True  # not a browser cross-site request (browsers always send one of them)
        return urlparse(src).netloc == request.host

    def _reject(message):
        if request.is_json or request.path.startswith(SAME_ORIGIN_ONLY):
            return jsonify({"ok": False, "error": message}), 400
        return (
            "<h3>%s</h3><p>Go back, refresh the page and try again.</p>" % message,
            400,
        )

    @app.before_request
    def csrf_protect():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        if request.endpoint == "static":
            return None
        if request.path.startswith(SAME_ORIGIN_ONLY):
            return None if _same_origin() else _reject("Cross-site request blocked.")
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken") or ""
        expected = session.get("_csrf_token") or ""
        if expected and sent and hmac.compare_digest(sent, expected):
            return None
        return _reject("Your session expired or the form was invalid.")

    @app.after_request
    def add_security_headers(resp):
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if force_https and _is_secure():
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        name = "Content-Security-Policy-Report-Only" if report_only else "Content-Security-Policy"
        h.setdefault(name, build_csp(csp_nonce()))
        return resp
