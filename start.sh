#!/usr/bin/env bash
# Starts Forkcast locally: backend on :8343, website on :6001. Ctrl+C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BACKEND_PORT="${BACKEND_PORT:-8343}"
FRONTEND_PORT="${FRONTEND_PORT:-6001}"   # 6000 is blocked by browsers (X11 port)
export PYTHONUTF8=1
export NEXT_PUBLIC_API_URL="http://localhost:${BACKEND_PORT}"

# ---- Python 3.11+ with the backend packages (venv first; Scripts/ is Git Bash on Windows) ----
PY=""
for c in "$ROOT/backend/.venv/bin/python" "$ROOT/backend/.venv/Scripts/python.exe" python3 python; do
  if "$c" -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Forkcast needs Python 3.11 or newer: https://www.python.org/downloads/"
  exit 1
fi
if ! "$PY" -c 'import fastapi, uvicorn, pywebpush' 2>/dev/null; then
  echo "Installing the backend's Python packages into backend/.venv (one-time step)..."
  [ -d backend/.venv ] || "$PY" -m venv backend/.venv
  PY="$ROOT/backend/.venv/bin/python"
  [ -x "$PY" ] || PY="$ROOT/backend/.venv/Scripts/python.exe"
  "$PY" -m pip install -r backend/requirements.txt
fi

# ---- Node.js and the website packages (no global pnpm needed) ----
if ! command -v node >/dev/null 2>&1; then
  echo "Forkcast needs Node.js 20 or newer: https://nodejs.org/"
  exit 1
fi
if [ ! -f web/node_modules/next/dist/bin/next ]; then
  echo "Installing the website's packages (one-time step, takes a few minutes)..."
  (cd web && npx --yes pnpm@12 install)
fi

# ---- run both; Ctrl+C, or either one stopping, stops the other ----
BACKEND_PID="" WEB_PID=""
trap 'kill $BACKEND_PID $WEB_PID 2>/dev/null || true; wait' EXIT
trap 'exit 130' INT TERM

echo "Backend : http://localhost:${BACKEND_PORT}   [python: $PY]"
(cd backend && exec "$PY" -m uvicorn app:app --port "$BACKEND_PORT") &
BACKEND_PID=$!
echo "Website : http://localhost:${FRONTEND_PORT}"
(cd web && exec node node_modules/next/dist/bin/next dev --port "$FRONTEND_PORT") &
WEB_PID=$!

echo ""
echo "  Open http://localhost:${FRONTEND_PORT}   (Ctrl+C stops both)"
echo ""
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do sleep 1; done
echo "One of the servers stopped (see above), so the other one is being stopped too."
