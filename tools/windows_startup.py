#!/usr/bin/env python3
"""
K-Sites Windows startup watchdog.

Starts the Flask backend and ngrok, then keeps them running.
Restart either process if it exits unexpectedly.

Usage:
    python tools/windows_startup.py

Or via the batch wrapper:
    start_ksites_windows.bat
"""
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBAPP = ROOT / "webapp"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

BACKEND_LOG = LOG_DIR / "backend.log"
NGROK_LOG = LOG_DIR / "ngrok.log"
WATCHDOG_LOG = LOG_DIR / "watchdog.log"

NGROK_DOMAIN = os.environ.get("NGROK_DOMAIN", "deuce-scouting-outbid.ngrok-free.dev")
NGROK_PORT = int(os.environ.get("NGROK_PORT", "5000"))

PID_FILE = LOG_DIR / "watchdog.pid"


def _is_process_alive(pid):
    """Return True if a process with pid is still running (Windows and Unix)."""
    if pid is None:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            kernel = ctypes.windll.kernel32
            handle = kernel.OpenProcess(1, False, pid)  # PROCESS_TERMINATE
            if handle:
                kernel.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _another_instance_running():
    """Check whether another watchdog is already running and return its PID if so."""
    if not PID_FILE.exists():
        return None
    try:
        other_pid = int(PID_FILE.read_text(encoding="utf-8").strip() or 0)
    except Exception:
        return None
    if other_pid == os.getpid():
        return None
    if other_pid and _is_process_alive(other_pid):
        return other_pid
    # Stale lock file
    try:
        PID_FILE.unlink()
    except Exception:
        pass
    return None


def _write_lock():
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception as e:
        log(f"WARNING: could not write PID file: {e}")


def _remove_lock():
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception:
        pass


def find_ngrok():
    """Find ngrok.exe in PATH or common Windows locations."""
    exe = shutil.which("ngrok")
    if exe:
        return exe

    home = Path.home()
    candidates = [
        ROOT / "ngrok.exe",
        home / "ngrok" / "ngrok.exe",
        home / "AppData" / "Local" / "ngrok" / "ngrok.exe",
        home / "Downloads" / "ngrok" / "ngrok.exe",
        home / "Downloads" / "ngrok.exe",
        home / "Desktop" / "ngrok.exe",
        Path("C:") / "Program Files" / "ngrok" / "ngrok.exe",
        Path("C:") / "ngrok" / "ngrok.exe",
    ]
    env_path = os.environ.get("NGROK_PATH")
    if env_path:
        candidates.insert(0, Path(env_path))

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def log(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def start_backend():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    if not env.get("K_SITES_NCBI_EMAIL"):
        env["K_SITES_NCBI_EMAIL"] = "user@example.com"

    python = str(ROOT / ".venv" / "Scripts" / "python.exe")
    if not Path(python).exists():
        python = sys.executable

    log(f"Starting backend with {python}")
    return subprocess.Popen(
        [python, "app.py"],
        cwd=WEBAPP,
        env=env,
        stdout=open(BACKEND_LOG, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )


def start_ngrok(ngrok_path):
    log(f"Starting ngrok: {ngrok_path}")
    return subprocess.Popen(
        [ngrok_path, "http", f"--url={NGROK_DOMAIN}", str(NGROK_PORT)],
        cwd=ROOT,
        stdout=open(NGROK_LOG, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )


def terminate(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
            proc.wait(timeout=5)
        else:
            proc.terminate()
            proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main():
    log("K-Sites startup watchdog starting")

    other_pid = _another_instance_running()
    if other_pid:
        log(f"ERROR: another watchdog is already running (PID {other_pid}). Exiting.")
        sys.exit(0)

    _write_lock()

    ngrok_path = find_ngrok()
    if not ngrok_path:
        log("ERROR: ngrok.exe not found.")
        log("Please install ngrok and make sure it is in PATH, or set NGROK_PATH environment variable.")
        _remove_lock()
        sys.exit(1)
    log(f"Found ngrok at {ngrok_path}")

    backend = None
    ngrok = None
    running = True

    def shutdown(signum, frame):
        nonlocal running
        running = False
        log("Shutdown signal received, stopping processes...")
        terminate(backend)
        terminate(ngrok)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        tick = 0
        while running:
            backend_restarted = False
            ngrok_restarted = False

            if backend is None or backend.poll() is not None:
                if backend is not None:
                    log(f"Backend exited with code {backend.poll()}, restarting...")
                backend = start_backend()
                backend_restarted = True
                time.sleep(3)  # give backend a moment before starting ngrok

            if ngrok is None or ngrok.poll() is not None:
                if ngrok is not None:
                    log(f"Ngrok exited with code {ngrok.poll()}, restarting...")
                ngrok = start_ngrok(ngrok_path)
                ngrok_restarted = True

            tick += 1
            if tick % 6 == 0 or backend_restarted or ngrok_restarted:
                backend_pid = backend.pid if backend and backend.poll() is None else "dead"
                ngrok_pid = ngrok.pid if ngrok and ngrok.poll() is None else "dead"
                health = "unknown"
                try:
                    import urllib.request
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{NGROK_PORT}/api/health",
                        headers={"ngrok-skip-browser-warning": "1"},
                        method="GET",
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        health = "ok" if resp.status == 200 else f"status_{resp.status}"
                except Exception as e:
                    health = f"error: {type(e).__name__}"
                log(f"Status — backend PID={backend_pid}, ngrok PID={ngrok_pid}, health={health}")

            time.sleep(5)
    finally:
        terminate(backend)
        terminate(ngrok)
        _remove_lock()
        log("Watchdog exited")


if __name__ == "__main__":
    main()
