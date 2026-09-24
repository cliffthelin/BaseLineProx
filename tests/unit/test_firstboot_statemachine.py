"""Unit tests for firstboot_statemachine.py (Gate E) - the real,
integrated state machine connecting proxmox_detect.py,
firstboot_network_repair.py (Gate A's real repair pipeline, reused
unchanged), and package install/verification for the five diagnostic
tools. Reuses test_phase0_additive_repair.py's `make_additive_runner`
(a fully real, already-proven FakeRunner setup for the repair pipeline
itself) rather than re-deriving that scripting - this file's own
scripts cover only the new layers: proxmox detection, package install,
and package verification."""
import json

import pytest

from fake_runner import FakeProc
from test_phase0_additive_repair import (
    FIXTURE_A_IPV6_ONLY,
    broken_facts_fixture_a,
    healthy_facts,
    make_additive_runner,
)

import firstboot_statemachine as fsm


def full_runner(package_install_ok=True, packages_installed=True, iperf_enabled="disabled",
                 iperf_active="inactive", iperf_listening=False, **kwargs):
    """`make_additive_runner`'s scripts, plus this module's own
    package-install/verify layer prepended so they're checked first -
    FakeRunner's command_responses matches in list order, first hit
    wins, and `dpkg-query`/`ss` are called by both layers for
    different purposes."""
    r = make_additive_runner(**kwargs)

    install_proc = (FakeProc(0, "Setting up lm-sensors ...\n", "") if package_install_ok
                     else FakeProc(100, "", "E: Unable to locate package lm-sensors"))
    dpkg_lines = "\n".join(
        f"{p} install ok installed" if packages_installed else f"{p} unknown ok not-installed"
        for p in fsm.DIAGNOSTIC_PACKAGES
    )
    ss_output = ("State  Recv-Q Send-Q Local Address:Port  Peer Address:Port\n"
                 + ("LISTEN 0      128    0.0.0.0:5201        0.0.0.0:*\n" if iperf_listening else ""))

    prepended = [
        (lambda a: "apt-get" in a and "install" in a, install_proc),
        (lambda a: a[:1] == ["dpkg-query"] and "ifupdown2" not in a,
         FakeProc(0, dpkg_lines, "")),
        (lambda a: a[:3] == ["systemctl", "is-enabled", "iperf3"], FakeProc(0, iperf_enabled, "")),
        (lambda a: a[:3] == ["systemctl", "is-active", "iperf3"], FakeProc(0, iperf_active, "")),
        (lambda a: a[:1] == ["ss"], FakeProc(0, ss_output, "")),
    ]
    r.command_responses = prepended + r.command_responses
    return r


# --------------------------------------------------------------------------
# Successful completion, end to end
# --------------------------------------------------------------------------

def test_successful_completion_commits_after_confirm_network_and_packages(tmp_path):
    r = full_runner()
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "committed"
    assert (tmp_path / "complete").exists()
    journal = json.loads((tmp_path / "journal.json").read_text())
    states = [e["state"] for e in journal["history"]]
    assert states == ["created", "detected", "discovered", "proposed", "confirmed",
                       "network_repaired", "packages_installed", "packages_verified", "committed"]
    assert "iface vmbr0 inet dhcp" in r.files["/etc/network/interfaces"]


def test_already_healthy_lifeline_still_requires_confirmation_for_packages(tmp_path):
    r = full_runner()
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=healthy_facts)
    assert result["action"] == "committed"
    assert r.writes == []  # no network file was ever touched - lifeline was already healthy


# --------------------------------------------------------------------------
# Declined / refused authorization
# --------------------------------------------------------------------------

def test_declined_confirmation_makes_no_change_and_does_not_commit(tmp_path):
    r = full_runner()
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["not confirm\n", ""]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "declined"
    assert not (tmp_path / "complete").exists()
    assert r.files["/etc/network/interfaces"] == FIXTURE_A_IPV6_ONLY
    assert not any(c[:2] == ["apt-get", "install"] for c in r.calls)


