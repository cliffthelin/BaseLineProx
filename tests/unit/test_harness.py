"""Unit tests for harness.py's warm, per-process session support
(docs/design/decision-records/31 - "always available, not always
running"): the first turn names a new Claude Code session with
--session-id, every later turn in the same process continues it with
-c, and the session dies with the process - never persisted, never a
background daemon. hardware.py/network.py are stubbed since this
module's context blob calls them directly; the actual `claude` CLI
invocation always goes through an injectable Runner, matching
repair.py's established convention - no test here ever spawns a real
subprocess.
"""
from dataclasses import dataclass

import pytest

import harness


@dataclass
class FakeProc:
    returncode: int = 0
    stdout: str = "ok"
    stderr: str = ""


class FakeRunner(harness.Runner):
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def run(self, argv, timeout=60):
        self.calls.append(argv)
        if self.responses:
            return self.responses.pop(0)
        return FakeProc()


class FailingRunner(harness.Runner):
    def __init__(self, exc):
        self.exc = exc

    def run(self, argv, timeout=60):
        raise self.exc


@pytest.fixture(autouse=True)
def _stub_context(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")
    monkeypatch.setattr(harness.hardware, "collect", lambda: ({}, None))
    monkeypatch.setattr(harness.hardware, "normalize", lambda raw: {})
    monkeypatch.setattr(harness.network, "check_lifeline", lambda: {})


# -- pure argv-building: the actual session-continuity contract -----------

def test_build_ask_argv_first_call_names_a_new_session():
    session = harness.HarnessSession(session_id="fixed-id")
    argv = harness.build_ask_argv("hello", session)
    assert argv == ["claude", "-p", "hello", "--session-id", "fixed-id", "--tools", ""]


def test_build_ask_argv_subsequent_call_continues_it():
    session = harness.HarnessSession(session_id="fixed-id", started=True)
    argv = harness.build_ask_argv("hello again", session)
    assert argv == ["claude", "-p", "hello again", "-c", "--tools", ""]


# -- ask(): wiring, real Runner injection, session lifecycle ---------------

def test_ask_names_a_new_session_then_continues_it_across_calls():
    runner = FakeRunner()
    session = harness.HarnessSession(session_id="fixed-id")
    harness.ask("first", runner=runner, session=session)
    harness.ask("second", runner=runner, session=session)
    assert "--session-id" in runner.calls[0]
    assert "-c" in runner.calls[1]
    assert "--session-id" not in runner.calls[1]


def test_ask_marks_session_started_even_when_the_call_fails():
    session = harness.HarnessSession(session_id="fixed-id")
    result = harness.ask("first", runner=FailingRunner(FileNotFoundError("claude")), session=session)
    assert "claude CLI not found" in result
    assert session.started is True


def test_ask_never_calls_the_runner_without_credentials(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(harness, "ENV_FILE", "/nonexistent/harness.env")
    runner = FakeRunner()
    result = harness.ask("first", runner=runner)
    assert "no CLAUDE_CODE_OAUTH_TOKEN" in result
    assert runner.calls == []


def test_ask_returns_stdout_from_the_runner():
    runner = FakeRunner(responses=[FakeProc(returncode=0, stdout="42\n")])
    result = harness.ask("six times seven", runner=runner, session=harness.HarnessSession())
    assert result == "42"


def test_ask_reports_a_nonzero_exit_without_crashing():
    runner = FakeRunner(responses=[FakeProc(returncode=1, stdout="", stderr="boom")])
    result = harness.ask("anything", runner=runner, session=harness.HarnessSession())
    assert "harness exited 1" in result
    assert "boom" in result


def test_ask_reports_a_timeout_without_crashing():
    result = harness.ask("first", runner=FailingRunner(__import__("subprocess").TimeoutExpired(cmd="claude", timeout=60)),
                          session=harness.HarnessSession())
    assert "timed out" in result
