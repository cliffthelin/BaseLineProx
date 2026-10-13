"""Chat and Tether for the browser (parity with the TUI's Chat tab and `t` action). Shared wording so both say the same thing."""
from __future__ import annotations

import html

MAX_QUESTION = 4000


def tether_message(result: dict):
    """(severity, text) exactly as the TUI's report_tether_result words it."""
    if result.get("ok"):
        return "information", f"USB tether connected on {result.get('interface')}: {result.get('address')}"
    return "error", f"USB tether {result.get('stage', 'unknown')}: {result.get('detail') or 'no diagnostic detail provided'}"


def clean_question(value) -> str:
    text = (value or "").strip() if isinstance(value, str) else ""
    if not text or len(text) > MAX_QUESTION:
        raise ValueError(f"a question is 1 to {MAX_QUESTION} characters")
    return text


def render(history, harnesses, notice="") -> bytes:
    log = "".join(f"<p><b>You:</b> {html.escape(q)}</p><p><b>Baseline:</b> {html.escape(a)}</p>" for q, a in history)
    options = "".join(f"<option value='{html.escape(i)}'>{html.escape(n)}</option>" for i, n in harnesses)
    note = f"<p>{html.escape(notice)}</p>" if notice else ""
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Chat</title></head><body><h1>Chat</h1>"
            f"{note}<form method=\"post\" action=\"/chat/ask\"><select name='harness'>{options}</select> "
            "<input name='question' size='60' autocomplete='off' placeholder='Ask Baseline...' required> "
            f"<button type='submit'>Ask</button></form>{log}"
            "<p><a href='/ai-setup'>AI provider setup</a></p></body></html>").encode()


def render_shell(transcript, harnesses, current="claude", notice="") -> bytes:
    """The browser version of the TUI's Console tab: a transcript (lines already plain text) and a command box."""
    log = "".join(f"<div>{html.escape(line)}</div>" for line in transcript)
    options = "".join(f"<option value='{html.escape(i)}'{' selected' if i == current else ''}>{html.escape(n)}</option>"
                      for i, n in harnesses)
    note = f"<p>{html.escape(notice)}</p>" if notice else ""
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Console</title><style>"
            "pre,.t{font-family:ui-monospace,monospace;white-space:pre-wrap}</style></head><body><h1>Console</h1>"
            f"{note}<div class='t'>{log or 'Baseline console. Type help for commands.'}</div>"
            "<form method=\"post\" action=\"/shell/run\"><label>baseline&gt; <input name='line' size='60' autocomplete='off' autofocus "
            "placeholder='hardware | network | tether | ask &lt;question&gt; | help'></label> "
            f"<select name='harness'>{options}</select> <button type='submit'>Run</button></form></body></html>").encode()
