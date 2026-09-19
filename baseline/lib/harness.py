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
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, "/opt/baseline/lib")
import hardware  # noqa: E402
import network  # noqa: E402

ENV_FILE = "/etc/baseline/harness.env"


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


def ask(prompt: str) -> str:
    """Send prompt + Baseline's own context through the HarnessAdapter."""
    if not _load_env():
        return (f"[ask] no CLAUDE_CODE_OAUTH_TOKEN found ({ENV_FILE} or env). "
                "Set it yourself, outside Baseline, then retry.")

    full_prompt = f"{_context_blob()}\nQuestion: {prompt}\n"
    try:
        proc = subprocess.run(
            ["claude", "-p", full_prompt, "--tools", ""],
            capture_output=True, text=True, timeout=60,
            env={**os.environ},
        )
    except subprocess.TimeoutExpired:
        return "[ask] harness timed out after 60s"
    except FileNotFoundError:
        return "[ask] claude CLI not found on this host"

    if proc.returncode != 0:
        return f"[ask] harness exited {proc.returncode}: {proc.stderr.strip()[:400]}"
    return proc.stdout.strip() or "[ask] empty response from harness"


if __name__ == "__main__":
    print(ask(" ".join(sys.argv[1:]) or "Why am I offline?"))
