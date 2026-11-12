"""Thin Gemini chat helper — reuses the exact HTTP pattern from intake.llm_parse
(same URL / X-goog-api-key header / gemini-flash-latest model), but in plain chat
mode (free-text out) rather than JSON mode.

Kept tiny and dependency-free (urllib) so the demo never blocks on a missing key:
callers pass a deterministic fallback that is returned when GEMINI_API_KEY is unset
or any network/parse error occurs.
"""
import os
import json
import urllib.request

# Model choice is driven by WHICH QUOTA a model is limited by, not by how smart
# it is — this workload is simple JSON extraction, so the dumbest model that
# returns clean JSON fast is the right one.
#
# Measured against this key:
#   gemini-3.6-flash / flash-latest  20 requests per DAY   -> useless, ~3 chats
#   gemini-3.5-flash-lite            15 requests per MINUTE -> recovers in 60s
#   gemma-4-31b-it                   large quota, but 4x slower and ignores
#                                    "return only JSON" (emits prose)
#
# A per-MINUTE cap is the one to want: it refills continuously, while a spent
# daily cap kills the feature until midnight Pacific. flash-lite also answered
# in ~1.0s with clean unfenced JSON.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Tried in order on 429. Quotas are per-model, so each entry is a separate
# bucket — ordered by measured latency and JSON cleanliness. The per-day models
# sit last as a genuine last resort.
FALLBACK_MODELS = [
    m.strip() for m in os.environ.get(
        "GEMINI_FALLBACK_MODELS",
        "gemini-3.1-flash-lite,gemini-2.5-flash-lite,gemini-flash-lite-latest,"
        "gemini-3.5-flash,gemini-2.5-flash"
    ).split(",") if m.strip()
]


def has_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


# Models found to be out of daily quota this process. Skipped on later calls so
# every request doesn't re-pay a doomed round-trip.
_EXHAUSTED = set()


def chat(prompt, system=None, timeout=30, file=None) -> str:
    """Return Gemini's text reply, or "" if no key / all models exhausted.

    Never raises — every caller has a deterministic fallback. Walks the model
    chain on 429 so one model's spent daily quota doesn't silently downgrade the
    whole app to heuristics.
    """
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return ""

    for model in [GEMINI_MODEL] + FALLBACK_MODELS:
        if model in _EXHAUSTED:
            continue
        text, quota_spent = _call(model, key, prompt, system, timeout, file)
        if text:
            return text
        if quota_spent == "day":
            # Daily cap won't recover until midnight Pacific — stop retrying it.
            _EXHAUSTED.add(model)
            print(f"[gemini] {model} out of DAILY quota; trying next model")
            continue
        if quota_spent == "minute":
            # Per-minute cap refills on its own. Move to the next model for this
            # request but keep this one in rotation — blacklisting it would throw
            # away the best model over a momentary burst.
            print(f"[gemini] {model} hit per-minute limit; trying next model")
            continue
        return ""  # a non-quota failure won't be fixed by another model
    print("[gemini] all models exhausted — using deterministic fallback")
    return ""


def _call(model, key, prompt, system, timeout, file=None):
    """One attempt. Returns (text, quota) where quota is None|"minute"|"day"."""
    try:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent")
        parts = [{"text": prompt}]
        if file:   # (mime, base64): an image or PDF for the model to read
            parts.append({"inline_data": {"mime_type": file[0], "data": file[1]}})
        body = {"contents": [{"parts": parts}]}
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "X-goog-api-key": key})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip(), None
    except urllib.error.HTTPError as e:
        # LOG, don't just swallow. Callers fall back silently, so a spent quota
        # looked exactly like "the heuristics handled it" — an adjust request
        # came back with no constraints and nothing said why.
        body = ""
        try:
            body = e.read().decode(errors="replace")
        except Exception:  # noqa: BLE001
            pass
        if e.code in (500, 503):
            # overloaded/unavailable is transient like a minute quota: try the
            # next model now, keep this one in rotation
            print(f"[gemini] {model} HTTP {e.code} (overloaded); trying next model")
            return "", "minute"
        if e.code != 429:
            print(f"[gemini] {model} HTTP {e.code}: {body[:200]}")
            return "", None
        # Distinguish a per-minute burst (recovers in ~60s) from a spent daily
        # cap (dead until midnight Pacific) — they need opposite handling.
        kind = "day" if "PerDay" in body else "minute"
        print(f"[gemini] {model} 429 ({kind} quota)")
        return "", kind
    except Exception as e:  # noqa: BLE001
        print(f"[gemini] {model} failed: {type(e).__name__}: {e}")
        return "", None
