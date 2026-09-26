"""Minimal serial-console expect-style driver for the TestPersistence
Phase-B vertical slice (docs/design/testpersistence-prd.md Milestone
3). No pexpect dependency, no shell - raw UNIX-socket I/O against a
QEMU chardev, with explicit string-matching and bounded timeouts.
Every read is timeout-bounded; nothing here waits forever except the
two explicit authorization gates in the orchestrator, which are a
deliberate design choice (PRD-required "no default or timeout
acceptance"), not a property of this module."""
import codecs
import socket
import time


class ConsoleTimeout(Exception):
    pass


class SerialConsole:
    def __init__(self, sock_path: str, connect_timeout: float = 30.0):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        deadline = time.time() + connect_timeout
        last_err = None
        while time.time() < deadline:
            try:
                self.sock.connect(sock_path)
                last_err = None
                break
            except (FileNotFoundError, ConnectionRefusedError) as exc:
                last_err = exc
                time.sleep(0.2)
        if last_err:
            raise last_err
        self.sock.settimeout(1.0)
        self.buffer = ""
        # An incremental decoder, not per-chunk decode(): a raw stream
        # socket can split a multi-byte UTF-8 character across two
        # recv() calls, and decoding each chunk independently (even
        # with errors="replace") would corrupt that character into two
        # replacement characters instead of reconstructing it. This
        # decoder carries any incomplete trailing bytes forward to the
        # next chunk.
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def read_until(self, needle: str, timeout: float = 120.0) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if needle in self.buffer:
                idx = self.buffer.index(needle) + len(needle)
                out, self.buffer = self.buffer[:idx], self.buffer[idx:]
                return out
            try:
                chunk = self.sock.recv(4096)
                if chunk:
                    self.buffer += self._decoder.decode(chunk)
            except socket.timeout:
                continue
            except OSError:
                break
        raise ConsoleTimeout(
            f"did not see {needle!r} within {timeout}s - last buffer tail: "
            f"{self.buffer[-800:]!r}")

    def drain(self, quiet_for: float = 2.0, max_wait: float = 10.0) -> str:
        """Reads whatever arrives until the stream is quiet for
        `quiet_for` seconds or `max_wait` is reached - used after
        sending a command to collect its output without knowing the
        exact prompt string in advance."""
        start = time.time()
        last_data = time.time()
        collected = self.buffer
        self.buffer = ""
        while time.time() - last_data < quiet_for and time.time() - start < max_wait:
            try:
                chunk = self.sock.recv(4096)
                if chunk:
                    collected += self._decoder.decode(chunk)
                    last_data = time.time()
            except socket.timeout:
                continue
            except OSError:
                break
        return collected

    def send_line(self, line: str) -> None:
        self.sock.sendall((line + "\n").encode())

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass
