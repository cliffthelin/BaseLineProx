"""Harness CLIs the offline cache did not carry are installed once the internet is reachable (readiness-released, DR256)."""
from types import SimpleNamespace as NS

import harness_install as hi


class Runner:
    def __init__(self, ok=True):
        self.calls, self.ok = [], ok

    def run(self, argv, timeout=0):
        self.calls.append(list(argv))
        return NS(returncode=0 if self.ok else 1, stderr="boom" if not self.ok else "", stdout="")


def test_nothing_is_done_when_every_harness_tool_is_already_there():
    runner = Runner()
    result = hi.run_once(which=lambda b: "/usr/bin/" + b, connect=lambda: True, runner=runner)
    assert result == {"state": "nothing_missing", "installed": []} and runner.calls == []


def test_the_missing_tools_wait_for_the_internet_and_do_not_fail_without_it():
    runner = Runner()
    result = hi.run_once(which=lambda b: "/usr/bin/claude" if b == "claude" else None, connect=lambda: False, runner=runner)
    assert result["state"] == "waiting_for_internet" and result["missing"] == ["opencode", "codex"] and runner.calls == []


def test_missing_tools_are_installed_by_package_name_once_online():
    runner = Runner()
    result = hi.run_once(which=lambda b: "/usr/bin/claude" if b == "claude" else None, connect=lambda: True, runner=runner)
    assert result["state"] == "installed" and sorted(result["installed"]) == ["codex", "opencode"]
    assert ["npm", "install", "-g", "opencode-ai"] in runner.calls and ["npm", "install", "-g", "@openai/codex"] in runner.calls


def test_a_failed_install_is_reported_and_retried_next_time():
    result = hi.run_once(which=lambda b: None if b != "claude" else "/x", connect=lambda: True, runner=Runner(ok=False))
    assert result["state"] == "partly_failed" and result["installed"] == [] and set(result["failed"]) == {"opencode", "codex"}
