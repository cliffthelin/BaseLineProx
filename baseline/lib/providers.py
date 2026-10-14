#!/usr/bin/env python3
"""AI provider/harness availability - Step 6 follow-up.

Three states per provider, not a collapsed up/down flag:
- "reachable": actually verified live, this check cycle.
- "available": configured (a key/local service exists) but not tested
  right now - checking every provider on every network refresh would be
  slow and noisy.
- "unreachable": configured but a live check just failed.
- "unconfigured": no key/service found at all.

Separately, HARNESSES are the orchestration tool (Claude Code, OpenCode,
etc.) that talks to a provider - only Claude Code has a real adapter
(baseline/lib/harness.py) as of V0.1. The others are listed so the
operator can see what's plausible to add, not to pretend they work.
"""
import os
import socket
from pathlib import Path

HARNESS_ENV_FILE = "/etc/baseline/harness.env"


def _env_or_file(*var_names: str) -> bool:
    """Whether any named credential is configured, preserving read errors.

    An unreadable credential file is unknown, not evidence that no key is
    configured. Environment values are checked first so an authoritative
    process credential remains usable even if the optional file is unreadable.
    """
    if any(os.environ.get(name) for name in var_names):
        return True
    import vault                      # USER_PERSONAL's and USER_ADMIN's vaults (DR258); unreadable ones are skipped
    if any(vault.lookup(name, environ={}) for name in var_names):
        return True
    try:
        lines = Path(HARNESS_ENV_FILE).read_text().splitlines()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RuntimeError(f"cannot inspect provider credential configuration: {exc}") from exc
    configured = set()
    for line in lines:
        name, separator, value = line.partition("=")
        if separator and name.strip() in var_names and value.strip():
            configured.add(name.strip())
    return bool(configured)


def _configured_result(name: str, var_names: tuple[str, ...], provider: str) -> dict:
    try:
        configured = _env_or_file(*var_names)
    except RuntimeError as exc:
        return {"name": name, "state": "unknown", "detail": str(exc)}
    if configured:
        return {"name": name, "state": "available", "detail": f"{provider} credential configured; live access not checked"}
    return {"name": name, "state": "unconfigured",
            "detail": f"no {provider} credential configured - add it to {HARNESS_ENV_FILE}"
                      + (" (run /opt/baseline/bin/baseline-auth-setup.sh)" if provider == "Claude" else "")}


def display_status(state: str) -> str:
    """Map provider observations to the dashboard without collapsing unknown."""
    return {"reachable": "Reachable", "available": "Available",
            "unreachable": "Unreachable", "unconfigured": "Not set up",
            "unknown": "Unknown"}.get(state, "Unknown")


def _tcp_probe(host: str, port: int, timeout: float = 1.0) -> tuple[str, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return "reachable", f"TCP connection established to {host}:{port}"
    except ConnectionRefusedError as exc:
        return "unreachable", f"TCP connection refused by {host}:{port}: {exc}"
    except (TimeoutError, OSError) as exc:
        return "unknown", f"TCP probe to {host}:{port} could not determine service state: {exc}"


def check_providers():
    """Return a list of {"name", "state", "detail"} - state one of
    reachable/available/unreachable/unconfigured. Cheap checks only
    (env/file presence, local port probes) - not live API calls, so this
    can run on every UI refresh without being slow."""
    results = []

    results.append(_configured_result("Claude Subscription", ("CLAUDE_CODE_OAUTH_TOKEN",), "Claude"))

    ollama_state, ollama_detail = _tcp_probe("127.0.0.1", 11434, timeout=0.5)
    results.append({"name": "Ollama (local)", "state": ollama_state, "detail": ollama_detail})

    results.append(_configured_result("OpenAI", ("OPENAI_API_KEY",), "OpenAI"))

    results.append(_configured_result("Google Gemini", ("GOOGLE_API_KEY", "GEMINI_API_KEY"), "Google Gemini"))

    results.append(_configured_result("OpenRouter", ("OPENROUTER_API_KEY",), "OpenRouter"))

    return results


# Harnesses = the orchestration CLI, not the model/provider underneath it.
# This is the user-selectable set: every entry must have a real adapter.
# Do not add a candidate CLI until its invocation and permission model are
# verified and its adapter passes the HarnessAdapter contract.
#
# "adapter_module" names the importable module implementing the
# HarnessAdapter contract (see harness_adapter.py) - harness_registry.py
# is the only thing that reads this field; bin/baseline dispatches
# through the registry rather than hardcoding a specific adapter
# module, so selecting a different harness in the Chat tab actually
# changes which module runs. Must always agree with "implemented":
# True needs a real adapter_module, False must have none - a harness
# claiming to be implemented with nothing to import would be a lie the
# dropdown tells the operator, not a shortcut worth taking.
HARNESSES = [
    {"id": "claude", "name": "Claude Code", "implemented": True, "adapter_module": "harness"},
    {"id": "opencode", "name": "OpenCode", "implemented": True, "adapter_module": "opencode_adapter"},
    {"id": "codex", "name": "OpenAI Codex", "implemented": True, "adapter_module": "codex_adapter"},
]

# Each harness's command-line tool and the credential it needs, for the "is it there and set up" view (/ai-setup).
HARNESS_REQUIREMENTS = {
    "claude": {"binary": "claude", "credential": ("CLAUDE_CODE_OAUTH_TOKEN",)},
    "opencode": {"binary": "opencode", "credential": ()},       # OpenCode brings its own provider login
    "codex": {"binary": "codex", "credential": ("OPENAI_API_KEY",)},
}


def harness_status(which=None) -> list:
    """[{id, name, installed, credential}] - credential is 'set', 'missing' or 'not needed'."""
    import shutil
    find = which or shutil.which
    rows = []
    for entry in HARNESSES:
        need = HARNESS_REQUIREMENTS.get(entry["id"], {"binary": entry["id"], "credential": ()})
        if need["credential"]:
            try:
                credential = "set" if _env_or_file(*need["credential"]) else "missing"
            except RuntimeError:
                credential = "unknown"
        else:
            credential = "not needed"
        rows.append({"id": entry["id"], "name": entry["name"], "installed": bool(find(need["binary"])), "credential": credential})
    return rows
