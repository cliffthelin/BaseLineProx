#!/usr/bin/env python3
"""Baseline Read-Only Harness - Step 6.

HarnessAdapter contract: Baseline collects its own deterministic state
(hardware.py / network.py) and hands it to the harness as plain text
context. The harness itself gets zero tools (--tools "") - it cannot see
or touch anything on the machine beyond what's in this context blob. This
is the strictest reading of "AI observes Baseline, AI does not bypass
Baseline": no tool-calling surface exists for it to misuse at all.

This adapter shells out to the Claude Code CLI, authenticated via a
long-lived OAuth token tied to the operator's Claude subscription
(CLAUDE_CODE_OAUTH_TOKEN) rather than a pay-per-token API key. Swapping
providers later means writing a new adapter with the same ask(prompt)
signature - the CLI/TUI layer never changes.

Session continuity (docs/design/decision-records/31 - "always
available, not always running"): `HarnessSession` names one Claude
Code session per Chat-tab process via `--session-id` on the first
turn, then continues it with `-c` on every later turn in that same
process, so the harness has real multi-turn memory. The session lives
only as long as this process does - it is never written to disk and
never runs unattended between turns; closing Baseline ends it. This is
purely a reachability change - `--tools ""` is unchanged on every
call, so this does not grant the harness anything it couldn't already
do.
"""
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field

sys.path.insert(0, "/opt/baseline/lib")
import hardware  # noqa: E402
import network  # noqa: E402
import stream_json  # noqa: E402

ENV_FILE = "/etc/baseline/harness.env"


class Runner:
    """Injectable subprocess boundary - real calls go through
    RealRunner, tests use a FakeRunner recording calls and returning
    scripted results, matching repair.py's established convention.
    Deliberately minimal (this module only ever runs one external
    command) rather than importing repair.Runner's larger interface,
    which would pull in ifnet_config/topology for no functional
    reason."""

    def run(self, argv, timeout=60):
        raise NotImplementedError

    def stream(self, argv, timeout=60):
        """Yields decoded stdout lines as they arrive in real time -
        unlike run(), which blocks until the whole process exits.
        Only ask_streaming() needs this; run()-only fakes elsewhere in
        this codebase are unaffected by its default NotImplementedError."""
        raise NotImplementedError


class RealRunner(Runner):
    def run(self, argv, timeout=60):
        return subprocess.run(argv, capture_output=True, text=True,
                               timeout=timeout, env={**os.environ})

    def stream(self, argv, timeout=60):
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, env={**os.environ})
        try:
            for line in proc.stdout:
                yield line
        finally:
            proc.wait(timeout=timeout)


@dataclass
class WriteGrant:
    """An explicit, scoped, session-only write authorization (decision
    record 32). Never created by the harness itself and never by
    anything reacting to the harness's own output - only Baseline's
    own console, after an operator has explicitly named the boundary.
    Holds only what was actually decided: where, by whom, and when -
    no duration field, because the answer is always "this session"
    and nothing here ever writes it to disk."""
    scope_path: str
    authorized_by: str
    granted_at: float


