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

NGROK_DOMAIN = "deuce-scouting-outbid.ngrok-free.dev"
NGROK_PORT = 5000


def find_ngrok():
    """Find ngrok.exe in PATH or common Windows locations."""
    exe = shutil.which("ngrok")
    if exe:
        return exe

    home = Path.home()
    candidates = [
        home / "ngrok" / "ngrok.exe",
        home / "AppData" / "Local" / "ngrok" / "ngrok.exe",
        home / "Downloads" / "ngrok" / "ngrok.exe",
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
        [ngrok_path, "http", f"--domain={NGROK_DOMAIN}", str(NGROK_PORT)],
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

    ngrok_path = find_ngrok()
    if not ngrok_path:
        log("ERROR: ngrok.exe not found.")
        log("Please install ngrok and make sure it is in PATH, or set NGROK_PATH environment variable.")
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
        while running:
            if backend is None or backend.poll() is not None:
                if backend is not None and backend.poll() is not None:
                    log(f"Backend exited with code {backend.poll()}, restarting...")
                backend = start_backend()

            if ngrok is None or ngrok.poll() is not None:
                if ngrok is not None and ngrok.poll() is not None:
                    log(f"Ngrok exited with code {ngrok.poll()}, restarting...")
                ngrok = start_ngrok(ngrok_path)

            time.sleep(5)
    finally:
        terminate(backend)
        terminate(ngrok)
        log("Watchdog exited")


if __name__ == "__main__":
    main()
