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


class RealRunner(Runner):
    def run(self, argv, timeout=60):
        return subprocess.run(argv, capture_output=True, text=True,
                               timeout=timeout, env={**os.environ})


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


def build_ask_argv(full_prompt: str, session: HarnessSession) -> list:
    argv = ["claude", "-p", full_prompt]
    argv += ["--session-id", session.session_id] if not session.started else ["-c"]
    if session.write_grant is not None:
        # NOT yet verified against the real Claude Code CLI's actual
        # --allowedTools pattern syntax for a path-scoped Write tool -
        # see decision record 32's "explicitly not decided here". Pin
        # this exact shape in tests so a real-CLI verification pass
        # has one concrete thing to confirm or correct, rather than
        # leaving the mapping unspecified.
        argv += ["--allowedTools", f"Write({session.write_grant.scope_path}/**)"]
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


if __name__ == "__main__":
    print(ask(" ".join(sys.argv[1:]) or "Why am I offline?"))
