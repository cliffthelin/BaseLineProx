"""Pure formatting for the app-wide condensed header bar
(SESSION_HANDOFF.md's still-open "Chat tab quality" ask, item 2 of
docs/design/v0.1-work-queue.md).

Deliberately narrow: Textual's own `Header` widget already shows the
app title and a live clock (datetime), and its `TabbedContent`
already highlights the active tab (`Tab.-active` in bin/baseline's
CSS) - this bar exists only for what nothing else already shows: live
session/access-scope state, and the copy-action hint.

Enforces the 80x24 layout floor (item 4, docs/design/v0.1-work-queue.md):
a long write-grant scope path (the one genuinely variable-length piece
of `describe_session`'s output) must never push this always-visible
line past the target floor width. Truncation uses plain ASCII "...",
never an ellipsis glyph - this project's own standing rule is "no
non-ASCII characters anywhere in rendered output" (see
docs/SESSION_HANDOFF.md's "Standing rules"; the app's only prior
Unicode use, arrow glyphs, was found and removed after real
TERM=linux rendering bugs).
"""
from __future__ import annotations


def elide_middle(text: str, max_len: int) -> str:
    """Truncate the middle of `text`, keeping both ends, so a long
    path still shows where it starts and ends rather than just being
    cut off at one end. Never exceeds `max_len`, for any `max_len`
    including very small ones."""
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return "." * max_len
    keep = max_len - 3
    head = keep - keep // 2
    tail = keep // 2
    return text[:head] + "..." + (text[len(text) - tail:] if tail else "")


def format_status_bar(session_desc: str, *, max_width: int = 80) -> str:
    prefix = "BaselineOS | "
    suffix = " | c=copy"
    budget = max(1, max_width - len(prefix) - len(suffix))
    desc = elide_middle(session_desc, budget)
    return f"{prefix}{desc}{suffix}"
