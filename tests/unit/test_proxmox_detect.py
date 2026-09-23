"""Unit tests for proxmox_detect.py - the thin gate that stops Baseline
from re-invoking the installer when Proxmox is already present."""
from fake_runner import FakeRunner, FakeProc

import proxmox_detect as pd


def test_not_installed_when_no_signal_present():
    runner = FakeRunner()  # dpkg/pveversion both fail (default FakeProc rc=0 empty stdout... )
    runner.command_responses = [
        (lambda a: a[:1] == ["dpkg-query"], FakeProc(1, "", "no packages found")),
        (lambda a: a[:1] == ["pveversion"], FakeProc(127, "", "command not found")),
    ]
    state = pd.detect_proxmox_install(runner)
    assert state.installed is False
    assert state.evidence == []


def test_installed_via_dpkg_version():
    runner = FakeRunner()
    runner.command_responses = [
        (lambda a: a[:1] == ["dpkg-query"], FakeProc(0, "8.2.4", "")),
        (lambda a: a[:1] == ["pveversion"], FakeProc(127, "", "not found")),
    ]
    state = pd.detect_proxmox_install(runner)
    assert state.installed is True
    assert state.version == "8.2.4"
    assert "8.2.4" in state.evidence[0]


def test_installed_via_pveversion_when_dpkg_query_absent():
    runner = FakeRunner()
    runner.command_responses = [
        (lambda a: a[:1] == ["dpkg-query"], FakeProc(1, "", "")),
        (lambda a: a[:1] == ["pveversion"], FakeProc(0, "pve-manager/8.2.4/xyz", "")),
    ]
    state = pd.detect_proxmox_install(runner)
    assert state.installed is True
    assert state.version == "pve-manager/8.2.4/xyz"


def test_installed_via_pmxcfs_mountpoint_alone():
    runner = FakeRunner(files={"/etc/pve": ""})
    runner.command_responses = [
        (lambda a: a[:1] == ["dpkg-query"], FakeProc(1, "", "")),
        (lambda a: a[:1] == ["pveversion"], FakeProc(127, "", "")),
    ]
    state = pd.detect_proxmox_install(runner)
    assert state.installed is True
    assert state.version is None  # no version signal, just presence
    assert any("pmxcfs" in e for e in state.evidence)


def test_decision_skips_installer_when_already_installed():
    state = pd.InstallState(installed=True, version="8.2.4", evidence=["dpkg-query reports proxmox-ve 8.2.4 installed"])
    decision = pd.decide_next_action(state)
    assert decision.action == "run_diagnostics_only"
    assert "already installed" in decision.reason


def test_decision_runs_installer_when_not_installed():
    state = pd.InstallState(installed=False, version=None, evidence=[])
    decision = pd.decide_next_action(state)
    assert decision.action == "run_installer"


def test_check_convenience_entry_point_composes_detect_and_decide():
    runner = FakeRunner()
    runner.command_responses = [
        (lambda a: a[:1] == ["dpkg-query"], FakeProc(0, "8.2.4", "")),
        (lambda a: a[:1] == ["pveversion"], FakeProc(0, "pve-manager/8.2.4", "")),
    ]
    decision = pd.check(runner)
    assert decision.action == "run_diagnostics_only"
    assert decision.state.installed is True
