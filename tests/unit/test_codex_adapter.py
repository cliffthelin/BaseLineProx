"""OpenAI's Codex CLI as a harness: `codex exec` in a read-only sandbox, the API key from the vault, never on a command line.
A real child process stands in for the CLI so argv, environment and exit codes are the real ones."""
import os
import stat
import sys

import codex_adapter as ca
import harness_adapter
import harness_events
import vault as v


def fake_codex(tmp_path, body):
    path = tmp_path / "codex"
    path.write_text("#!" + sys.executable + "\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


ECHO = '''import os, sys
print("ARGV=" + "|".join(sys.argv[1:]))
print("KEY=" + ("present" if os.environ.get("OPENAI_API_KEY") else "absent"))
'''


def test_the_adapter_satisfies_the_harness_contract():
    import types
    module = types.SimpleNamespace(**{n: getattr(ca, n) for n in harness_adapter.REQUIRED_ATTRS})
    assert harness_adapter.conforms(module)


def test_a_question_runs_codex_exec_read_only_with_the_key_in_the_environment_only(tmp_path, monkeypatch):
    vault = v.Vault(tmp_path / "vault")
    vault.put("OPENAI_API_KEY", "sk-openai-secret-value-00001")
    monkeypatch.setattr(v, "default_vaults", lambda: [vault])
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    answer = ca.ask("how hot is the drive?", binary=fake_codex(tmp_path, ECHO))
    assert "KEY=present" in answer and "sk-openai-secret-value-00001" not in answer
    argv = answer.splitlines()[0].removeprefix("ARGV=").split("|")
    assert argv[0] == "exec" and "--skip-git-repo-check" in argv and argv[argv.index("-s") + 1] == "read-only"
    assert argv[-1] == "how hot is the drive?"
    assert "sk-openai" not in "".join(argv)


def test_no_key_says_so_without_starting_the_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "default_vaults", lambda: [])
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    marker = tmp_path / "ran"
    answer = ca.ask("hi", binary=fake_codex(tmp_path, f"open({str(marker)!r}, 'w').close()\n"))
    assert "OPENAI_API_KEY" in answer and "/vault" in answer and not marker.exists()


def test_a_missing_binary_and_a_failing_run_are_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret-value-00001")
    assert "not installed" in ca.ask("hi", binary="/nonexistent/codex")
    failing = fake_codex(tmp_path, "import sys\nprint('quota exceeded', file=sys.stderr)\nsys.exit(3)\n")
    assert "exited 3" in ca.ask("hi", binary=failing) and "quota exceeded" in ca.ask("hi", binary=failing)


def test_streaming_delivers_one_chunk_then_a_turn_end(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret-value-00001")
    events = []
    text = ca.ask_streaming("hi", events.append, binary=fake_codex(tmp_path, "print('pong')\n"))
    assert text == "pong"
    assert isinstance(events[0], harness_events.AgentMessageChunk) and events[0].text == "pong"
    assert isinstance(events[-1], harness_events.TurnEnd) and events[-1].is_error is False


def test_the_session_line_names_the_provider_and_the_read_only_scope():
    assert "read-only" in ca.describe_session(ca.new_session())