def test_eof_on_stdin_never_treated_as_confirmation(tmp_path):
    r = full_runner()
    result = fsm.run(r, state_dir=tmp_path, stdin=iter([]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "declined"
    assert not (tmp_path / "complete").exists()


def test_no_safe_repair_candidate_refuses_without_any_prompt(tmp_path):
    r = full_runner(files={"/etc/network/interfaces": "auto lo\niface lo inet loopback\n"})
    result = fsm.run(r, state_dir=tmp_path, print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "refused"
    assert not (tmp_path / "complete").exists()
    assert not any(c[:2] == ["apt-get", "install"] for c in r.calls)


# --------------------------------------------------------------------------
# Network failure blocks package installation
# --------------------------------------------------------------------------

def test_network_verification_failure_blocks_package_installation(tmp_path):
    r = full_runner(verify_ok=False)
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "network_failed"
    assert result["package_install_allowed"] is False
    assert not (tmp_path / "complete").exists()
    assert not any(c[:2] == ["apt-get", "install"] for c in r.calls)


def test_network_apply_failure_blocks_package_installation(tmp_path):
    r = full_runner(apply_ok=False)
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "network_failed"
    assert not any(c[:2] == ["apt-get", "install"] for c in r.calls)


# --------------------------------------------------------------------------
# Package install/verify failure blocks completion
# --------------------------------------------------------------------------

def test_package_install_failure_blocks_completion(tmp_path):
    r = full_runner(package_install_ok=False)
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "packages_failed"
    assert not (tmp_path / "complete").exists()


def test_package_verification_failure_missing_package_blocks_completion(tmp_path):
    r = full_runner(packages_installed=False)
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "packages_verify_failed"
    assert not (tmp_path / "complete").exists()


def test_iperf3_active_fails_verification_and_blocks_completion(tmp_path):
    r = full_runner(iperf_active="active")
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "packages_verify_failed"
    assert not (tmp_path / "complete").exists()


def test_iperf3_listening_fails_verification_and_blocks_completion(tmp_path):
    r = full_runner(iperf_listening=True)
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "packages_verify_failed"
    assert not (tmp_path / "complete").exists()


# --------------------------------------------------------------------------
# Completion marker prevents re-trigger
# --------------------------------------------------------------------------

def test_completion_marker_prevents_rerun(tmp_path):
    r = full_runner()
    fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
             check_lifeline_fn=broken_facts_fixture_a)
    calls_before = len(r.calls)

    result2 = fsm.run(r, state_dir=tmp_path, print_fn=lambda *a: None)
    assert result2["action"] == "already_completed"
    assert len(r.calls) == calls_before  # nothing was re-run


# --------------------------------------------------------------------------
# Interruption recovery / proposal reuse after restart
# --------------------------------------------------------------------------

def test_resumes_from_proposed_state_without_rediscovering(tmp_path):
    r = full_runner()
    # Simulate a first run interrupted right after the proposal was
    # journaled but before CONFIRM was ever read (state_dir now holds
    # exactly what a real crash at that point would leave behind).
    fsm.run(r, state_dir=tmp_path, stdin=iter([]), print_fn=lambda *a: None,
            check_lifeline_fn=broken_facts_fixture_a)
    journal_before = json.loads((tmp_path / "journal.json").read_text())
    assert journal_before["state"] == "proposed"
    discover_calls_before = sum(1 for c in r.calls if c == ["ip", "route", "show", "default"])

    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    discover_calls_after = sum(1 for c in r.calls if c == ["ip", "route", "show", "default"])
    assert result["action"] == "committed"
    assert discover_calls_after == discover_calls_before  # discovery was NOT redone


def test_resumes_from_network_repaired_state_without_reapplying(tmp_path):
    r = full_runner()
    # Hand-construct a journal exactly at "network_repaired" (success) -
    # matching a real interruption right after that transition was
    # durably written but before package installation began.
    diagnosis = {"needs_repair": True, "mode": "additive", "target": "vmbr0",
                 "target_kind": "bridge", "physical_devices": ["ens3"],
                 "diff": {"action": "add", "file": "/etc/network/interfaces",
                          "before": [], "after": ["iface vmbr0 inet dhcp"]}, "reason": ""}
    history = [
        {"state": "created", "ts": "x"},
        {"state": "detected", "ts": "x", "proxmox_installed": True, "proxmox_version": "8.2", "proxmox_evidence": []},
        {"state": "discovered", "ts": "x", "discovery": {"lifeline_ok": False, "facts": broken_facts_fixture_a()}},
        {"state": "proposed", "ts": "x", "diagnosis": diagnosis},
        {"state": "confirmed", "ts": "x"},
        {"state": "network_repaired", "ts": "x", "network_ok": True, "network_detail": "already applied"},
    ]
    (tmp_path / "journal.json").write_text(json.dumps({"state": "network_repaired", "history": history}))

    result = fsm.run(r, state_dir=tmp_path, print_fn=lambda *a: None)
    assert result["action"] == "committed"
    # The repair pipeline itself was never re-invoked on resume - no
    # ifreload apply call happened in this run.
    assert not any(c == ["ifreload", "-a"] for c in r.calls)


# --------------------------------------------------------------------------
# Corrupted journal - fail closed, never resume into a consequential state
# --------------------------------------------------------------------------

def test_corrupted_journal_starts_fresh_not_trusted_for_resume(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "journal.json").write_text("{not valid json at all")
    r = full_runner()
    messages = []
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=messages.append,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "committed"
    assert any("corrupted" in m for m in messages)


def test_journal_with_unknown_state_value_starts_fresh(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "journal.json").write_text(json.dumps({"state": "not_a_real_state", "history": []}))
    r = full_runner()
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "committed"


def test_completion_marker_is_never_bypassed_by_a_corrupted_journal(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    fsm.mark_complete(tmp_path)
    (tmp_path / "journal.json").write_text("{corrupted")
    r = full_runner()
    result = fsm.run(r, state_dir=tmp_path, print_fn=lambda *a: None)
    assert result["action"] == "already_completed"
    assert r.calls == []  # the marker check happens before anything else, always


# --------------------------------------------------------------------------
# Package install/verify helpers, tested directly
# --------------------------------------------------------------------------

def test_install_diagnostic_tools_uses_noninteractive_env_and_exact_package_list():
    r = full_runner()
    result = fsm.install_diagnostic_tools(r)
    assert result["ok"] is True
    install_call = next(c for c in r.calls if "apt-get" in c and "install" in c)
    assert "DEBIAN_FRONTEND=noninteractive" in install_call
    for pkg in fsm.DIAGNOSTIC_PACKAGES:
        assert pkg in install_call


def test_verify_diagnostic_tools_reports_iperf3_safe_by_default():
    r = full_runner()
    result = fsm.verify_diagnostic_tools(r)
    assert result["ok"] is True
    assert result["iperf3_safe"] is True
    assert set(result["installed"]) == set(fsm.DIAGNOSTIC_PACKAGES)
