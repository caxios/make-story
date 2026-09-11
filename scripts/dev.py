"""Unified dev server runner for StoryWeaver.

Runs both FastAPI (port 8001) and Vite (port 5173) in one terminal,
and cleanly terminates both on Ctrl+C.
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


def main() -> None:
    print("\n========================================================")
    print("🚀 Starting StoryWeaver (FastAPI + Vite React TS)")
    print("========================================================\n")

    backend_cmd = UVICORN_CMD + [
        "storyweaver.server:app",
        "--reload",
        "--port",
        "8001",
    ]

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

    print("\n✅ Both servers are running!")
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
