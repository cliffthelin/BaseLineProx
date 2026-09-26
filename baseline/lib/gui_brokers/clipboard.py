"""Clipboard broker (Track B3) - wraps `wl-copy`/`wl-paste` (lightweight,
Wayland-native CLI tools, no portal or D-Bus needed) through the same
Runner-injectable subprocess boundary repair.py established. See
docs/design/milestone-2-gui-plan.md.
"""
from __future__ import annotations

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError


def read_clipboard(runner: Runner) -> str:
    proc = runner.run(["wl-paste", "-n"], timeout=5)
    return proc.stdout if proc.returncode == 0 else ""


def write_clipboard(runner: Runner, text: str) -> bool:
    proc = runner.run(["wl-copy", text], timeout=5)
    return proc.returncode == 0
