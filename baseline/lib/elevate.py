"""The application asks the system for root itself when a stage needs it, so nobody wraps it in a command of their own.

A graphical session gets Ubuntu's own authentication dialog (pkexec); otherwise sudo asks on the terminal. The person types their password to the system, never to this program, and the same
command line (the same stages, the same typed wipe confirmation) is re-run as root, nothing more. Only the BASELINE_* settings and PATH are carried across.
"""
from __future__ import annotations

import os
import shutil
import sys

CARRIED_PREFIX = "BASELINE_"


def elevation_argv(argv, environ, *, which=shutil.which, euid=None, python=sys.executable):
    """The command that re-runs `argv` as root, or None when already root or no way to ask is installed."""
    if (os.geteuid() if euid is None else euid) == 0:
        return None
    carried = [f"{k}={v}" for k, v in sorted(environ.items()) if k.startswith(CARRIED_PREFIX) or k == "PATH"]
    graphical = bool(environ.get("DISPLAY") or environ.get("WAYLAND_DISPLAY"))
    if graphical and which("pkexec"):
        return ["pkexec", "env", f"HOME={environ.get('HOME', '/root')}", *carried, python, *argv]
    if which("sudo"):
        return ["sudo", "env", *carried, python, *argv]
    return None


def elevate_or_return(argv, environ=None):
    """Replace this process with the root re-run; returns only when there is no way to ask."""
    cmd = elevation_argv(argv, os.environ if environ is None else environ)
    if cmd:
        os.execvp(cmd[0], cmd)
