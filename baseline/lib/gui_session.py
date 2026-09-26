"""Runner-injectable lifecycle for one compositor+app GUI session (Track
B3 - see docs/design/milestone-2-gui-plan.md's "local routing for future
app-sandbox work"). Mirrors `drive_setup_install.py`'s already-proven
`InstallRunner`/process pattern (spawn via `subprocess.Popen` with
`start_new_session=True`, kill via `os.killpg`) rather than `repair.py`'s
`Runner.run()`, which is synchronous and unsuited to a long-running
compositor process.

Deliberately generic (session name + argv + env, not hardcoded to
Chromium) so a future second app reuses `start`/`stop`/`restart` unchanged
- `cage`'s own model is one session per app, never several sharing one
compositor, so "switching apps" is stopping one session and starting
another on the same dedicated GUI VT, never running two at once.
"""
from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass


class SessionRunner:
    def spawn(self, argv: list[str], env: dict | None = None) -> "SessionProcess":
        raise NotImplementedError


class SessionProcess:
    def poll(self) -> int | None:
        raise NotImplementedError

    def kill(self) -> None:
        raise NotImplementedError


class RealSessionRunner(SessionRunner):
    def spawn(self, argv: list[str], env: dict | None = None) -> "SessionProcess":
        return _RealSessionProcess(argv, env)


class _RealSessionProcess(SessionProcess):
    def __init__(self, argv: list[str], env: dict | None):
        full_env = {**os.environ, **(env or {})}
        self._proc = subprocess.Popen(argv, env=full_env, start_new_session=True)

    def poll(self) -> int | None:
        return self._proc.poll()

    def kill(self) -> None:
        try:
            os.killpg(self._proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


@dataclass
class SessionHandle:
    name: str
    process: SessionProcess


def start(runner: SessionRunner, *, name: str, command: list[str], env: dict | None = None) -> SessionHandle:
    process = runner.spawn(command, env=env)
    return SessionHandle(name=name, process=process)


def is_running(handle: SessionHandle) -> bool:
    return handle.process.poll() is None


def stop(handle: SessionHandle) -> bool:
    handle.process.kill()
    return True


def restart(runner: SessionRunner, handle: SessionHandle, *, command: list[str], env: dict | None = None) -> SessionHandle:
    stop(handle)
    return start(runner, name=handle.name, command=command, env=env)
