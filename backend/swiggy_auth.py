"""Swiggy MCP OAuth 2.1 login helper (PKCE + dynamic client registration).

Run:  python swiggy_auth.py
It will:
  1. Discover OAuth endpoints from the .well-known metadata.
  2. Dynamically register a public client (auth method 'none', PKCE S256).
  3. Open your browser to Swiggy's authorize page — you log in / grant access.
  4. Catch the redirect on http://localhost:8765/callback (whitelisted host).
  5. Exchange the auth code (+ PKCE verifier) for an access token.
  6. Write SWIGGY_MCP_TOKEN (and refresh token) into backend/.env.

After it finishes, set SWIGGY_MODE=mcp in .env and restart the app -> live Swiggy.

Verified metadata (mcp.swiggy.com/.well-known/oauth-authorization-server):
  issuer         https://mcp.swiggy.com/auth
  authorize      https://mcp.swiggy.com/auth/authorize
  token          https://mcp.swiggy.com/auth/token
  register       https://mcp.swiggy.com/auth/register
  PKCE           S256 (required), response_type=code
  scopes         mcp:tools mcp:resources mcp:prompts
  auth method    none (public client) — no client secret needed
  resource       https://mcp.swiggy.com/food  (RFC 8707 resource indicator)
"""
import os
import json
import base64
import hashlib
import secrets
import threading
import webbrowser
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

WELL_KNOWN = "https://mcp.swiggy.com/.well-known/oauth-authorization-server"
RESOURCE = os.environ.get("SWIGGY_MCP_URL", "https://mcp.swiggy.com/food")
SCOPES = "mcp:tools mcp:resources mcp:prompts"

REDIRECT_HOST = "localhost"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}/callback"

ENV_PATH = Path(__file__).parent / ".env"


# ---------- small HTTP helpers ----------
def _get_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _post_json(url, data, form=False):
    if form:
        body = urllib.parse.urlencode(data).encode()
        ctype = "application/x-www-form-urlencoded"
    else:
        body = json.dumps(data).encode()
        ctype = "application/json"
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": ctype, "Accept": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')}") from e


# ---------- PKCE ----------
def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


# ---------- redirect catcher ----------
class _Catcher(BaseHTTPRequestHandler):
    code = None
    state = None
    error = None

    def do_GET(self):
        q = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(q)
        _Catcher.code = (params.get("code") or [None])[0]
        _Catcher.state = (params.get("state") or [None])[0]
        _Catcher.error = (params.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = ("Swiggy connected. You can close this tab."
               if _Catcher.code else f"Auth failed: {_Catcher.error}")
        # window.close() works because the app opened this tab itself (popup flow)
        self.wfile.write((f"<html><body style='font-family:sans-serif;text-align:center;padding-top:20vh'>"
                          f"<h2>{msg}</h2><script>setTimeout(function(){{window.close()}},600)</script>"
                          f"</body></html>").encode())

    def log_message(self, *a):
        pass


def _wait_for_code(timeout=180):
    server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), _Catcher)
    server.timeout = timeout
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    t.join(timeout)
    server.server_close()
    return _Catcher.code, _Catcher.state, _Catcher.error


# ---------- env writer ----------
def _write_env(updates: dict):
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    keys = set(updates)
    out, seen = [], set()
    for ln in lines:
        k = ln.split("=", 1)[0].strip().lstrip("#").strip() if "=" in ln else None
        if k in keys:
            out.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            out.append(ln)
    for k in keys - seen:
        out.append(f"{k}={updates[k]}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------- flow ----------
def run(on_url=None):
    """on_url(url): hand the login URL to the caller (the web app opens it in its own
    popup) instead of opening a browser on this machine."""
    print("1/5 discovering OAuth metadata ...")
    meta = _get_json(WELL_KNOWN)
    authorize_url = meta["authorization_endpoint"]
    token_url = meta["token_endpoint"]
    register_url = meta.get("registration_endpoint")

    print("2/5 registering client ...")
    client_id = os.environ.get("SWIGGY_CLIENT_ID")
    if not client_id and register_url:
        reg = _post_json(register_url, {
            "client_name": "Budget Meal Planner (local)",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": SCOPES,
        })
        client_id = reg["client_id"]
        print(f"    registered client_id={client_id}")
    if not client_id:
        raise RuntimeError("no client_id and no registration endpoint")

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": RESOURCE,          # RFC 8707 — bind token to the food server
    }
    url = authorize_url + "?" + urllib.parse.urlencode(params)

    print("3/5 opening browser — log into Swiggy and approve ...")
    print(f"    if it doesn't open, paste this URL:\n    {url}\n")
    on_url(url) if on_url else webbrowser.open(url)

    print(f"4/5 waiting for redirect on {REDIRECT_URI} ...")
    code, got_state, err = _wait_for_code()
    if err:
        raise RuntimeError(f"authorization error: {err}")
    if not code:
        raise RuntimeError("timed out waiting for auth code")
    if got_state != state:
        raise RuntimeError("state mismatch — possible CSRF, aborting")

    print("5/5 exchanging code for token ...")
    tok = _post_json(token_url, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": verifier,
        "resource": RESOURCE,
    }, form=True)

    access = tok.get("access_token")
    refresh = tok.get("refresh_token", "")
    if not access:
        raise RuntimeError(f"no access_token in response: {tok}")

    _write_env({
        "SWIGGY_MCP_TOKEN": access,
        "SWIGGY_REFRESH_TOKEN": refresh,
        "SWIGGY_CLIENT_ID": client_id,
        "SWIGGY_MODE": "mcp",
    })
    # also update the live process env so the server can switch to live WITHOUT
    # a restart (the app calls _init_runtime() after this returns).
    os.environ["SWIGGY_MCP_TOKEN"] = access
    if refresh:
        os.environ["SWIGGY_REFRESH_TOKEN"] = refresh
    os.environ["SWIGGY_CLIENT_ID"] = client_id
    os.environ["SWIGGY_MODE"] = "mcp"
    print("\n  Success. Token written to backend/.env, SWIGGY_MODE=mcp.")
    print("  Restart the app -> live Swiggy ordering.")
    return access


def refresh():
    """Swap SWIGGY_REFRESH_TOKEN for a new access token (no browser).

    Returns the new access token, or None when no refresh token / client id is
    saved or the server refuses — the caller then falls back to a full login.
    """
    rt = os.environ.get("SWIGGY_REFRESH_TOKEN")
    client_id = os.environ.get("SWIGGY_CLIENT_ID")
    if not rt or not client_id:
        return None
    try:
        tok = _post_json(_get_json(WELL_KNOWN)["token_endpoint"], {
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": client_id,
            "resource": RESOURCE,
        }, form=True)
    except Exception as e:  # noqa: BLE001 — refresh failure means "log in again"
        print(f"[auth] refresh failed: {e}")
        return None
    access = tok.get("access_token")
    if not access:
        return None
    # servers may rotate the refresh token; keep the old one if they don't
    updates = {"SWIGGY_MCP_TOKEN": access,
               "SWIGGY_REFRESH_TOKEN": tok.get("refresh_token") or rt}
    _write_env(updates)
    os.environ.update(updates)
    return access


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"\n  FAILED: {e}")
        raise
