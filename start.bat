@echo off
REM One-command launcher (Windows): FastAPI backend (:8343) + Next.js frontend (:6001).
setlocal
cd /d "%~dp0"

set "BACKEND_PORT=8343"
set "FRONTEND_PORT=6001"

REM pick backend python (prefer uv venv)
set "PY=python"
if exist "backend\.venv\Scripts\python.exe" set "PY=backend\.venv\Scripts\python.exe"

echo Backend  : http://localhost:%BACKEND_PORT%
start "meal-backend" cmd /c "cd backend && %PY% -m uvicorn app:app --port %BACKEND_PORT%"

if not exist "web\node_modules" (
  echo Installing web dependencies ^(first run^)...
  pushd web && call pnpm install && popd
)

echo Frontend : http://localhost:%FRONTEND_PORT%
start "meal-frontend" cmd /c "cd web && pnpm dev --port %FRONTEND_PORT%"

echo.
echo   Open http://localhost:%FRONTEND_PORT%
echo   Close the two spawned windows to stop.
endlocal
