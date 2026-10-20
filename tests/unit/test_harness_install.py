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


def test_audio_and_bluetooth_packages_are_installed_once_online_and_only_the_missing_ones():
    runner = Runner()
    have = {"pipewire", "bluez"}
    result = hi.run_extras(installed=lambda p: p in have, connect=lambda: True, runner=runner)
    wanted = [p for p in hi.APT_PACKAGES if p not in have]
    assert result["state"] == "installed" and result["installed"] == wanted
    assert runner.calls == [["apt-get", "install", "-y", "--no-install-recommends", *wanted]]


def test_extras_wait_for_the_internet_and_report_when_nothing_is_missing():
    runner = Runner()
    assert hi.run_extras(installed=lambda p: True, connect=lambda: False, runner=runner)["state"] == "nothing_missing"
    assert hi.run_extras(installed=lambda p: False, connect=lambda: False, runner=runner)["state"] == "waiting_for_internet"
    assert runner.calls == []


def test_the_audio_and_bluetooth_set_covers_the_sound_server_the_bluetooth_stack_and_the_bridge_between_them():
    for package in ("pipewire", "pipewire-pulse", "wireplumber", "bluez", "libspa-0.2-bluetooth"):
        assert package in hi.APT_PACKAGES
