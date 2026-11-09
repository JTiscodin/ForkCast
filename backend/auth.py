"""Per-user access tokens: every user-scoped route must prove it owns the user_id.

POST /user returns {user_id, token}; the browser sends `Authorization: Bearer <token>`.
The token is HMAC-SHA256(secret, user_id): no token table, nothing to leak from the
DB, and it can't be forged without the server secret.

Secret: FORKCAST_SECRET env var, else a random one generated once into
backend/.auth_secret (gitignored). Rotating it signs every user out.

shortcut: tokens never expire; add an issued-at + expiry (or Swiggy OAuth sign-in)
when there are real multi-user accounts.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path

from fastapi.responses import JSONResponse

_SECRET_FILE = Path(__file__).parent / ".auth_secret"

# Routes anyone may call: the health/mode probe, creating a user, the onboarding
# quiz, and connecting the server's Swiggy account (needed before a user exists).
# shortcut: /mcp/addresses and /im/search use the server's single Swiggy login, so
# they stay open for onboarding; per-user Swiggy OAuth removes this in production.
PUBLIC = {("POST", "/user"), ("GET", "/mode"), ("GET", "/daily/quiz"),
          ("POST", "/auth/swiggy/start"), ("GET", "/auth/swiggy/status"),
          ("GET", "/mcp/addresses"), ("GET", "/mcp/tools"), ("GET", "/im/search"),
          ("GET", "/docs"), ("GET", "/openapi.json")}
LOOPBACK_ONLY = {("POST", "/daily/nightly")}
_USER_PATH = re.compile(r"^/(?:daily|wallet)/(\d+)(?:/|$)")
_PLAN_PATH = re.compile(r"^/plan/(\d+)(?:/|$)")
_SLOT_PATH = re.compile(r"^/slot/(\d+)(?:/|$)")


def _secret():
    s = os.environ.get("FORKCAST_SECRET")
    if s:
        return s.encode()
    try:   # owner-only, created atomically so two workers can't race
        fd = os.open(_SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return _SECRET_FILE.read_text().strip().encode()


def token_for(user_id):
    return hmac.new(_secret(), str(int(user_id)).encode(), hashlib.sha256).hexdigest()


def user_from(header):
    """'Bearer <uid>.<sig>' -> uid, or None if missing/forged."""
    if not header or not header.startswith("Bearer "):
        return None
    uid, _, sig = header[7:].strip().partition(".")
    if not uid.isdigit() or not hmac.compare_digest(sig, token_for(uid)):
        return None
    return int(uid)


def bearer(user_id):
    return f"{int(user_id)}.{token_for(user_id)}"


def owner_of(conn, path):
    """user_id that owns the plan/slot in the path; None if the path has none."""
    if m := _PLAN_PATH.match(path):
        r = conn.execute("SELECT user_id FROM plans WHERE id = ?", (int(m[1]),)).fetchone()
        return r[0] if r else -1
    if m := _SLOT_PATH.match(path):
        r = conn.execute("SELECT p.user_id FROM meal_slots s JOIN plans p ON s.plan_id = p.id WHERE s.id = ?",
                         (int(m[1]),)).fetchone()
        return r[0] if r else -1
    return None


def _deny(code, msg):
    return JSONResponse({"detail": msg}, status_code=code)


def middleware(get_conn):
    async def check(request, call_next):
        key = (request.method, request.url.path)
        if request.method == "OPTIONS" or key in PUBLIC:
            return await call_next(request)
        if key in LOOPBACK_ONLY:
            host = request.client.host if request.client else ""
            return await call_next(request) if host in ("127.0.0.1", "::1") else _deny(403, "local only")
        uid = user_from(request.headers.get("authorization"))
        if uid is None:
            return _deny(403, "Sign in again: missing or invalid session")
        path = request.url.path
        if (m := _USER_PATH.match(path)) and int(m[1]) != uid:
            return _deny(403, "Not your account")
        conn = get_conn()
        try:
            owner = owner_of(conn, path)
        finally:
            conn.close()
        if owner is not None and owner != uid:
            return _deny(403 if owner != -1 else 404, "Not your plan" if owner != -1 else "Not found")
        # any user_id the request carries (query or body, whatever the content-type) must be the caller's
        claimed = [request.query_params.get("user_id")]
        body = await request.body()   # starlette caches it for the route
        if body:
            try:
                data = json.loads(body)
            except ValueError:
                data = None
            if isinstance(data, dict):
                claimed.append(data.get("user_id"))
        if any(c is not None and str(c) != str(uid) for c in claimed):
            return _deny(403, "Not your account")
        return await call_next(request)
    return check
