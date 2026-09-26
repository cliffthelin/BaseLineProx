"""Unit tests for acp_protocol.py - the real Agent Client Protocol
(ACP) message building/parsing (decision record 44). Every fixture
line below is REAL, captured directly from a live `opencode acp`
process during this work - not a guessed shape, and not just the
documented schema either: the real wire format uses `"sessionUpdate"`
as the discriminator key inside `update`, not `"type"` as the
protocol's own docs page implied - caught specifically by live-testing
rather than trusting the docs alone.
"""
import acp_protocol as acp
import harness_events as he

# Real captured line: the initialize response.
REAL_INITIALIZE_RESPONSE = (
    '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":'
    '{"loadSession":true,"mcpCapabilities":{"http":true,"sse":true},'
    '"promptCapabilities":{"embeddedContext":true,"image":true},'
    '"sessionCapabilities":{"close":{},"fork":{},"list":{},"resume":{}}},'
    '"authMethods":[{"description":"Run `opencode auth login` in the terminal",'
    '"name":"Login with opencode","id":"opencode-login"}],'
    '"agentInfo":{"name":"OpenCode","version":"1.18.11"}}}'
)

# Real captured line: the session/new response.
REAL_SESSION_NEW_RESPONSE = (
    '{"jsonrpc":"2.0","id":2,"result":{"sessionId":"ses_f1ff601e1ffeGyBrBZWcWn41r9",'
    '"configOptions":[{"id":"model","name":"Model","category":"model","type":"select",'
    '"currentValue":"opencode/big-pickle","options":[]}]}}'
)

# Real captured line: an agent_message_chunk session/update notification.
REAL_MESSAGE_CHUNK_NOTIFICATION = (
    '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"ses_f1ff601e1ffeGyBrBZWcWn41r9",'
    '"update":{"sessionUpdate":"agent_message_chunk","messageId":"msg_0e009fe3d001O2fINbMLMAD4J7",'
    '"content":{"type":"text","text":"hello world"}}}}'
)

# Real captured line: an available_commands_update notification - not part of
# Baseline's trimmed schema, must normalize to None.
REAL_OTHER_NOTIFICATION = (
    '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"ses_f1ff601e1ffeGyBrBZWcWn41r9",'
    '"update":{"sessionUpdate":"usage_update","used":37994,"size":200000,'
    '"cost":{"amount":0,"currency":"USD"}}}}'
)

# Real captured line: the session/prompt response (turn completion).
REAL_PROMPT_RESPONSE = (
    '{"jsonrpc":"2.0","id":3,"result":{"stopReason":"end_turn",'
    '"usage":{"inputTokens":36055,"outputTokens":3,"totalTokens":37997,"cachedReadTokens":1939},"_meta":{}}}'
)


def test_build_initialize_request_shape():
    request = acp.build_initialize_request(1)
    assert request == {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": 1,
            "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
        },
    }


def test_build_session_new_request_shape():
    request = acp.build_session_new_request(2, cwd="/tmp")
    assert request == {
        "jsonrpc": "2.0", "id": 2, "method": "session/new",
        "params": {"cwd": "/tmp", "mcpServers": []},
    }


def test_build_session_prompt_request_shape():
    request = acp.build_session_prompt_request(3, session_id="ses_abc", text="hi")
    assert request == {
        "jsonrpc": "2.0", "id": 3, "method": "session/prompt",
        "params": {"sessionId": "ses_abc", "prompt": [{"type": "text", "text": "hi"}]},
    }


def test_encode_message_is_one_newline_terminated_json_line():
    line = acp.encode_message({"a": 1})
    assert line == '{"a": 1}\n'


def test_parse_message_parses_a_real_response():
    message = acp.parse_message(REAL_INITIALIZE_RESPONSE)
    assert message["id"] == 1
    assert message["result"]["agentInfo"]["name"] == "OpenCode"


def test_parse_message_returns_none_for_blank_or_malformed():
    assert acp.parse_message("") is None
    assert acp.parse_message("not json") is None


def test_extract_session_id_from_a_real_response():
    message = acp.parse_message(REAL_SESSION_NEW_RESPONSE)
    assert acp.extract_session_id(message) == "ses_f1ff601e1ffeGyBrBZWcWn41r9"


def test_extract_session_id_none_for_a_non_matching_message():
    message = acp.parse_message(REAL_PROMPT_RESPONSE)
    assert acp.extract_session_id(message) is None


def test_is_response_for_matches_id_and_result_or_error():
    message = acp.parse_message(REAL_SESSION_NEW_RESPONSE)
    assert acp.is_response_for(message, 2) is True
    assert acp.is_response_for(message, 3) is False


def test_extract_message_chunk_from_a_real_notification():
    message = acp.parse_message(REAL_MESSAGE_CHUNK_NOTIFICATION)
    chunk = acp.extract_message_chunk(message)
    assert chunk == he.AgentMessageChunk(text="hello world")


def test_extract_message_chunk_none_for_an_unrelated_session_update():
    message = acp.parse_message(REAL_OTHER_NOTIFICATION)
    assert acp.extract_message_chunk(message) is None


def test_extract_message_chunk_none_for_a_non_notification():
    message = acp.parse_message(REAL_PROMPT_RESPONSE)
    assert acp.extract_message_chunk(message) is None


def test_extract_stop_reason_from_a_real_prompt_response():
    message = acp.parse_message(REAL_PROMPT_RESPONSE)
    assert acp.extract_stop_reason(message, 3) == "end_turn"


def test_extract_stop_reason_none_for_a_different_id():
    message = acp.parse_message(REAL_PROMPT_RESPONSE)
    assert acp.extract_stop_reason(message, 99) is None
