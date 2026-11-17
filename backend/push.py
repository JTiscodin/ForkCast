"""Web Push meal-time reminders: VAPID keys, subscriptions, and the minute tick."""
import base64
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import daily

# Only browser push services may be called, so a stored subscription can't point the server at an internal URL.
PUSH_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "notify.windows.com", "web.push.apple.com")


def _push_host_ok(endpoint):
    u = urlparse(endpoint or "")
    host = (u.hostname or "").rstrip(".").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)

_VAPID_FILE = Path(__file__).parent / ".vapid.json"
_SENT = set()   # (user_id, date, slot) already reminded; shortcut: in-memory, a restart may resend once


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def vapid():
    """{public, private, subject}: from env, else generated once into backend/.vapid.json (0600)."""
    if os.environ.get("VAPID_PUBLIC_KEY") and os.environ.get("VAPID_PRIVATE_KEY"):
        return {"public": os.environ["VAPID_PUBLIC_KEY"], "private": os.environ["VAPID_PRIVATE_KEY"],
                "subject": os.environ.get("VAPID_SUBJECT", "mailto:admin@localhost")}
    if not _VAPID_FILE.exists():
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        k = ec.generate_private_key(ec.SECP256R1())
        keys = {"public": _b64(k.public_key().public_bytes(
                    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)),
                "private": _b64(k.private_numbers().private_value.to_bytes(32, "big"))}
        try:   # owner-only, created atomically so two workers can't race (like .auth_secret)
            fd = os.open(_VAPID_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(keys, f)
        except FileExistsError:
            pass
    keys = json.loads(_VAPID_FILE.read_text())
    return {**keys, "subject": os.environ.get("VAPID_SUBJECT", "mailto:admin@localhost")}


def subscribe(conn, user_id, sub):
    k = sub.get("keys") or {}
    if not (_push_host_ok(sub.get("endpoint", "")) and k.get("p256dh") and k.get("auth")):
        raise ValueError("invalid push subscription")
    # an endpoint re-subscribed by another account on the same browser moves to that account
    conn.execute("INSERT INTO push_subscription (user_id, endpoint, p256dh, auth) VALUES (?,?,?,?) "
                 "ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id, p256dh=excluded.p256dh, "
                 "auth=excluded.auth", (user_id, sub["endpoint"], k["p256dh"], k["auth"]))
    conn.commit()


def unsubscribe(conn, user_id, endpoint=None):
    q, a = "DELETE FROM push_subscription WHERE user_id=?", [user_id]
    if endpoint:
        q, a = q + " AND endpoint=?", a + [endpoint]
    conn.execute(q, a)
    conn.commit()


def due_slots(slots, windows, hhmm, ordered):
    """Planned slots whose window opens at hhmm and aren't ordered yet. Pure."""
    return [s for s in slots if windows.get(s, [None])[0] == hhmm and s not in ordered]


def payload(conn, user_id, day, slot):
    card = conn.execute("SELECT c.items, c.price FROM menu_card c JOIN daily_menu m ON m.id=c.menu_id "
                        "WHERE m.user_id=? AND m.date=? AND m.slot=? ORDER BY c.position LIMIT 1",
                        (user_id, day.isoformat(), slot)).fetchone()
    if card:
        items = json.loads(card["items"] or "[]")
        body = f"{items[0]['name'] if items else 'Your pick'} · ₹{round(card['price'])}. Deliver now?"
    else:
        body = "Your picks are ready. Deliver now?"
    return {"title": f"{slot.capitalize()} time", "body": body, "url": f"/#slot-{slot}",
            "tag": f"forkcast-{slot}-{day.isoformat()}"}


def _send(sub, data, keys):
    if not _push_host_ok(sub["endpoint"]):   # re-check rows saved before the allowlist
        raise ValueError("push endpoint not allowed")
    from pywebpush import webpush
    webpush({"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
            json.dumps(data), vapid_private_key=keys["private"], vapid_claims={"sub": keys["subject"]})


def tick(conn, now=None, send=_send):
    """Send every due reminder once. Returns how many notifications went out."""
    now = now or datetime.now(ZoneInfo(os.environ.get("TZ") or "Asia/Kolkata"))
    day, hhmm, sent = now.date(), now.strftime("%H:%M"), 0
    users = [r[0] for r in conn.execute("SELECT DISTINCT user_id FROM push_subscription")]
    keys = vapid() if users else None
    for uid in users:
        p = daily.get_profile(conn, uid)
        if not p:
            continue
        ordered = {s for s in p["slots"] if daily._ordered(conn, uid, day, s)}
        for slot in due_slots(p["slots"], p["windows"], hhmm, ordered):
            if (uid, day, slot) in _SENT:
                continue
            _SENT.add((uid, day, slot))
            data = payload(conn, uid, day, slot)
            for sub in conn.execute("SELECT * FROM push_subscription WHERE user_id=?", (uid,)).fetchall():
                try:
                    send(sub, data, keys)
                    sent += 1
                except Exception as e:  # noqa: BLE001 — one dead endpoint mustn't stop the rest
                    code = getattr(getattr(e, "response", None), "status_code", None)
                    if code in (404, 410):   # browser dropped the subscription
                        conn.execute("DELETE FROM push_subscription WHERE id=?", (sub["id"],))
                        conn.commit()
                    else:
                        print(f"[push] send failed: {e}")
    return sent
