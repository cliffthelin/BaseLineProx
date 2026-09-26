"""OSC 52 clipboard-set escape sequence - the standard mechanism for a
TUI to reach the *local* clipboard of whatever terminal is attached,
including over SSH (per SESSION_HANDOFF.md's original note on this).

Deliberately its own tiny, dependency-free module rather than relying
on a Textual version's own clipboard helper: the real deployment
target installs `python3-textual` via apt (provision.sh), and this
project has no way to confirm which Textual version that resolves to
without real hardware access - building the escape sequence directly
means this doesn't depend on that answer.

Building the sequence is the only thing this module does. Actually
writing it to the terminal (and confirming a terminal/SSH path
receives and applies it) is a separate, real-hardware verification
question - see docs/design/v0.1-work-queue.md item 1/7.
"""
from __future__ import annotations

import base64


def build_osc52_copy_sequence(text: str, *, selection: str = "c") -> str:
    """`selection`: "c" (clipboard, the default), "p" (primary), or
    "s" (select) - the buffer letter OSC 52 itself defines."""
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"\x1b]52;{selection};{payload}\x07"
