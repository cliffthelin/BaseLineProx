"""Install the harness CLIs the drive's offline cache did not carry, once the internet is reachable.

The installer's offline cache is the first source (provision.sh installs from it). A cache built before OpenCode and OpenAI Codex were
added lacks them; this closes that gap from the network when it comes up, without ever failing an installation or a boot.
"""
from __future__ import annotations

import shutil
import socket
import subprocess

# Sound and Bluetooth for the host's own browser session (operator, 2026-10-14: audio and Bluetooth input/output and tether in the Proxmox GUI):
# the sound server, the Bluetooth stack and the plugin that joins them. Installed once online when the offline cache did not carry them.
APT_PACKAGES = ["pipewire", "pipewire-pulse", "wireplumber", "bluez", "libspa-0.2-bluetooth"]
PACKAGES = {"claude": "@anthropic-ai/claude-code", "opencode": "opencode-ai", "codex": "@openai/codex"}


def _online():
    try:
        socket.create_connection(("registry.npmjs.org", 443), timeout=5).close()
        return True
    except OSError:
        return False


class _Real:
    def run(self, argv, timeout=600):
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def run_once(*, which=shutil.which, connect=_online, runner=None) -> dict:
    missing = [name for name in PACKAGES if not which(name)]
    if not missing:
        return {"state": "nothing_missing", "installed": []}
    if not connect():
        return {"state": "waiting_for_internet", "missing": missing}
    runner = runner or _Real()
    installed, failed = [], {}
    for name in missing:
        done = runner.run(["npm", "install", "-g", PACKAGES[name]])
        if done.returncode == 0:
            installed.append(name)
        else:
            failed[name] = (done.stderr or "").strip()[-160:]
    return {"state": "installed" if not failed else "partly_failed", "installed": installed, "failed": failed}


def _apt_installed(package: str) -> bool:
    done = subprocess.run(["dpkg-query", "-W", "-f=${Status}", package], capture_output=True, text=True)
    return done.returncode == 0 and "install ok installed" in done.stdout


def run_extras(*, installed=_apt_installed, connect=_online, runner=None) -> dict:
    missing = [p for p in APT_PACKAGES if not installed(p)]
    if not missing:
        return {"state": "nothing_missing", "installed": []}
    if not connect():
        return {"state": "waiting_for_internet", "missing": missing}
    runner = runner or _Real()
    done = runner.run(["apt-get", "install", "-y", "--no-install-recommends", *missing], timeout=1800)
    if done.returncode == 0:
        return {"state": "installed", "installed": missing}
    return {"state": "failed", "installed": [], "failed": (done.stderr or "").strip()[-200:]}
