"""Drive a shell that is on a serial console, from outside the VM (the live installers that have no unattended mode: NixOS, CachyOS).

QEMU exposes the guest's serial port as a unix socket. A command is sent followed by an `echo` of a marker that carries its exit status, and the output up to that marker is the result.
This is for BUILD machines installing a known image into a blank disk; it is not a way to reach a running system.
"""
from __future__ import annotations

import base64
import re
import secrets
import socket
import time


class SerialError(RuntimeError):
    pass


class SerialShell:
    def __init__(self, path: str, connect_timeout: float = 120):
        end = time.monotonic() + connect_timeout
        while True:
            try:
                self.sock = socket.socket(socket.AF_UNIX)
                self.sock.connect(path)
                break
            except OSError:
                self.sock.close()
                if time.monotonic() > end:
                    raise SerialError("the serial console did not come up") from None
                time.sleep(2)
        self.sock.settimeout(1.0)
        self.buffer = ""

    def _pull(self) -> str:
        try:
            chunk = self.sock.recv(65536)
        except (socket.timeout, TimeoutError):
            return ""
        if chunk == b"":
            raise SerialError("the serial console closed")
        text = chunk.decode(errors="replace")
        self.buffer += text
        return text

    def wait_for(self, pattern: str, timeout: float) -> str:
        """Read until `pattern` (a regular expression) appears; return everything read up to and including it."""
        end = time.monotonic() + timeout
        found = re.compile(pattern)
        while time.monotonic() < end:
            match = found.search(self.buffer)
            if match:
                taken, self.buffer = self.buffer[:match.end()], self.buffer[match.end():]
                return taken
            self._pull()
        raise SerialError(f"timed out waiting for {pattern!r}; the last output was: {self.buffer[-300:]!r}")

    def wait_ready(self, timeout: float = 600, login: tuple = None) -> None:
        """Wait for a shell to answer on the console (a booting system takes a while). Keeps asking until one answers; an answer to a question asked early is fine, the marker is unique.
        When a login prompt is what answers, `login=(user, password)` is typed in (an empty password is just Enter) and the wait goes on."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            mark = secrets.token_hex(4)
            self.sock.sendall(f"\necho READY_{mark}\n".encode())
            try:
                self.wait_for(rf"(?<!echo )READY_{mark}\r?\n", 8)
                return
            except SerialError:
                tail = self.buffer[-200:]
                if login and re.search(r"login: ?$", tail):
                    self.buffer = ""
                    self.sock.sendall((login[0] + "\n").encode())
                    try:
                        self.wait_for(r"(?i)password: ?", 10)
                        self.sock.sendall((login[1] + "\n").encode())
                    except SerialError:
                        pass
                continue
        raise SerialError("no shell answered on the serial console")

    def run(self, command: str, timeout: float = 600) -> tuple:
        """(exit status, output) of one command line. The command must be a single line."""
        if "\n" in command:
            raise SerialError("a command is one line")
        mark = secrets.token_hex(6)
        self.sock.sendall((f"{command}; echo \"__END_{mark}_$?__\"\n").encode())
        text = self.wait_for(rf"__END_{mark}_(\d+)__\r?\n", timeout)
        status = int(re.search(rf"__END_{mark}_(\d+)__", text).group(1))
        echoed = text.split(f"echo \"__END_{mark}_$?__\"", 1)[-1]                    # drop the terminal's echo of what was typed
        return status, re.sub(rf"__END_{mark}_\d+__\r?\n", "", echoed).strip()

    def write_file(self, path: str, data: bytes, timeout: float = 120) -> None:
        """Put a file on the guest: base64 on one line, so no quoting of its content matters."""
        encoded = base64.b64encode(data).decode()
        status, out = self.run(f"echo '{encoded}' | base64 -d > {path}", timeout)
        if status != 0:
            raise SerialError(f"could not write {path}: {out}")

    def close(self) -> None:
        self.sock.close()
