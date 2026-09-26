"""Unified dev server runner for StoryWeaver.

Runs both FastAPI (port 8001) and Vite (port 5173) in one terminal,
and cleanly terminates both on Ctrl+C.

    python scripts/dev.py               # backend restarts itself when its code changes
    python scripts/dev.py --no-reload   # for a long writing session: it never restarts

Auto-reload is on by default, so a backend edit (code or prompt) shows up
without restarting anything. A generation runs for minutes, and a reload kills
it partway (it resumes from its checkpoint) — use `--no-reload` when writing
chapters rather than editing the app.

The reloading is done here, not by `uvicorn --reload`. On Windows uvicorn stops
the old server by sending a console Ctrl+C event, and that event goes to every
process sharing the console: it either never lands, so the log says
"Reloading..." and stale code keeps answering, or it lands on this script and on
Vite too and takes everything down. Here the backend's own process tree is
killed and started again, and nothing else is touched.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
VENV_UVICORN = ROOT_DIR / ".venv" / "Scripts" / "uvicorn.exe"

if not VENV_UVICORN.exists():
    # Fallback to system uvicorn if not in standard venv location
    UVICORN_CMD = ["uvicorn"]
else:
    UVICORN_CMD = [str(VENV_UVICORN)]

IS_WIN = sys.platform == "win32"

# What counts as a backend change: code, and the prompts, which are Markdown.
# A prompt edit that did not reload would look exactly like a prompt edit that
# did not work.
WATCHED_SUFFIXES = (".py", ".md")


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


def _kill_tree(proc: subprocess.Popen) -> None:
    """Stop a process and everything it started, without touching anyone else."""
    if proc.poll() is not None:
        return
    try:
        if IS_WIN:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True
            )
        else:
            proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        pass


def _is_watched(path: str) -> bool:
    return path.endswith(WATCHED_SUFFIXES) and "__pycache__" not in path


class Backend:
    """The backend process, which the watcher may replace at any time."""

    # `--app-dir backend` makes the import work even without an editable
    # install, which is what broke when `src/` was renamed.
    CMD = UVICORN_CMD + ["storyweaver.server:app", "--app-dir", "backend", "--port", "8001"]

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc = self._start()
        # Set while a restart is deliberately stopping the process, so the main
        # loop does not mistake it for a crash.
        self.restarting = False

    def _start(self) -> subprocess.Popen:
        return subprocess.Popen(self.CMD, cwd=str(ROOT_DIR), shell=IS_WIN)

    def restart(self, changed: list[str]) -> None:
        with self.lock:
            self.restarting = True
            shown = ", ".join(changed[:3]) + (" …" if len(changed) > 3 else "")
            print(f"\n🔁 Backend changed ({shown}) — restarting the backend...\n")
            _kill_tree(self.proc)
            self.proc = self._start()
            self.restarting = False

    def stop(self) -> None:
        with self.lock:
            _kill_tree(self.proc)


def _watch(backend: Backend, stop: threading.Event) -> None:
    from watchfiles import watch

    for changes in watch(
        BACKEND_DIR,
        watch_filter=lambda _change, path: _is_watched(path),
        stop_event=stop,
    ):
        changed = sorted({str(Path(path).relative_to(ROOT_DIR)) for _change, path in changes})
        try:
            backend.restart(changed)
        except Exception as error:  # noqa: BLE001 — never let one bad restart end reloading
            print(f"\n⚠ Could not restart the backend: {error}\n")


def main() -> None:
    # A Korean Windows console or a pipe may be cp949, which cannot print the
    # emoji below — and a print that raises inside the watcher thread would
    # silently end auto-reload.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    print("\n========================================================")
    print("🚀 Starting StoryWeaver (FastAPI + Vite React TS)")
    print("========================================================\n")

    # On by default; `--no-reload` turns it off. (`--reload` is still accepted,
    # from when it was opt-in, and changes nothing.)
    reload = "--no-reload" not in sys.argv[1:]
    if reload:
        try:
            import watchfiles  # noqa: F401 — installed with uvicorn[standard]
        except ImportError:
            reload = False
            print("⚠ watchfiles is not installed, so auto-reload is OFF.")
            print("  pip install \"uvicorn[standard]\" to turn it on.\n")

    print("▶ Starting FastAPI backend on http://localhost:8001 ...")
    backend = Backend()

    # Brief pause to let backend bind port
    time.sleep(1.5)

    print("▶ Starting Vite frontend on http://localhost:5173 ...")
    frontend_proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=str(FRONTEND_DIR),
        shell=IS_WIN,  # Windows shell=True for npm
    )

    stop_watching = threading.Event()
    if reload:
        threading.Thread(target=_watch, args=(backend, stop_watching), daemon=True).start()

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
    if reload:
        print("🔁 Auto-reload is ON: saving a backend file (code or prompt) restarts the")
        print("   backend only. That interrupts a generation in progress (it resumes from")
        print("   its checkpoint). Use --no-reload for a long writing session.")
    else:
        print("⏸ Auto-reload is OFF: restart this script to pick up backend changes.")
    print("Press Ctrl+C to stop both servers.\n")

    def shutdown(signum=None, frame=None):
        print("\n🛑 Stopping servers...")
        stop_watching.set()
        backend.stop()
        _kill_tree(frontend_proc)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    reported_exit: subprocess.Popen | None = None
    try:
        while True:
            with backend.lock:
                proc, restarting = backend.proc, backend.restarting
            code = proc.poll()
            if code is not None and not restarting and proc is not reported_exit:
                if reload:
                    # Most often a syntax error in the file just saved. Keep the
                    # frontend up; the next save starts the backend again.
                    print(f"\n⚠ Backend exited with code {code}. Fix the error and save —")
                    print("  it restarts on the next change. (Ctrl+C to stop everything.)\n")
                    reported_exit = proc
                else:
                    print(f"Backend exited with code {code}")
                    shutdown()
            if frontend_proc.poll() is not None:
                print(f"Frontend exited with code {frontend_proc.returncode}")
                shutdown()
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
