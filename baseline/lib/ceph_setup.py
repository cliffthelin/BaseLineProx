"""Installing Ceph on the Proxmox host through Proxmox's own tool (`pveceph install`), in the background, with a state a page can show.

Only the packages. Creating a Ceph cluster (monitors, OSDs, a pool) is a deliberate step with consequences for the drives involved and is
not done here. The tool fetches from Proxmox's repository, so it needs the internet; without it the job fails with that said plainly.
"""
from __future__ import annotations

import subprocess
import threading


class _Real:
    def run(self, argv, timeout=1800):
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def is_installed(runner=None) -> bool:
    runner = runner or _Real()
    try:
        return runner.run(["dpkg-query", "-W", "-f=${Package} ${Version}", "ceph-common"], timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class InstallJob:
    def __init__(self, runner=None):
        self.runner = runner or _Real()
        self._lock = threading.Lock()
        self._state = {"phase": "idle", "message": ""}

    def state(self):
        with self._lock:
            return dict(self._state)

    def _set(self, phase, message=""):
        with self._lock:
            self._state = {"phase": phase, "message": message}

    def start(self):
        if self.state()["phase"] == "running":
            return
        self._set("running", "installing Ceph packages (this takes several minutes)")
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            if is_installed(self.runner):
                self._set("done", "Ceph is already installed")
                return
            done = self.runner.run(["pveceph", "install", "--repository", "no-subscription"], timeout=3600)
        except (OSError, subprocess.SubprocessError) as exc:
            self._set("failed", f"the install could not run: {exc}")
            return
        if done.returncode == 0:
            self._set("done", "Ceph packages installed; create monitors and OSDs from node > Ceph in Proxmox when ready")
        else:
            detail = (done.stderr or done.stdout or "").strip()[-200:]
            self._set("failed", "the install failed; it needs the internet to reach download.proxmox.com. " + detail)
