"""Browser-guided sign-in to an AI provider, the way commercial products do it (operator, 2026-10-12): the person is sent to the
provider's own site, signs in and grants access there, and Baseline finishes the setup.

How it works for a provider whose CLI has a sign-in flow (Claude Code's `claude setup-token`): the CLI runs under a terminal; the
sign-in link it prints is shown on the page (and only if it is on the provider's own site); the person signs in there and is given a
code; the code is passed back to the CLI; the token the CLI prints is written straight into the vault. The token is never in any state
the page can read, and nothing it prints is logged.

Providers whose keys are issued from an account page (no third-party sign-in grant exists for them) use the paste path instead: a link
to the key page and a field whose value goes to the vault (`/ai-setup`).
"""
from __future__ import annotations

import os
import pty
import re
import select
import signal
import subprocess
import threading
import time

_ANSI = re.compile(r"\x1b\[[0-9;?>]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[78=>]")
_URL = re.compile(r"https://[^\s\"'<>\x1b]+")
_TOKEN = re.compile(r"sk-ant-oat01-[A-Za-z0-9_-]{20,}")


class SetupError(RuntimeError):
    pass


class GuidedSetup:
    def __init__(self, argv, vault, secret_name, *, allowed_url_prefix, token_pattern=_TOKEN, wait_seconds=30, total_seconds=900):
        self.argv, self.vault, self.secret_name = list(argv), vault, secret_name
        self.allowed_url_prefix, self.token_pattern = allowed_url_prefix, token_pattern
        self.wait_seconds, self.total_seconds = wait_seconds, total_seconds
        self._lock = threading.Lock()
        self._phase, self._url, self._message = "idle", None, ""
        self._pid = self._fd = self._proc = None
        self._cancelled = False

    def state(self) -> dict:
        with self._lock:
            return {"phase": self._phase, "url": self._url, "message": self._message}

    def _set(self, phase, message="", url=None):
        with self._lock:
            self._phase, self._message = phase, message
            if url is not None:
                self._url = url

    def start(self):
        if self._phase != "idle":
            raise SetupError("this setup was already started")
        self._set("starting")
        # A terminal for the CLI through subprocess (posix_spawn/vfork), not pty.fork(): this runs inside a threaded web server, where
        # forking the interpreter can deadlock the child.
        try:
            master, slave = pty.openpty()
        except OSError as exc:
            self._set("failed", f"cannot open a terminal: {exc.strerror}")
            return
        try:
            self._proc = subprocess.Popen(self.argv, stdin=slave, stdout=slave, stderr=slave, start_new_session=True, close_fds=True)
        except OSError as exc:
            os.close(master)
            os.close(slave)
            self._set("failed", f"the provider's tool could not be started: {exc.strerror}")
            return
        os.close(slave)
        self._fd, self._pid = master, self._proc.pid
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        buffer, started = "", time.time()
        while True:
            if self._cancelled or self._fd is None:
                return
            if time.time() - started > self.total_seconds:
                self._finish_failed("the sign-in took too long and was stopped")
                return
            try:
                ready, _, _ = select.select([self._fd], [], [], 0.2)
            except (OSError, ValueError, TypeError):
                return                                  # the terminal was closed by terminate()
            if not ready:
                if self._phase == "starting" and time.time() - started > self.wait_seconds:
                    self._finish_failed("the provider's tool never showed a sign-in link")
                    return
                continue
            try:
                chunk = os.read(self._fd, 4096)
            except OSError:
                chunk = b""
            if not chunk:
                self._exited(buffer)
                return
            buffer = (buffer + _ANSI.sub("", chunk.decode("utf8", "replace")))[-20000:]
            token = self.token_pattern.search(buffer)
            if token:
                self.vault.put(self.secret_name, token.group(0))
                self._set("done", "signed in; the token is in the vault")
                self._terminate()
                return
            if self._phase == "starting":
                for found in _URL.findall(buffer):
                    if found.startswith(self.allowed_url_prefix):
                        self._set("waiting_for_code", "sign in at the provider, then paste the code it shows", found)
                        break
                else:
                    if _URL.search(buffer):
                        self._finish_failed("the provider's tool printed a link to another site; it was not shown")
                        return

    def _exited(self, buffer):
        if self._phase in ("done", "cancelled"):
            return
        self._finish_failed("the provider's tool stopped before finishing" if self._phase != "starting"
                            else "the provider's tool could not be started")

    def _finish_failed(self, message):
        if self._cancelled:
            return
        self._set("failed", message)
        self._terminate()

    def _terminate(self):
        pid, self._pid = self._pid, None
        if pid:
            try:
                os.killpg(pid, signal.SIGTERM)              # its own session: the tool and anything it started
            except OSError:
                pass
            try:
                self._proc.wait(timeout=5)
            except Exception:
                pass
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def submit_code(self, code):
        if self._phase != "waiting_for_code":
            raise SetupError("the setup is not waiting for a code")
        if not isinstance(code, str) or not 1 <= len(code.strip()) <= 512 or any(c in code.strip() for c in "\r\n\x00"):
            raise SetupError("the code must be one line of up to 512 characters")
        os.write(self._fd, code.strip().encode() + b"\r")
        self._set("finishing", "checking the code with the provider")

    def cancel(self):
        self._cancelled = True
        self._set("cancelled", "stopped")
        self._terminate()
