"""Unit tests for opencode_adapter.py (decision record 44) - the
second real HarnessAdapter, speaking real ACP (Agent Client Protocol)
rather than a bespoke wire format. FakeConnection is fed the same
real, captured JSON-RPC lines acp_protocol.py's own tests use - a
full, real, live round trip (initialize -> session/new ->
session/prompt -> session/update chunks -> stopReason) was completed
against the actual `opencode acp` binary during this work; nothing
here is a guessed shape."""
import harness_events as he
import opencode_adapter as oa

REAL_INITIALIZE_RESPONSE = (
    '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{},'
    '"authMethods":[],"agentInfo":{"name":"OpenCode","version":"1.18.11"}}}'
)
REAL_SESSION_NEW_RESPONSE = (
    '{"jsonrpc":"2.0","id":2,"result":{"sessionId":"ses_f1ff601e1ffeGyBrBZWcWn41r9","configOptions":[]}}'
)
REAL_OTHER_NOTIFICATION = (
    '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"ses_f1ff601e1ffeGyBrBZWcWn41r9",'
    '"update":{"sessionUpdate":"usage_update","used":37994,"size":200000}}}'
)
REAL_MESSAGE_CHUNK_NOTIFICATION = (
    '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"ses_f1ff601e1ffeGyBrBZWcWn41r9",'
    '"update":{"sessionUpdate":"agent_message_chunk","messageId":"msg_x",'
    '"content":{"type":"text","text":"hello world"}}}}'
)
REAL_PROMPT_RESPONSE = '{"jsonrpc":"2.0","id":3,"result":{"stopReason":"end_turn","usage":{}}}'


class FakeConnection:
    def __init__(self, responses):
        self.sent = []
        self.responses = list(responses)

    def send(self, message):
        self.sent.append(message)

    def read_line(self):
        return self.responses.pop(0) if self.responses else None


def _factory(connection):
    return lambda argv: connection


def test_new_session_never_spawns_a_connection():
    session = oa.new_session()
    assert session.connection is None
    assert session.session_id is None


def test_describe_session_cold_before_any_connection():
    session = oa.new_session()
    assert "cold" in oa.describe_session(session)
    assert "not supported by this harness" in oa.describe_session(session)


def test_ask_streaming_completes_a_real_full_round_trip():
    connection = FakeConnection([
        REAL_INITIALIZE_RESPONSE,
        REAL_SESSION_NEW_RESPONSE,
        REAL_OTHER_NOTIFICATION,
        REAL_MESSAGE_CHUNK_NOTIFICATION,
        REAL_PROMPT_RESPONSE,
    ])
    session = oa.new_session()
    seen = []
    result = oa.ask_streaming("Say exactly: hello world", seen.append,
                               session=session, runner=_factory(connection))
    assert result == "hello world"
    assert seen == [he.AgentMessageChunk(text="hello world"),
                     he.TurnEnd(text="hello world", is_error=False)]
    assert session.session_id == "ses_f1ff601e1ffeGyBrBZWcWn41r9"


def test_ask_streaming_sends_the_real_request_shapes_in_order():
    connection = FakeConnection([
        REAL_INITIALIZE_RESPONSE, REAL_SESSION_NEW_RESPONSE,
        REAL_MESSAGE_CHUNK_NOTIFICATION, REAL_PROMPT_RESPONSE,
    ])
    session = oa.new_session()
    oa.ask_streaming("hi", lambda e: None, session=session, runner=_factory(connection))
    assert connection.sent[0]["method"] == "initialize"
    assert connection.sent[1]["method"] == "session/new"
    assert connection.sent[2]["method"] == "session/prompt"
    assert connection.sent[2]["params"]["sessionId"] == "ses_f1ff601e1ffeGyBrBZWcWn41r9"
    assert connection.sent[2]["params"]["prompt"] == [{"type": "text", "text": "hi"}]


def test_ask_streaming_reuses_an_existing_session_without_reinitializing():
    # Reuse means the SAME connection stays warm - a transport_factory
    # given on a later call is never even invoked once session.connection
    # is already set, matching decision record 31's "warm, not
    # re-initialized every turn" shape for the Claude adapter.
    connection = FakeConnection([
        REAL_INITIALIZE_RESPONSE, REAL_SESSION_NEW_RESPONSE,
        REAL_MESSAGE_CHUNK_NOTIFICATION, REAL_PROMPT_RESPONSE,
    ])
    session = oa.new_session()
    oa.ask_streaming("first", lambda e: None, session=session, runner=_factory(connection))

    # The request-id counter correctly keeps incrementing across calls
    # on the same warm session (1=init, 2=session/new, 3=first prompt,
    # 4=second prompt) - the real captured REAL_PROMPT_RESPONSE fixture
    # has id=3 baked in, so this second response needs id=4 to match,
    # not a re-use of the same real line verbatim.
    second_prompt_response = REAL_PROMPT_RESPONSE.replace('"id":3', '"id":4')
    connection.responses.extend([REAL_MESSAGE_CHUNK_NOTIFICATION, second_prompt_response])
    calls_to_a_different_factory = []
    result = oa.ask_streaming("second", lambda e: None, session=session,
                               runner=lambda argv: calls_to_a_different_factory.append(argv))
    assert result == "hello world"
    assert calls_to_a_different_factory == []
    # Only one session/prompt was sent for "first", a second for "second" -
    # initialize/session-new were never repeated.
    prompt_calls = [m for m in connection.sent if m["method"] == "session/prompt"]
    assert len(prompt_calls) == 2


def test_ask_streaming_reports_a_dropped_connection_as_an_error_turn_end():
    connection = FakeConnection([REAL_INITIALIZE_RESPONSE, REAL_SESSION_NEW_RESPONSE])
    session = oa.new_session()
    seen = []
    result = oa.ask_streaming("hi", seen.append, session=session, runner=_factory(connection))
    assert "connection closed" in result
    assert seen[-1].is_error is True


def test_ask_delegates_to_ask_streaming_and_returns_the_final_text():
    connection = FakeConnection([
        REAL_INITIALIZE_RESPONSE, REAL_SESSION_NEW_RESPONSE,
        REAL_MESSAGE_CHUNK_NOTIFICATION, REAL_PROMPT_RESPONSE,
    ])
    session = oa.new_session()
    result = oa.ask("hi", session=session, runner=_factory(connection))
    assert result == "hello world"


def test_opencode_adapter_has_no_write_grant_hooks():
    # Optional per the HarnessAdapter contract (harness_adapter.py) -
    # deliberately absent rather than guessed at, matching decision
    # record 44's own stated reasoning.
    assert not hasattr(oa, "grant_write_scope")
    assert not hasattr(oa, "revoke_write_scope")
