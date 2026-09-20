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


def _env_or_file(var_name: str) -> bool:
    if os.environ.get(var_name):
        return True
    if os.path.exists(HARNESS_ENV_FILE):
        try:
            for line in open(HARNESS_ENV_FILE):
                if line.strip().startswith(f"{var_name}="):
                    return True
        except OSError:
            pass
    return False


def _tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_providers():
    """Return a list of {"name", "state", "detail"} - state one of
    reachable/available/unreachable/unconfigured. Cheap checks only
    (env/file presence, local port probes) - not live API calls, so this
    can run on every UI refresh without being slow."""
    results = []

    if _env_or_file("CLAUDE_CODE_OAUTH_TOKEN"):
        results.append({"name": "Claude Subscription", "state": "available", "detail": "token configured; verified live via harness.ask()"})
    else:
        results.append({"name": "Claude Subscription", "state": "unconfigured", "detail": "run baseline-auth-setup.sh"})

    if _tcp_open("127.0.0.1", 11434, timeout=0.5):
        results.append({"name": "Ollama (local)", "state": "reachable", "detail": "responding on 127.0.0.1:11434"})
    else:
        results.append({"name": "Ollama (local)", "state": "unconfigured", "detail": "no local Ollama service on :11434"})

    if _env_or_file("OPENAI_API_KEY"):
        results.append({"name": "OpenAI", "state": "available", "detail": "OPENAI_API_KEY configured"})
    else:
        results.append({"name": "OpenAI", "state": "unconfigured", "detail": "no OPENAI_API_KEY"})

    if _env_or_file("GOOGLE_API_KEY") or _env_or_file("GEMINI_API_KEY"):
        results.append({"name": "Google Gemini", "state": "available", "detail": "API key configured"})
    else:
        results.append({"name": "Google Gemini", "state": "unconfigured", "detail": "no GOOGLE_API_KEY/GEMINI_API_KEY"})

    if _env_or_file("OPENROUTER_API_KEY"):
        results.append({"name": "OpenRouter", "state": "available", "detail": "OPENROUTER_API_KEY configured"})
    else:
        results.append({"name": "OpenRouter", "state": "unconfigured", "detail": "no OPENROUTER_API_KEY"})

    return results


# Harnesses = the orchestration CLI, not the model/provider underneath it.
# "implemented" means baseline/lib has a real HarnessAdapter for it -
# selecting anything else in the TUI shows "not implemented" rather than
# silently failing or faking a response.
HARNESSES = [
    {"id": "claude", "name": "Claude Code", "implemented": True},
    {"id": "opencode", "name": "OpenCode", "implemented": False},
    {"id": "hermes", "name": "Hermes", "implemented": False},
    {"id": "pi", "name": "Pi", "implemented": False},
    {"id": "deepseek", "name": "DeepSeek", "implemented": False},
    {"id": "grokbot", "name": "GrokBot", "implemented": False},
]
