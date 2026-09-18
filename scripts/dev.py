"""Unified dev server runner for StoryWeaver.

Runs both FastAPI (port 8001) and Vite (port 5173) in one terminal,
and cleanly terminates both on Ctrl+C.

    python scripts/dev.py            # for writing: the backend never restarts itself
    python scripts/dev.py --reload   # for editing backend code

Auto-reload is off by default, on purpose. A generation runs for minutes, and a
reload kills it partway. Worse, on Windows a reload can hang outright: uvicorn
logs "Reloading..." and the old process never exits, so the server keeps
serving stale code — or, once it does go, nothing comes back up. Neither is
something an author should meet in the middle of a chapter.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
VENV_UVICORN = ROOT_DIR / ".venv" / "Scripts" / "uvicorn.exe"

if not VENV_UVICORN.exists():
    # Fallback to system uvicorn if not in standard venv location
    UVICORN_CMD = ["uvicorn"]
else:
    UVICORN_CMD = [str(VENV_UVICORN)]


def _wait_for_backend(timeout: float) -> bool:
    """Poll /api/health until the backend answers, or the timeout passes."""
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=2):
                return True
        except OSError:
            time.sleep(1)
    return False


def main() -> None:
    print("\n========================================================")
    print("🚀 Starting StoryWeaver (FastAPI + Vite React TS)")
    print("========================================================\n")

    # `--app-dir backend` makes the import work even without an editable
    # install, which is what broke when `src/` was renamed.
    backend_cmd = UVICORN_CMD + [
        "storyweaver.server:app",
        "--app-dir",
        "backend",
        "--port",
        "8001",
    ]
    if "--reload" in sys.argv[1:]:
        # Opt-in, for backend work. Watching only the backend package keeps an
        # edit to a test, a script or the frontend from restarting the server.
        backend_cmd += ["--reload", "--reload-dir", "backend"]
        print("⚠ Auto-reload is ON: saving a backend file restarts the server and")
        print("  interrupts any generation in progress (it resumes from its checkpoint).\n")

    frontend_cmd = ["npm", "run", "dev"]

    # Windows shell=True for npm
    is_win = sys.platform == "win32"

    print("▶ Starting FastAPI backend on http://localhost:8001 ...")
    backend_proc = subprocess.Popen(
        backend_cmd,
        cwd=str(ROOT_DIR),
        shell=is_win,
    )

    # Brief pause to let backend bind port
    time.sleep(1.5)

    print("▶ Starting Vite frontend on http://localhost:5173 ...")
    frontend_proc = subprocess.Popen(
        frontend_cmd,
        cwd=str(FRONTEND_DIR),
        shell=is_win,
    )

    # The backend loads ChromaDB before it answers anything — about 10–20 s. A
    # generation started before then is refused, so say "ready" only once it is.
    print("⏳ Waiting for the backend to load memory (ChromaDB)...")
    ready = _wait_for_backend(timeout=90)
    if ready:
        print("\n✅ Both servers are running!")
    else:
        print("\n⚠ The backend did not answer within 90 s — check the log above.")
    print("👉 Open your browser at: http://localhost:5173")
    print("👉 Backend API docs at:  http://localhost:8001/docs\n")
    print("Press Ctrl+C to stop both servers.\n")

    def shutdown(signum=None, frame=None):
        print("\n🛑 Stopping servers...")
        try:
            if is_win:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(backend_proc.pid)], capture_output=True)
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(frontend_proc.pid)], capture_output=True)
            else:
                backend_proc.terminate()
                frontend_proc.terminate()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            # Check if any process exited unexpectedly
            b_poll = backend_proc.poll()
            f_poll = frontend_proc.poll()
            if b_poll is not None:
                print(f"Backend exited with code {b_poll}")
                shutdown()
                break
            if f_poll is not None:
                print(f"Frontend exited with code {f_poll}")
                shutdown()
                break
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
