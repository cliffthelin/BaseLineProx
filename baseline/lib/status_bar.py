"""Pure formatting for the app-wide condensed header bar
(SESSION_HANDOFF.md's still-open "Chat tab quality" ask, item 2 of
docs/design/v0.1-work-queue.md).

Deliberately narrow: Textual's own `Header` widget already shows the
app title and a live clock (datetime), and its `TabbedContent`
already highlights the active tab (`Tab.-active` in bin/baseline's
CSS) - this bar exists only for what nothing else already shows: live
session/access-scope state, and the copy-action hint.
"""
from __future__ import annotations


def format_status_bar(session_desc: str) -> str:
    return f"BaselineOS | {session_desc} | c=copy"
