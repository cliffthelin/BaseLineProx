"""Tests for the serial-console driver's incremental UTF-8 decoding
(found during an independent review pass): a raw stream socket can
split a multi-byte UTF-8 character across two recv() calls. Decoding
each chunk independently - even with errors="replace" - corrupts that
character into replacement characters instead of reconstructing it.
Uses a real AF_UNIX socketpair, not a mock, so this exercises the
actual recv()/decode() path."""
import socket
import threading
import time

import qemu_serial_console as console


def _make_console_over_socketpair():
    """Returns (SerialConsole, other_end) where SerialConsole.sock is
    already connected to other_end via a real AF_UNIX socketpair -
    avoids needing SerialConsole.__init__'s connect-retry-to-a-path
    logic for this unit test."""
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    con = console.SerialConsole.__new__(console.SerialConsole)
    con.sock = a
    con.sock.settimeout(1.0)
    con.buffer = ""
    import codecs
    con._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    return con, b


def test_multibyte_character_split_across_two_chunks_reconstructs_correctly():
    con, other_end = _make_console_over_socketpair()
    try:
        # U+00E9 ("é") is 2 bytes in UTF-8: 0xC3 0xA9. Split them across
        # two separate sends so they arrive in separate recv() calls.
        text = "café MARKER"
        encoded = text.encode("utf-8")
        split_at = encoded.index(b"\xc3")
        first_half = encoded[:split_at + 1]  # ends with the first byte of "é"
        second_half = encoded[split_at + 1:]  # starts with the second byte of "é"

        def sender():
            other_end.sendall(first_half)
            time.sleep(0.1)  # ensure these are read as two separate recv() calls
            other_end.sendall(second_half)

        t = threading.Thread(target=sender)
        t.start()
        out = con.read_until("MARKER", timeout=5)
        t.join()

        assert "café" in out, f"expected correctly reconstructed 'café', got {out!r}"
        assert "�" not in out, f"a replacement character leaked through: {out!r}"
    finally:
        con.close()
        other_end.close()


def test_ascii_only_stream_is_unaffected():
    con, other_end = _make_console_over_socketpair()
    try:
        def sender():
            other_end.sendall(b"plain ascii output\n")
            other_end.sendall(b"MARKER")

        t = threading.Thread(target=sender)
        t.start()
        out = con.read_until("MARKER", timeout=5)
        t.join()
        assert "plain ascii output" in out
    finally:
        con.close()
        other_end.close()
