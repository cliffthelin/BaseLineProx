"""Install the harness CLIs the drive's offline cache did not carry, once the internet is reachable.

The installer's offline cache is the first source (provision.sh installs from it). A cache built before OpenCode and OpenAI Codex were
added lacks them; this closes that gap from the network when it comes up, without ever failing an installation or a boot.
"""
from __future__ import annotations

import shutil
import socket
import subprocess

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
