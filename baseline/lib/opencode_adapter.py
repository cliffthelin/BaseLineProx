"""OpenCode HarnessAdapter (decision record 44) - the second real
harness satisfying harness_adapter.py's contract, and the first one to
arrive already speaking a real, open standard: the Agent Client
Protocol (ACP), not a bespoke wire format. Confirmed against a real,
live `opencode acp` process during this work - a full
initialize -> session/new -> session/prompt round trip, including real
`session/update` streaming notifications, completed successfully (see
acp_protocol.py's own module docstring for the one real discrepancy
that live-testing caught against the protocol's own documentation).

Deliberately does NOT implement grant_write_scope/revoke_write_scope -
optional per the HarnessAdapter contract. ACP defines a real
`session/request_permission` flow for tool-call approval, but whether
it can express decision record 32's specific "session-only,
scope-asked, path-bounded" shape has not been checked - guessing at
that mapping would repeat the exact mistake decision record 40 already
found and fixed once for Claude (`Write(...)` vs. `Edit(...)`). Left
absent, honestly, rather than faked.

`runner` here is a transport *factory* (`callable(argv) -> connection`
exposing `send`/`read_line`), not the same `Runner` class
harness.py's Claude adapter uses - the HarnessAdapter contract only
promises each adapter accepts an injectable dependency for its own
I/O boundary, not that every adapter's boundary has the identical
shape. ACP's bidirectional JSON-RPC needs a different shape than
Claude's one-shot/streaming subprocess calls.
"""
from __future__ import annotations

from dataclasses import dataclass

import acp_protocol
import acp_transport
import harness_events

OPENCODE_ARGV = ["opencode", "acp"]
DEFAULT_CWD = "/tmp"


@dataclass
class OpencodeSession:
    """One warm ACP connection + session id, alive only for this
    process's lifetime - the same 'always available, not always
    running' shape as harness.HarnessSession (decision record 31), for
    a different transport. `connection`/`session_id` are created
    lazily on first use, so new_session() itself never spawns a
    process."""
    cwd: str = DEFAULT_CWD
    connection: object = None
    session_id: str = None
    _next_id: int = 1

    def next_request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id


_default_session = OpencodeSession()


def new_session() -> OpencodeSession:
    return OpencodeSession()


def describe_session(session: OpencodeSession) -> str:
    state = "warm (ACP session active)" if session.session_id else "cold (no ACP session yet)"
    return f"session: {state} | write: not supported by this harness"


def _read_until_response(connection, request_id):
    while True:
        line = connection.read_line()
        if line is None:
            return None
        message = acp_protocol.parse_message(line)
        if message is None:
            continue
        if acp_protocol.is_response_for(message, request_id):
            return message


def _ensure_session(session: OpencodeSession, transport_factory):
    if session.connection is None:
        session.connection = transport_factory(OPENCODE_ARGV)
        init_id = session.next_request_id()
        session.connection.send(acp_protocol.build_initialize_request(init_id))
        _read_until_response(session.connection, init_id)
    if session.session_id is None:
        new_id = session.next_request_id()
        session.connection.send(acp_protocol.build_session_new_request(new_id, cwd=session.cwd))
        response = _read_until_response(session.connection, new_id)
        session.session_id = acp_protocol.extract_session_id(response)
    return session.connection


def ask_streaming(prompt: str, on_event, *, session: OpencodeSession = None, runner=None) -> str:
    session = session if session is not None else _default_session
    transport_factory = runner if runner is not None else acp_transport.AcpConnection

    try:
        connection = _ensure_session(session, transport_factory)
    except (OSError, FileNotFoundError) as exc:
        message = f"[ask] opencode acp failed to start: {exc}"
        on_event(harness_events.TurnEnd(text=message, is_error=True))
        return message

    prompt_id = session.next_request_id()
    connection.send(acp_protocol.build_session_prompt_request(
        prompt_id, session_id=session.session_id, text=prompt))

    accumulated = []
    while True:
        line = connection.read_line()
        if line is None:
            message = "[ask] opencode acp connection closed unexpectedly"
            on_event(harness_events.TurnEnd(text=message, is_error=True))
            return message

        message = acp_protocol.parse_message(line)
        if message is None:
            continue

        chunk = acp_protocol.extract_message_chunk(message)
        if chunk is not None:
            accumulated.append(chunk.text)
            on_event(chunk)
            continue

        stop_reason = acp_protocol.extract_stop_reason(message, prompt_id)
        if stop_reason is not None:
            final_text = "".join(accumulated)
            is_error = stop_reason not in ("end_turn", "completed")
            on_event(harness_events.TurnEnd(text=final_text, is_error=is_error))
            return final_text


def ask(prompt: str, *, session: OpencodeSession = None, runner=None) -> str:
    session = session if session is not None else _default_session
    return ask_streaming(prompt, lambda event: None, session=session, runner=runner)
