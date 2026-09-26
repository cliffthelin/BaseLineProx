"""Unit tests for stream_json.py - parsing the claude CLI's
--output-format stream-json NDJSON event stream (item 3 of
docs/design/v0.1-work-queue.md). The fixture lines below are the
REAL, captured output of a real `claude -p "Say exactly: hello world"
--output-format stream-json --verbose --tools ""` invocation run
directly against the installed CLI during this work (decision record
41) - not a guessed shape, the actual bytes the real binary emitted.
"""
import harness_events as he
import stream_json as sj

# Real captured line: the assistant's own message event.
REAL_ASSISTANT_LINE = (
    '{"type":"assistant","message":{"model":"claude-sonnet-5","id":"msg_011CfSpKUXQXdQKyNTNLUPDF",'
    '"type":"message","role":"assistant","content":[{"type":"text","text":"hello world"}],'
    '"container":null,"stop_reason":null,"stop_sequence":null,"stop_details":null,'
    '"usage":{"input_tokens":2,"output_tokens":1},"diagnostics":null,"context_management":null},'
    '"parent_tool_use_id":null,"session_id":"6470810b-e6bb-4d36-beb4-93137e6c61d6",'
    '"uuid":"c45ec1c9-8cc9-46d7-8133-df0705195d5f","timestamp":"2026-09-26T22:11:01.113Z",'
    '"request_id":"req_011CfSpKU3P5rWjMYe17UZM8"}'
)

# Real captured line: the rate-limit metadata event - not part of the answer.
REAL_RATE_LIMIT_LINE = (
    '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1790465400,'
    '"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false},'
    '"uuid":"13029db3-49f5-4ed5-8427-79bdb7981a68","session_id":"6470810b-e6bb-4d36-beb4-93137e6c61d6"}'
)

# Real captured line: the final result event.
REAL_RESULT_LINE = (
    '{"is_error":false,"duration_api_ms":13541,"num_turns":1,"stop_reason":"end_turn",'
    '"session_id":"6470810b-e6bb-4d36-beb4-93137e6c61d6","total_cost_usd":0.1788666,'
    '"usage":{"input_tokens":2,"output_tokens":5},"permission_denials":[],'
    '"terminal_reason":"completed","subtype":"success","api_error_status":null,'
    '"result":"hello world","type":"result","duration_ms":14308,'
    '"uuid":"3158cbe5-6057-45cf-bc5b-f241d993f2ac"}'
)


def test_parse_event_parses_a_real_assistant_line():
    event = sj.parse_event(REAL_ASSISTANT_LINE)
    assert event["type"] == "assistant"
    assert event["session_id"] == "6470810b-e6bb-4d36-beb4-93137e6c61d6"


def test_parse_event_returns_none_for_a_blank_line():
    assert sj.parse_event("") is None
    assert sj.parse_event("   \n") is None


def test_parse_event_returns_none_rather_than_raising_on_malformed_json():
    assert sj.parse_event("{not valid json") is None


def test_extract_assistant_text_from_a_real_assistant_event():
    event = sj.parse_event(REAL_ASSISTANT_LINE)
    assert sj.extract_assistant_text(event) == "hello world"


def test_extract_assistant_text_is_none_for_other_event_types():
    event = sj.parse_event(REAL_RATE_LIMIT_LINE)
    assert sj.extract_assistant_text(event) is None


def test_extract_assistant_text_is_none_for_none_event():
    assert sj.extract_assistant_text(None) is None


def test_extract_final_result_from_a_real_result_event():
    event = sj.parse_event(REAL_RESULT_LINE)
    assert sj.extract_final_result(event) == "hello world"


def test_extract_final_result_is_none_for_other_event_types():
    event = sj.parse_event(REAL_ASSISTANT_LINE)
    assert sj.extract_final_result(event) is None


def test_is_error_result_false_on_the_real_success_line():
    event = sj.parse_event(REAL_RESULT_LINE)
    assert sj.is_error_result(event) is False


def test_is_error_result_true_when_is_error_is_true():
    event = {"type": "result", "is_error": True, "result": "something failed"}
    assert sj.is_error_result(event) is True


def test_is_error_result_false_for_non_result_events():
    event = sj.parse_event(REAL_ASSISTANT_LINE)
    assert sj.is_error_result(event) is False


# -- to_normalized(): the bridge into Baseline's ACP-inspired IR (harness_events.py) --

def test_to_normalized_maps_a_real_assistant_event_to_agent_message_chunk():
    event = sj.parse_event(REAL_ASSISTANT_LINE)
    normalized = sj.to_normalized(event)
    assert normalized == he.AgentMessageChunk(text="hello world")


def test_to_normalized_maps_a_real_result_event_to_turn_end():
    event = sj.parse_event(REAL_RESULT_LINE)
    normalized = sj.to_normalized(event)
    assert normalized == he.TurnEnd(text="hello world", is_error=False)


def test_to_normalized_maps_an_error_result_event_to_turn_end_with_is_error_true():
    event = {"type": "result", "is_error": True, "result": "boom"}
    normalized = sj.to_normalized(event)
    assert normalized == he.TurnEnd(text="boom", is_error=True)


def test_to_normalized_is_none_for_bookkeeping_events():
    event = sj.parse_event(REAL_RATE_LIMIT_LINE)
    assert sj.to_normalized(event) is None


def test_to_normalized_is_none_for_none():
    assert sj.to_normalized(None) is None
