"""Minimal .env loader (no external dep). Import this FIRST in app.py so env vars
are set before any module reads os.environ.

Only sets keys not already present in the real environment (real env wins).
"""
import os
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"


def load_env(path=ENV_PATH):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


load_env()
