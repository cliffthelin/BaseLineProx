"""One launcher for Baseline: open the web application, starting its service first if it is not running.

It does exactly two things: start `baseline-web.service` (through pkexec, so the operator's own password is asked by
the system, never by this program) and open the local page in the browser. Everything else happens inside the web
application, behind its login.
"""
from __future__ import annotations

import os
import shutil
import subprocess
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


def _start_service() -> bool:
    pkexec = shutil.which("pkexec")
    if pkexec is None:
        return False
    return subprocess.run([pkexec, "systemctl", "start", SERVICE], timeout=120).returncode == 0


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
    if not is_installed():
        notify("Baseline is not installed on this machine yet, so there is nothing to open.")
        return 1
    if not start_service():
        notify("Baseline could not be started (the start was not permitted or failed).")
        return 1
    deadline = clock() + WAIT_S
    while clock() < deadline:
        if probe(url):
            open_page(url)
            return 0
        sleep(POLL_S)
    notify(f"Baseline did not start within {WAIT_S} seconds. Check: systemctl status {SERVICE}")
    return 1
