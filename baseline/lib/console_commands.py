"""The TUI Console tab's commands, as plain text lines, for the browser (parity, operator 2026-10-12).

Same command set and wording as the TUI: hardware, network, tether, ask <question>, grant write <directory>, revoke write, help.
Collaborators are passed in a Context so the same interpreter serves the web page and tests. A session per harness is kept in
`context.sessions`, exactly as the TUI's `_session_for` does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

HELP = ("commands: hardware, network, tether, ask <question>, grant write <directory>, revoke write, help")


@dataclass
class Context:
    hardware: Any
    network: Any
    tether: Any
    harness_registry: Any
    sessions: dict = field(default_factory=dict)
    snapshot: dict = field(default_factory=dict)          # {"read": () -> dict|None, "write": (dict) -> None}
    now: Callable[[], float] = lambda: 0.0


def _adapter(context, harness):
    try:
        return context.harness_registry.get_adapter(harness), None
    except context.harness_registry.HarnessAdapterError as exc:
        return None, f"Harness error: {exc}"


def _session(context, adapter, harness):
    if harness not in context.sessions:
        context.sessions[harness] = adapter.new_session()
    return context.sessions[harness]


def run(line: str, context: Context, harness: str = "claude") -> list:
    line = (line or "").strip()
    if not line:
        return []
    if line in ("help", "exit", "quit"):
        return [HELP]
    if line == "hardware":
        return _hardware(context)
    if line == "network":
        return _network(context)
    if line == "tether":
        return _tether(context)
    if line.startswith("ask "):
        return _ask(line[4:].strip(), context, harness)
    if line.startswith("grant write"):
        return _grant(line[len("grant write"):].strip(), context, harness)
    if line == "revoke write":
        return _revoke(context, harness)
    return [f"unknown command: {line!r} (try 'help')"]


def _hardware(context):
    raw, err = context.hardware.collect()
    if err:
        return [f"[hardware] collection failed: {err}"]
    current = context.hardware.normalize(raw)
    previous = context.snapshot["read"]() if context.snapshot else None
    lines = ["Hardware",
             f"System: {current['machine']['system']} ({current['machine']['type']})",
             f"CPU: {current['cpu']['model']} x{current['cpu']['cores']}",
             f"Memory: {current['memory']['total']} total, {current['memory']['used']} used",
             f"Kernel: {current['system']['kernel']} ({current['system']['distro']})"]
    if previous is None:
        lines.append("(no prior snapshot - this boot is the baseline)")
    elif previous == current:
        lines.append("(unchanged since last snapshot)")
    else:
        lines.append("(hardware differs from last snapshot)")
    if context.snapshot:
        context.snapshot["write"](current)
    return lines


def _network(context):
    facts = context.network.check_lifeline()
    lines = ["Lifeline Networking"] + [f"{f['fact']}: {'OK' if f['ok'] else 'FAIL'} - {f['detail']}" for f in facts]
    if facts and not facts[-1]["ok"]:
        lines.append(f"Stopped at: {facts[-1]['fact']} - everything upstream of this is fine.")
    elif facts:
        lines.append("Lifeline fully up: hardware -> network -> LLM provider all reachable.")
    return lines


def _tether(context):
    result = context.tether.auto_tether()
    if result["stage"] == "no_candidate":
        return [f"No tether device found: {result['detail']}"]
    lines = [f"Trying: {result.get('interface', '?')} (candidates seen: {', '.join(result.get('candidates', [])) or 'none'})"]
    if result["ok"]:
        lines.append(f"Tether up: {result['interface']} -> {result['address']} ({result['detail']})")
        lines += _network(context)
    else:
        lines.append(f"FAIL ({result['stage']}): {result['detail']}")
    return lines


def _ask(question, context, harness):
    adapter, error = _adapter(context, harness)
    if error:
        return [error]
    if adapter is None:
        return ["No adapter for the currently selected harness."]
    return [adapter.ask(question, session=_session(context, adapter, harness))]


def _grant(path, context, harness):
    adapter, error = _adapter(context, harness)
    if error:
        return [error]
    if not context.harness_registry.supports_write_grant(adapter):
        return [f"The current harness ({harness}) doesn't support a write grant."]
    if not path:
        return ["usage: grant write <directory>"]
    try:
        grant = adapter.grant_write_scope(_session(context, adapter, harness), path,
                                          authorized_by="operator via browser console", now=context.now())
    except ValueError as exc:
        return [str(exc)]
    return [f"Write access granted, scoped to {grant.scope_path}",
            "This is a one-time grant for this session only - it ends when Baseline restarts and is never remembered "
            "next time. Type 'revoke write' to end it sooner."]


def _revoke(context, harness):
    adapter, error = _adapter(context, harness)
    if error:
        return [error]
    if not context.harness_registry.supports_write_grant(adapter):
        return [f"The current harness ({harness}) doesn't support a write grant."]
    session = _session(context, adapter, harness)
    had = session.write_grant is not None
    adapter.revoke_write_scope(session)
    return ["Write access revoked for this session."] if had else ["No write access was granted this session."]
