"""Real ACP transport - spawns an ACP-compliant agent CLI as a
subprocess and speaks newline-delimited JSON-RPC over its stdin/stdout.
Confirmed live against a real `opencode acp` process (decision record
44): a full initialize -> session/new -> session/prompt round trip
completed over exactly this framing.

Kept separate from acp_protocol.py's pure message building/parsing so
the protocol layer stays testable with no real subprocess at all -
matches this project's established split (e.g. harness.py's
Runner/RealRunner boundary). Not unit-tested directly for the same
reason RealRunner.run()/stream() aren't: it's a thin real-IO wrapper,
exercised through the adapters that inject a fake in its place.
"""
from __future__ import annotations

import subprocess

import acp_protocol


class AcpConnection:
    def __init__(self, argv):
        self.proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        )

    def send(self, message: dict) -> None:
        self.proc.stdin.write(acp_protocol.encode_message(message))
        self.proc.stdin.flush()

    def read_line(self):
        line = self.proc.stdout.readline()
        return line if line else None

    def close(self) -> None:
        self.proc.terminate()
