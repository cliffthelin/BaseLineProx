"""OpenAI's Codex CLI as a Baseline harness (the HarnessAdapter contract, harness_adapter.py).

`codex exec` runs one non-interactive turn. It is always started in the read-only sandbox, outside any git checkout check, in a scratch
folder; the OpenAI API key comes from the environment or the credential vault (vault.lookup) and reaches the child only as an
environment variable, never as an argument. Answers are delivered whole (one chunk, one turn end): the CLI is not a streaming
protocol the way ACP is.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import harness_events
import vault

BINARY = "codex"
SCRATCH = "/tmp"
TIMEOUT_S = 180


class CodexSession:
    """Codex's `exec` is stateless per call; the session only records that a turn happened."""
    turns = 0


def new_session() -> CodexSession:
    return CodexSession()


def describe_session(session: CodexSession) -> str:
    return f"session: {'warm' if session.turns else 'cold'} (codex exec, one turn per question) | provider: OpenAI | write: read-only sandbox"


def _run(prompt, binary):
    key = vault.lookup("OPENAI_API_KEY")
    import ai_provisioning
    env = ai_provisioning.client_environment("codex")
    key = key or env.get("OPENAI_API_KEY")
    if not key and not (env.get("BASELINE_AI_PROFILE") == "codex" and (Path(env.get("CODEX_HOME", "/nonexistent")) / "auth.json").is_file()):
        return None, "[ask] no OPENAI_API_KEY found: add it on the AI providers page or the vault page (/vault), then ask again"
    if key:
        env["OPENAI_API_KEY"] = key
    argv = [binary, "exec", "--skip-git-repo-check", "-s", "read-only", "-C", SCRATCH, prompt]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S, env=env)
    except FileNotFoundError:
        return None, "[ask] the codex CLI is not installed on this host"
    except subprocess.TimeoutExpired:
        return None, f"[ask] codex timed out after {TIMEOUT_S}s"
    if done.returncode != 0:
        return None, f"[ask] codex exited {done.returncode}: {(done.stderr or done.stdout).strip()[:400]}"
    return (done.stdout.strip() or "[ask] empty response from codex"), None


def ask_streaming(prompt: str, on_event, *, session: CodexSession = None, runner=None, binary: str = BINARY) -> str:
    text, error = _run(prompt, binary)
    if session is not None:
        session.turns += 1
    if error:
        on_event(harness_events.TurnEnd(text=error, is_error=True))
        return error
    on_event(harness_events.AgentMessageChunk(text=text))
    on_event(harness_events.TurnEnd(text=text, is_error=False))
    return text


def ask(prompt: str, *, session: CodexSession = None, runner=None, binary: str = BINARY) -> str:
    return ask_streaming(prompt, lambda event: None, session=session, runner=runner, binary=binary)
