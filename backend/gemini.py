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

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")


def has_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def chat(prompt, system=None, timeout=20) -> str:
    """Return Gemini's text reply, or "" if no key / failure. Never raises."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return ""
    try:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent")
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "X-goog-api-key": key})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return ""
