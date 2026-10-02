"""One launcher for Baseline: open the web application, starting its service first if it is not running.

It does exactly two things: start `baseline-web.service` (through pkexec, so the operator's own password is asked by
the system, never by this program) and open the local page in the browser. Everything else happens inside the web
application, behind its login.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8100/"
SERVICE = "baseline-web.service"
WAIT_S = 45
POLL_S = 1.5


def _probe(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "login", timeout=3) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        return exc.code < 500            # any answer at all means the server is up
    except (urllib.error.URLError, OSError):
        return False


def _is_installed() -> bool:
    return os.path.exists(f"/etc/systemd/system/{SERVICE}") or os.path.exists(f"/usr/lib/systemd/system/{SERVICE}")


def _run_app_directly() -> bool:
    """No service installed (dev machine): run the web app as its own detached process so it outlives the launcher."""
    app = os.path.join(os.path.dirname(os.path.realpath(__file__)), "baseline_web.py")
    if not os.path.exists(app):
        return False
    try:
        subprocess.Popen([sys.executable, app], cwd=os.path.dirname(app), start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


def _start_service() -> bool:
    """Start the app via systemd if installed, otherwise run directly from Python."""
    pkexec = shutil.which("pkexec")
    if pkexec is not None and _is_installed():
        # Try systemd first if pkexec is available
        if subprocess.run([pkexec, "systemctl", "start", SERVICE], timeout=120, capture_output=True).returncode == 0:
            return True
    # Fallback: run the app directly (works on dev machines)
    return _run_app_directly()


def _open_page(url: str) -> None:
    opener = shutil.which("xdg-open")
    if opener:
        subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _notify(text: str) -> None:
    sender = shutil.which("notify-send")
    if sender:
        subprocess.run([sender, "-a", "Baseline", "Baseline", text], timeout=10)
    else:
        print(text)


def launch(*, probe=_probe, is_installed=_is_installed, start_service=_start_service, open_page=_open_page,
           notify=_notify, sleep=time.sleep, clock=time.monotonic, url: str = URL) -> int:
    if probe(url):
        open_page(url)
        return 0
    # Start the app (via systemd if installed, otherwise run directly from Python)
    if not start_service():
        notify("Baseline could not be started.")
        return 1
    deadline = clock() + WAIT_S
    while clock() < deadline:
        if probe(url):
            open_page(url)
            return 0
        sleep(POLL_S)
    notify(f"Baseline did not start within {WAIT_S} seconds.")
    return 1
