"""Pure parsing for the claude CLI's `--output-format stream-json`
NDJSON event stream (item 3 of docs/design/v0.1-work-queue.md) - one
JSON object per line. Verified against the real installed CLI
(decision record 41): `--verbose` is required alongside
`--output-format stream-json` under `-p`/`--print` - confirmed
directly, omitting it fails fast with "Error: When using --print,
--output-format=stream-json requires --verbose" before any request is
even sent, so `build_ask_argv`'s streaming variant must always include
both together.

This module only parses lines already captured from a real
invocation - the test fixtures are the actual bytes a real `claude -p
"Say exactly: hello world" --output-format stream-json --verbose`
call emitted, not a guessed shape.
"""
from __future__ import annotations

import json


def parse_event(line: str):
    """One NDJSON line -> its parsed event dict, or None for a blank
    line or malformed JSON - never raises, so one bad line can't crash
    an otherwise-good stream."""
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except ValueError:
        return None


def extract_assistant_text(event):
    """The assistant's own text from a {"type": "assistant", ...}
    event - None for every other event type or a malformed one."""
    if not event or event.get("type") != "assistant":
        return None
    content = event.get("message", {}).get("content", [])
    texts = [block.get("text", "") for block in content if block.get("type") == "text"]
    return "".join(texts) if texts else None


def extract_final_result(event):
    """The final answer text from a {"type": "result", ...} event."""
    if not event or event.get("type") != "result":
        return None
    return event.get("result")


def is_error_result(event) -> bool:
    return bool(event) and event.get("type") == "result" and event.get("is_error") is True
