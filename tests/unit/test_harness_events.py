"""Unit tests for harness_events.py - Baseline's internal normalized
harness-IO event types (the "ACL" asked for: every adapter must
translate its own wire format into these two, so bin/baseline never
needs to know Claude's NDJSON shape or OpenCode's ACP shape).

Named after the real Agent Client Protocol (ACP) v1 schema's
SessionUpdate vocabulary (https://agentclientprotocol.com/protocol/v1/schema) -
not invented from scratch. Trimmed to the two variants Baseline's
harness layer actually surfaces today (no tool_call/plan/thought_chunk
variants - every harness runs with zero tools by design)."""
import harness_events as he


def test_agent_message_chunk_holds_text():
    chunk = he.AgentMessageChunk(text="hello")
    assert chunk.text == "hello"


def test_turn_end_defaults_to_not_an_error():
    end = he.TurnEnd(text="final answer")
    assert end.text == "final answer"
    assert end.is_error is False


def test_turn_end_can_carry_an_error():
    end = he.TurnEnd(text="[ask] harness timed out after 60s", is_error=True)
    assert end.is_error is True