@dataclass
class HarnessSession:
    """One warm, resumable session, alive only for this process's
    lifetime. `started` flips to True after the first turn is sent
    (even if that turn fails) so every later turn continues the same
    session with `-c` rather than naming a new one. `write_grant`
    defaults to None on every new instance - a fresh session (a fresh
    Baseline process) never inherits a grant made in a previous one,
    by construction, not by remembering to clear it."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started: bool = False
    write_grant: WriteGrant = None


_default_session = HarnessSession()


def new_session() -> HarnessSession:
    """The HarnessAdapter contract's session factory
    (harness_adapter.py) - a thin, named wrapper so callers going
    through harness_registry never need to know this adapter's
    session type is specifically `HarnessSession`, only that
    `new_session()` returns *something* to pass back into `ask`/
    `ask_streaming`/`describe_session`."""
    return HarnessSession()


def grant_write_scope(session: HarnessSession, scope_path: str, *, authorized_by: str, now: float) -> WriteGrant:
    """The only way a `WriteGrant` comes into existence. Refuses a
    scope that isn't a real, existing directory - fail-closed rather
    than granting a boundary around nothing (matches
    gui_brokers.file_picker's allowlist-by-construction discipline).
    Resolves symlinks/`..` before storing, so the stored scope is the
    real path being granted, not whatever string was typed."""
    resolved = os.path.realpath(scope_path)
    if not os.path.isdir(resolved):
        raise ValueError(f"{scope_path!r} is not an existing directory - "
                          "refusing to grant a write scope around it")
    grant = WriteGrant(scope_path=resolved, authorized_by=authorized_by, granted_at=now)
    session.write_grant = grant
    return grant


def revoke_write_scope(session: HarnessSession) -> None:
    session.write_grant = None


def is_path_within_grant(session: HarnessSession, path: str) -> bool:
    """Whether `path` genuinely resolves inside the session's granted
    scope - real containment after resolving symlinks/`..`, never a
    prefix-string comparison alone, so `scope-but-not-really/` can't
    pass a check meant for `scope/` and `scope/../outside` can't
    escape it. False whenever there is no active grant at all."""
    if session.write_grant is None:
        return False
    resolved = os.path.realpath(path)
    scope = session.write_grant.scope_path
    return resolved == scope or resolved.startswith(scope + os.sep)


def describe_session(session: HarnessSession) -> str:
    """The visible-access-scope status text SESSION_HANDOFF.md's
    Chat-tab item asked for - the underlying HarnessSession/WriteGrant
    state already existed with no UI reading it. Pure and cheap
    enough to call on every render; the TUI header/status widget is
    the only intended caller."""
    state = "warm (multi-turn memory active)" if session.started else "cold (no memory yet)"
    if session.write_grant is None:
        scope = "write: none"
    else:
        scope = f"write: {session.write_grant.scope_path} (this session only)"
    return f"session: {state} | {scope}"


def build_ask_argv(full_prompt: str, session: HarnessSession) -> list:
    argv = ["claude", "-p", full_prompt]
    argv += ["--session-id", session.session_id] if not session.started else ["-c"]
    if session.write_grant is not None:
        # Verified against the real installed claude CLI (decision
        # record 40), against the original guess this replaced: (1)
        # "Write(...)" is not a valid permission rule at all - the CLI
        # itself refuses it ("only Edit(path) rules are [matched]");
        # the correct tool name for file-editing scope is Edit. (2)
        # --allowedTools alone is not sufficient non-interactively -
        # --permission-mode acceptEdits is also required, or the edit
        # is refused even though the rule matches. (3) With both
        # present, a real adversarial prompt asking for a write
        # outside the granted scope_path was still correctly refused -
        # the glob-scoped rule genuinely holds, not just in the
        # unmatched-path-rejected case but under a real edit attempt.
        argv += ["--allowedTools", f"Edit({session.write_grant.scope_path}/**)",
                 "--permission-mode", "acceptEdits"]
    else:
        argv += ["--tools", ""]
    return argv


def _load_env():
    """Load CLAUDE_CODE_OAUTH_TOKEN from the environment or the env file,
    without ever writing or logging the value itself."""
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return True
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            line = line.strip()
            if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = line.split("=", 1)[1].strip().strip('"')
                return True
    return False


def _context_blob() -> str:
    """Everything the harness is allowed to know, gathered by Baseline
    itself - never fetched by the harness directly."""
    raw, hw_err = hardware.collect()
    hw = hardware.normalize(raw) if not hw_err else {"error": hw_err}
    net = network.check_lifeline()
    return (
        "Baseline deterministic state (read-only, gathered by Baseline itself):\n\n"
        f"HARDWARE:\n{json.dumps(hw, indent=2)}\n\n"
        f"NETWORK:\n{json.dumps(net, indent=2)}\n"
    )


def ask(prompt: str, *, runner: Runner = None, session: HarnessSession = None) -> str:
    """Send prompt + Baseline's own context through the HarnessAdapter.
    `runner`/`session` default to the real subprocess boundary and
    this process's one warm session - inject fakes for tests, never
    for production use."""
    if not _load_env():
        return (f"[ask] no CLAUDE_CODE_OAUTH_TOKEN found ({ENV_FILE} or env). "
                "Set it yourself, outside Baseline, then retry.")

    runner = runner if runner is not None else RealRunner()
    session = session if session is not None else _default_session
    full_prompt = f"{_context_blob()}\nQuestion: {prompt}\n"
    argv = build_ask_argv(full_prompt, session)
    try:
        proc = runner.run(argv, timeout=60)
    except subprocess.TimeoutExpired:
        return "[ask] harness timed out after 60s"
    except FileNotFoundError:
        return "[ask] claude CLI not found on this host"
    finally:
        session.started = True

    if proc.returncode != 0:
        return f"[ask] harness exited {proc.returncode}: {proc.stderr.strip()[:400]}"
    return proc.stdout.strip() or "[ask] empty response from harness"


def build_stream_argv(full_prompt: str, session: HarnessSession) -> list:
    """Same session/tools logic as build_ask_argv, plus the two flags
    real incremental streaming needs. Confirmed directly against the
    real installed CLI (decision record 41): --output-format
    stream-json and --verbose are required *together* under -p -
    omitting --verbose fails fast with "Error: When using --print,
    --output-format=stream-json requires --verbose", before any
    request is even sent."""
    base = build_ask_argv(full_prompt, session)
    return base[:3] + ["--output-format", "stream-json", "--verbose"] + base[3:]


def ask_streaming(prompt: str, on_text, *, runner: Runner = None, session: HarnessSession = None) -> str:
    """Like ask(), but calls on_text(text) as soon as the assistant's
    own message event lands in the NDJSON stream, instead of blocking
    until the whole process exits - real incremental feedback (item 3,
    docs/design/v0.1-work-queue.md), not simulated token-by-token
    typing. Returns the final answer text, same contract as ask()."""
    if not _load_env():
        message = (f"[ask] no CLAUDE_CODE_OAUTH_TOKEN found ({ENV_FILE} or env). "
                    "Set it yourself, outside Baseline, then retry.")
        on_text(message)
        return message

    runner = runner if runner is not None else RealRunner()
    session = session if session is not None else _default_session
    full_prompt = f"{_context_blob()}\nQuestion: {prompt}\n"
    argv = build_stream_argv(full_prompt, session)
    final_text = ""
    try:
        for line in runner.stream(argv, timeout=60):
            event = stream_json.parse_event(line)
            if event is None:
                continue
            text = stream_json.extract_assistant_text(event)
            if text:
                on_text(text)
                final_text = text
            result_text = stream_json.extract_final_result(event)
            if result_text is not None:
                final_text = result_text
    except subprocess.TimeoutExpired:
        return "[ask] harness timed out after 60s"
    except FileNotFoundError:
        return "[ask] claude CLI not found on this host"
    finally:
        session.started = True

    return final_text.strip() or "[ask] empty response from harness"


if __name__ == "__main__":
    print(ask(" ".join(sys.argv[1:]) or "Why am I offline?"))
