"""Unit tests for harness.py's real incremental streaming
(ask_streaming, decision record 41): text arrives as soon as the
assistant's own message event lands in the NDJSON stream, not only
after the whole process exits. The fake streaming runner yields the
same real, previously-captured NDJSON lines stream_json.py's own tests
use - not a guessed shape."""
import pytest

import harness


class FakeStreamingRunner(harness.Runner):
    def __init__(self, lines):
        self.lines = list(lines)
        self.calls = []

    def stream(self, argv, timeout=60):
        self.calls.append(argv)
        for line in self.lines:
            yield line


@pytest.fixture(autouse=True)
def _stub_context(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")
    monkeypatch.setattr(harness.hardware, "collect", lambda: ({}, None))
    monkeypatch.setattr(harness.hardware, "normalize", lambda raw: {})
    monkeypatch.setattr(harness.network, "check_lifeline", lambda: {})


REAL_ASSISTANT_LINE = '{"type":"assistant","message":{"content":[{"type":"text","text":"hello world"}]}}'
REAL_RESULT_LINE = '{"type":"result","is_error":false,"result":"hello world"}'


def test_build_stream_argv_adds_output_format_and_verbose_required_together():
    session = harness.HarnessSession(session_id="fixed-id")
    argv = harness.build_stream_argv("hello", session)
    assert argv == ["claude", "-p", "hello", "--output-format", "stream-json", "--verbose",
                     "--session-id", "fixed-id", "--tools", ""]


def test_build_stream_argv_continues_a_started_session_like_build_ask_argv():
    session = harness.HarnessSession(session_id="fixed-id", started=True)
    argv = harness.build_stream_argv("hello", session)
    assert argv == ["claude", "-p", "hello", "--output-format", "stream-json", "--verbose",
                     "-c", "--tools", ""]


def test_ask_streaming_calls_on_text_as_the_assistant_event_arrives():
    runner = FakeStreamingRunner([REAL_ASSISTANT_LINE, REAL_RESULT_LINE])
    seen = []
    result = harness.ask_streaming("hi", seen.append, runner=runner, session=harness.HarnessSession())
    assert seen == ["hello world"]
    assert result == "hello world"


def test_ask_streaming_skips_malformed_lines_without_crashing():
    runner = FakeStreamingRunner(["not json at all", REAL_ASSISTANT_LINE, REAL_RESULT_LINE])
    seen = []
    result = harness.ask_streaming("hi", seen.append, runner=runner, session=harness.HarnessSession())
    assert seen == ["hello world"]
    assert result == "hello world"


def test_ask_streaming_marks_session_started():
    runner = FakeStreamingRunner([REAL_RESULT_LINE])
    session = harness.HarnessSession(session_id="fixed-id")
    harness.ask_streaming("hi", lambda t: None, runner=runner, session=session)
    assert session.started is True


def test_ask_streaming_reports_no_credentials_without_calling_the_runner(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(harness, "ENV_FILE", "/nonexistent/harness.env")
    runner = FakeStreamingRunner([])
    seen = []
    result = harness.ask_streaming("hi", seen.append, runner=runner)
    assert "no CLAUDE_CODE_OAUTH_TOKEN" in result
    assert runner.calls == []
