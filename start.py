"""One-command launcher. Starts FastAPI backend + serves frontend + opens browser.

Usage:  python start.py
Stops both on Ctrl+C.
"""
import os
import sys
import time
import signal
import subprocess
import threading
import webbrowser
import http.server
import socketserver
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
BACKEND = ROOT / "backend"
# Legacy CDN frontend lives in frontend/index.html; the real Next.js app is web/.
# Prefer web/ when it exists so `python start.py` doesn't serve the wrong UI.
FRONTEND = (ROOT / "web") if (ROOT / "web").exists() else (ROOT / "frontend")
API_PORT = 8000
WEB_PORT = 5500

procs = []


def wait_for_api(url, timeout=25):
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            # 404/405 still means server is up
            try:
                urllib.request.urlopen(url, timeout=2)
            except urllib.error.HTTPError:
                return True
            except Exception:
                pass
        time.sleep(0.5)
    return False


def start_backend():
    print(f"[api]  starting FastAPI on :{API_PORT} ...")
    env = dict(os.environ, PYTHONUTF8="1")
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--port", str(API_PORT)],
        cwd=str(BACKEND), env=env,
    )
    procs.append(p)


def start_frontend():
    """Serve frontend/ over http so fetch() to the API isn't blocked by file:// CORS."""
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(FRONTEND), **k)
        def log_message(self, *a):
            pass

    def serve():
        with socketserver.TCPServer(("", WEB_PORT), Handler) as httpd:
            httpd.serve_forever()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    print(f"[web]  serving frontend on :{WEB_PORT}")


def shutdown(*_):
    print("\nshutting down ...")
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, shutdown)
    start_backend()
    start_frontend()

    api_health = f"http://localhost:{API_PORT}/docs"
    if wait_for_api(api_health):
        print(f"[api]  ready -> {api_health}")
    else:
        print("[api]  WARNING: did not become ready in time (check backend logs)")

    url = f"http://localhost:{WEB_PORT}/index.html"
    print(f"\n  Meal Planner running:")
    print(f"    UI   {url}")
    print(f"    API  http://localhost:{API_PORT}/docs")
    print(f"\n  Ctrl+C to stop.\n")
    webbrowser.open(url)

    # keep alive
    try:
        while True:
            time.sleep(1)
            for p in procs:
                if p.poll() is not None:
                    print("[api]  backend exited unexpectedly.")
                    shutdown()
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
