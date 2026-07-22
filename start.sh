#!/usr/bin/env bash
# One-command launcher: FastAPI backend (:8343) + Next.js frontend (:6001).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BACKEND_PORT="${BACKEND_PORT:-8343}"
FRONTEND_PORT="${FRONTEND_PORT:-6001}"   # 6000 is blocked by browsers/Next (x11 reserved)

# ---- pick backend python (prefer the uv venv) ----
pick_python() {
  if [ -n "${PYTHON:-}" ]; then echo "$PYTHON"; return; fi
  if [ -x "backend/.venv/Scripts/python.exe" ]; then echo "backend/.venv/Scripts/python.exe"; return; fi
  if [ -x "backend/.venv/bin/python" ]; then echo "backend/.venv/bin/python"; return; fi
  for c in python3 python py; do
    if command -v "$c" >/dev/null 2>&1; then echo "$c"; return; fi
  done
  echo ""; return
}
PY="$(pick_python)"
if [ -z "$PY" ]; then
  echo "No Python found. Set up the backend venv first:"
  echo "  cd backend && uv venv && uv pip install -r requirements.txt"
  exit 1
fi

pids=()
cleanup() {
  echo ""
  echo "Stopping..."
  for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done
  exit 0
}
trap cleanup INT TERM

echo "Backend  (FastAPI) : http://localhost:${BACKEND_PORT}   [python: $PY]"
( cd backend && exec "$PY" -m uvicorn app:app --port "$BACKEND_PORT" ) &
pids+=($!)

# ---- frontend ----
if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm not found. Install it: npm i -g pnpm"
  cleanup
fi
if [ ! -d "web/node_modules" ]; then
  echo "Installing web dependencies (first run)..."
  ( cd web && pnpm install )
fi
echo "Frontend (Next.js) : http://localhost:${FRONTEND_PORT}"
( cd web && exec pnpm dev --port "$FRONTEND_PORT" ) &
pids+=($!)

echo ""
echo "  Open  http://localhost:${FRONTEND_PORT}"
echo "  Ctrl+C to stop both."
echo ""

# wait for either to exit
wait -n 2>/dev/null || wait
cleanup
