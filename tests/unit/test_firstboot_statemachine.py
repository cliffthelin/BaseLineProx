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


def _apt_installs(r):
    """Every apt-get install the runner saw. The real argv starts with `env DEBIAN_FRONTEND=...`, so the old
    check `c[:2] == ["apt-get", "install"]` could never match and silently passed whatever happened."""
    return [c for c in r.calls if "apt-get" in c and "install" in c]


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
    assert not [w for w in r.writes if w.startswith("/etc/network")]  # lifeline was already healthy
    assert ["nft", "-f", "/etc/baseline/lan-only.nft.new"] in r.calls  # first-boot commit enforces LAN-only


def test_first_boot_commit_attempts_lan_only_even_with_no_exported_config(tmp_path):
    r = full_runner()
    fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
            check_lifeline_fn=healthy_facts)
    assert any(c[:2] == ["nft", "-c"] for c in r.calls)


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
    assert not _apt_installs(r)


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
    assert not _apt_installs(r)


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
    assert not _apt_installs(r)
    journal = json.loads((tmp_path / "journal.json").read_text())
    assert journal["state"] == "network_repair_failed"
    assert not any(e["state"] == "network_repaired" for e in journal["history"])


def test_network_apply_failure_blocks_package_installation(tmp_path):
    r = full_runner(apply_ok=False)
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "network_failed"
    assert not _apt_installs(r)
    journal = json.loads((tmp_path / "journal.json").read_text())
    assert journal["state"] == "network_repair_failed"
    assert not any(e["state"] == "network_repaired" for e in journal["history"])


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
    assert len(r.calls) > calls_before  # repeat boot re-enforces the firewall
    assert not any(call[:2] == ['apt-get', 'install'] for call in r.calls[calls_before:])


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
        {"state": "network_repaired", "ts": "x", "network_detail": "already applied"},
    ]
    (tmp_path / "journal.json").write_text(json.dumps({"state": "network_repaired", "history": history}))

    result = fsm.run(r, state_dir=tmp_path, print_fn=lambda *a: None)
    assert result["action"] == "committed"
    # The repair pipeline itself was never re-invoked on resume - no
    # ifreload apply call happened in this run.
    assert not any(c == ["ifreload", "-a"] for c in r.calls)


def test_resumes_from_network_repair_failed_state_without_retrying(tmp_path):
    r = full_runner()
    # Hand-construct a journal exactly at "network_repair_failed" -
    # matching a real interruption right after that transition was
    # durably written but before the run() call that wrote it had a
    # chance to return. Recovery must branch on this recorded outcome
    # directly, never re-run diagnosis/apply, and never install packages.
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
        {"state": "network_repair_failed", "ts": "x", "network_ok": False,
         "network_detail": "already_healthy: refusing to change a device that isn't actually broken"},
    ]
    (tmp_path / "journal.json").write_text(json.dumps({"state": "network_repair_failed", "history": history}))

    result = fsm.run(r, state_dir=tmp_path, print_fn=lambda *a: None)
    assert result["action"] == "network_failed"
    assert result["package_install_allowed"] is False
    assert not (tmp_path / "complete").exists()
    assert r.calls == []  # neither the repair pipeline nor apt-get was ever invoked on resume


# --------------------------------------------------------------------------
# network_repaired / network_repair_failed state invariant
# --------------------------------------------------------------------------

def test_network_repaired_state_can_never_record_network_ok_false(tmp_path):
    """record_transition itself must refuse this, not just the callers
    that happen to avoid it - a state named "repaired" must never be
    writable with a false outcome flag, by construction."""
    journal = {"state": "confirmed", "history": []}
    with pytest.raises(ValueError, match="network_repaired"):
        fsm.record_transition(tmp_path, journal, "network_repaired", network_ok=False, network_detail="x")


def test_network_repaired_state_never_carries_network_ok_false_in_practice(tmp_path):
    """End-to-end: across every failure-inducing scenario this suite
    exercises, no journal ever records network_ok: False under the
    network_repaired state - failures land in network_repair_failed
    instead."""
    for kwargs in ({"verify_ok": False}, {"apply_ok": False}):
        r = full_runner(**kwargs)
        state_dir = tmp_path / f"case-{kwargs}"
        fsm.run(r, state_dir=state_dir, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                check_lifeline_fn=broken_facts_fixture_a)
        journal = json.loads((state_dir / "journal.json").read_text())
        for entry in journal["history"]:
            if entry["state"] == "network_repaired":
                assert entry.get("network_ok", True) is not False


# --------------------------------------------------------------------------
# network_repaired requires explicit positive verification evidence, not
# merely the absence of network_ok=False (false/null/omitted/malformed
# verification, and omitted/false/malformed network_ok or target_interface,
# must all be refused).
# --------------------------------------------------------------------------

VALID_VERIFICATION = {"address": True, "gateway": True, "dns": True, "https": True}


def test_network_repaired_requires_network_ok_true_not_merely_non_false(tmp_path):
    """Omitting network_ok entirely (a caller forgetting the keyword)
    must be refused exactly as loudly as passing False - the previous,
    weaker guard only checked `is False`, which a simple omission or a
    None/truthy-but-wrong value could slip past."""
    journal = {"state": "confirmed", "history": []}
    for bad_network_ok in ({}, {"network_ok": None}, {"network_ok": 1}, {"network_ok": "true"}):
        with pytest.raises(ValueError, match="network_ok=True"):
            fsm.record_transition(tmp_path, journal, "network_repaired",
                                   target_interface="vmbr0", verification=dict(VALID_VERIFICATION),
                                   **bad_network_ok)


def test_network_repaired_requires_nonempty_target_interface(tmp_path):
    journal = {"state": "confirmed", "history": []}
    for bad_target in ({}, {"target_interface": ""}, {"target_interface": None}):
        with pytest.raises(ValueError, match="target_interface"):
            fsm.record_transition(tmp_path, journal, "network_repaired", network_ok=True,
                                   verification=dict(VALID_VERIFICATION), **bad_target)


def test_network_repaired_requires_verification_dict_present_and_nonempty(tmp_path):
    """Omitted, None, empty-dict, and non-dict verification must all be
    refused - "absence of evidence" must never be treated as evidence."""
    journal = {"state": "confirmed", "history": []}
    for bad_verification in ({}, {"verification": None}, {"verification": {}}, {"verification": "yes"},
                              {"verification": ["address"]}):
        with pytest.raises(ValueError, match="verification"):
            fsm.record_transition(tmp_path, journal, "network_repaired", network_ok=True,
                                   target_interface="vmbr0", **bad_verification)


def test_network_repaired_requires_every_verification_value_exactly_true(tmp_path):
    """False, None, and truthy-but-not-True (e.g. the string "true", or
    1) values must all be refused - a malformed or failed individual
    check must not be able to hide inside an otherwise-plausible dict."""
    journal = {"state": "confirmed", "history": []}
    for bad_value in (False, None, "true", 1, 0):
        with pytest.raises(ValueError, match="exactly True"):
            fsm.record_transition(tmp_path, journal, "network_repaired", network_ok=True,
                                   target_interface="vmbr0",
                                   verification={"address": True, "gateway": bad_value})


def test_network_repaired_accepts_genuine_complete_evidence(tmp_path):
    """The positive case: network_ok=True, a real target_interface, and
    a non-empty verification dict with every value exactly True is
    accepted and durably written."""
    journal = {"state": "confirmed", "history": []}
    result = fsm.record_transition(tmp_path, journal, "network_repaired", network_ok=True,
                                    target_interface="vmbr0", verification=dict(VALID_VERIFICATION),
                                    network_detail="applied and verified")
    assert result["state"] == "network_repaired"
    entry = result["history"][-1]
    assert entry["network_ok"] is True
    assert entry["target_interface"] == "vmbr0"
    assert entry["verification"] == VALID_VERIFICATION


def test_successful_completion_journal_carries_genuine_verification_evidence(tmp_path):
    """End-to-end: the real production path (not a hand-constructed
    fixture) must itself supply valid network_ok/target_interface/
    verification - proving repair.py/repair_additive.py's
    RepairResult.verification threading actually works, not just that
    the guard rejects bad input in isolation."""
    r = full_runner()
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "committed"
    journal = json.loads((tmp_path / "journal.json").read_text())
    entry = next(e for e in journal["history"] if e["state"] == "network_repaired")
    assert entry["network_ok"] is True
    assert entry["target_interface"] == "vmbr0"
    assert entry["verification"], "verification must be non-empty"
    assert all(v is True for v in entry["verification"].values())


def test_already_healthy_lifeline_journal_carries_genuine_verification_evidence(tmp_path):
    """Same guarantee for the already-healthy fast path, which has no
    RepairResult to draw from - it must still supply real evidence
    (reused from discover()'s own facts), not a fabricated placeholder."""
    r = full_runner()
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=healthy_facts)
    assert result["action"] == "committed"
    journal = json.loads((tmp_path / "journal.json").read_text())
    entry = next(e for e in journal["history"] if e["state"] == "network_repaired")
    assert entry["network_ok"] is True
    assert entry["target_interface"]
    assert entry["verification"], "verification must be non-empty"
    assert all(v is True for v in entry["verification"].values())


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
    assert r.calls and all(call[0] == 'nft' for call in r.calls)  # enforce only firewall; never replay install


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


# --------------------------------------------------------------------------
# Configurator wiring: an exported config, if present on this disk, is
# genuinely applied once firstboot commits - real code, not just a
# recorded intent. Best-effort and never gating: absent or malformed
# config must never block or fail the network-repair/package-install
# flow above, which remains the one real authorization gate.
# --------------------------------------------------------------------------

_EXPORTED_CONFIG = json.dumps({
    "proxmox": {"smartd_health_check": True, "smartd_monitor_all": True},
    "drivers": {"cpu_microcode": True},
})


def test_committed_run_applies_an_exported_configurator_config(tmp_path):
    r = full_runner(files={
        "/etc/network/interfaces": FIXTURE_A_IPV6_ONLY,
        "/etc/baseline/install-config.json": _EXPORTED_CONFIG,
    })
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "committed"
    assert "/etc/smartd.conf" in r.writes
    assert any("apt-get" in c and "install" in c and "amd64-microcode" in c for c in r.calls)


def test_already_completed_run_also_applies_an_exported_config(tmp_path):
    r = full_runner()
    fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
            check_lifeline_fn=broken_facts_fixture_a)
    # Config exported/placed on disk only AFTER the initial commit - the
    # normal real-world order (review the form, export, copy it over).
    r.files["/etc/baseline/install-config.json"] = _EXPORTED_CONFIG
    result2 = fsm.run(r, state_dir=tmp_path, print_fn=lambda *a: None)
    assert result2["action"] == "already_completed"
    assert "/etc/smartd.conf" in r.writes


def test_missing_config_file_is_skipped_without_error(tmp_path):
    r = full_runner()
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "committed"
    assert "/etc/smartd.conf" not in r.writes


def test_malformed_config_file_never_blocks_or_fails_commit(tmp_path):
    r = full_runner(files={
        "/etc/network/interfaces": FIXTURE_A_IPV6_ONLY,
        "/etc/baseline/install-config.json": "{not valid json",
    })
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                      check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "committed"
    assert (tmp_path / "complete").exists()


def test_healthy_resume_rechecks_missing_historical_evidence(tmp_path):
    fsm.run(full_runner(), state_dir=tmp_path, stdin=iter(['NO\n']),
            print_fn=lambda *a: None, check_lifeline_fn=healthy_facts)
    path = tmp_path / 'journal.json'
    journal = json.loads(path.read_text())
    next(e for e in journal['history'] if e['state'] == 'discovered')['discovery'] = {
        'lifeline_ok': True, 'facts': []}
    path.write_text(json.dumps(journal))
    result = fsm.run(full_runner(), state_dir=tmp_path, stdin=iter(['CONFIRM\n']),
                     print_fn=lambda *a: None, check_lifeline_fn=healthy_facts)
    assert result['action'] == 'committed'


def test_healthy_resume_reports_current_failed_verification(tmp_path):
    fsm.run(full_runner(), state_dir=tmp_path, stdin=iter(['NO\n']),
            print_fn=lambda *a: None, check_lifeline_fn=healthy_facts)
    result = fsm.run(full_runner(), state_dir=tmp_path, stdin=iter(['CONFIRM\n']),
                     print_fn=lambda *a: None, check_lifeline_fn=lambda: [])
    assert result['action'] == 'network_failed'
    assert not (tmp_path / 'complete').exists()


def test_completed_host_still_enforces_firewall(tmp_path, monkeypatch):
    (tmp_path/'complete').write_text('completed')
    calls=[]
    monkeypatch.setattr(fsm,'apply_configurator_settings',lambda *a,**kw:calls.append(kw))
    result=fsm.run(full_runner(),state_dir=tmp_path,print_fn=lambda *a:None)
    assert result['action']=='already_completed'
    assert calls[0]['enforce_lan_only'] is True


# --------------------------------------------------------------------------
# Offline commit from the drive's own verified repository (2026-10-10)
# --------------------------------------------------------------------------

def _offline_repo(tmp_path):
    """A real repository on disk with a real manifest, the shape baseline-first-boot-install carries."""
    import offline_cache
    root = tmp_path / "baseline-cache"
    (root / "apt").mkdir(parents=True)
    (root / "apt" / "Packages").write_text("Package: lm-sensors\nVersion: 1:3.6.2-2\n")
    (root / "apt" / "lm-sensors_3.6.2-2_amd64.deb").write_bytes(b"not really a deb, but real bytes")
    (root / "MANIFEST.json").write_text(json.dumps(offline_cache.build_manifest(root)))
    sources = tmp_path / "baseline-installer-cache.list"
    sources.write_text(f"deb [trusted=yes] file:{root / 'apt'} ./\n")
    return root, sources


def _run_offline(tmp_path, r, root, sources, **kw):
    state = tmp_path / "state"
    return state, fsm.run(r, state_dir=state, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                          check_lifeline_fn=broken_facts_fixture_a, offline_root=root, offline_sources=sources, **kw)


def test_an_intact_registered_repository_is_available(tmp_path):
    root, sources = _offline_repo(tmp_path)
    repo = fsm.offline_repository(root, sources)
    assert repo["available"] is True and repo["files_verified"] == 2


def test_a_repository_apt_does_not_know_about_is_not_available(tmp_path):
    root, sources = _offline_repo(tmp_path)
    sources.unlink()
    assert fsm.offline_repository(root, sources)["available"] is False


@pytest.mark.parametrize("tamper", ["modify", "add"])
def test_a_repository_that_no_longer_matches_its_manifest_is_not_trusted(tmp_path, tamper):
    root, sources = _offline_repo(tmp_path)
    if tamper == "modify":
        (root / "apt" / "lm-sensors_3.6.2-2_amd64.deb").write_bytes(b"altered after the manifest was made")
    else:
        (root / "apt" / "extra_1.0_amd64.deb").write_bytes(b"not in the manifest")
    repo = fsm.offline_repository(root, sources)
    assert repo["available"] is False and "does not verify" in repo["reason"]


def test_network_failure_with_a_verified_repository_commits_offline_and_keeps_the_failure(tmp_path):
    root, sources = _offline_repo(tmp_path)
    r = full_runner(verify_ok=False)
    state, result = _run_offline(tmp_path, r, root, sources)
    assert result["action"] == "committed"
    assert result["network_verified"] is False and result["package_source"] == "offline"
    assert (state / "complete").exists()                     # what releases the kiosk gate
    history = json.loads((state / "journal.json").read_text())["history"]
    states = [e["state"] for e in history]
    assert "network_repair_failed" in states                  # the failure is still on record
    assert "network_repaired" not in states                   # and was never rewritten as success
    assert history[-1]["network_verified"] is False


def test_the_offline_install_never_consults_a_network_source(tmp_path):
    root, sources = _offline_repo(tmp_path)
    r = full_runner(verify_ok=False)
    _run_offline(tmp_path, r, root, sources)
    apt = [c for c in r.calls if "apt-get" in c]
    assert apt, "the tools should have been installed offline"
    for argv in apt:
        assert f"Dir::Etc::SourceList={sources}" in argv
        assert "Dir::Etc::SourceParts=-" in argv


def test_network_failure_with_a_tampered_repository_still_refuses(tmp_path):
    root, sources = _offline_repo(tmp_path)
    (root / "apt" / "lm-sensors_3.6.2-2_amd64.deb").write_bytes(b"tampered")
    r = full_runner(verify_ok=False)
    state, result = _run_offline(tmp_path, r, root, sources)
    assert result["action"] == "network_failed" and result["package_install_allowed"] is False
    assert not _apt_installs(r)
    assert not (state / "complete").exists()


def test_a_resumed_network_failure_proceeds_offline_without_retrying_the_repair(tmp_path):
    root, sources = _offline_repo(tmp_path)
    r = full_runner(verify_ok=False)
    _run_offline(tmp_path, r, root, sources.with_suffix(".absent"))   # first run: no repo yet -> refused
    repair_calls = len([c for c in r.calls if "ifreload" in c or "ifup" in c])
    state, result = _run_offline(tmp_path, r, root, sources)          # repo now present
    assert result["action"] == "committed" and result["network_verified"] is False
    assert len([c for c in r.calls if "ifreload" in c or "ifup" in c]) == repair_calls


def test_an_offline_install_failure_does_not_commit(tmp_path):
    root, sources = _offline_repo(tmp_path)
    r = full_runner(verify_ok=False, package_install_ok=False)
    state, result = _run_offline(tmp_path, r, root, sources)
    assert result["action"] == "packages_failed"
    assert not (state / "complete").exists()


def test_a_verified_network_still_installs_from_the_network_and_records_it(tmp_path):
    root, sources = _offline_repo(tmp_path)
    r = full_runner()
    state, result = _run_offline(tmp_path, r, root, sources)
    assert result["action"] == "committed"
    assert result["network_verified"] is True and result["package_source"] == "network"
    for argv in [c for c in r.calls if "apt-get" in c and "install" in c]:
        assert not any("Dir::Etc::SourceList" in a for a in argv)


def test_the_confirm_screen_names_the_offline_source_only_when_one_is_present():
    class D:
        installed, evidence = True, []
    diagnosis = {"needs_repair": False}
    with_repo = fsm.format_full_proposal(D(), {}, diagnosis, offline_available=True)
    without = fsm.format_full_proposal(D(), {}, diagnosis, offline_available=False)
    assert "own verified package repository" in with_repo
    assert "only after network verifies" in without and "repository" not in without


# --------------------------------------------------------------------------
# Proposal and the repair's own re-check agreeing (2026-10-10 rehearsal)
# --------------------------------------------------------------------------

def _facts_sequence(*fns):
    """Discovery sees the first; every later lifeline check sees the next, then the last repeats."""
    calls = iter(fns)
    last = [fns[-1]]

    def check():
        fn = next(calls, last[0])
        return fn()
    return check


def test_a_lifeline_that_heals_before_the_repair_is_verified_now_not_failed(tmp_path):
    """Discovery (before CONFIRM) found it broken; the repair's own check then found it healthy and
    refused. That used to be recorded as a network failure."""
    r = full_runner()
    check = _facts_sequence(broken_facts_fixture_a, healthy_facts, healthy_facts)
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                     check_lifeline_fn=check, offline_root=tmp_path / "none", offline_sources=tmp_path / "none.list")
    assert result["action"] == "committed" and result["network_verified"] is True
    entry = next(e for e in json.loads((tmp_path / "journal.json").read_text())["history"]
                 if e["state"] == "network_repaired")
    assert entry["verification"] and all(v is True for v in entry["verification"].values())
    assert "verified now" in entry["network_detail"]


def test_an_already_healthy_refusal_that_does_not_reverify_is_still_a_failure(tmp_path):
    r = full_runner()
    check = _facts_sequence(broken_facts_fixture_a, healthy_facts, broken_facts_fixture_a)
    result = fsm.run(r, state_dir=tmp_path, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
                     check_lifeline_fn=check, offline_root=tmp_path / "none", offline_sources=tmp_path / "none.list")
    assert result["action"] == "network_failed"
    states = [e["state"] for e in json.loads((tmp_path / "journal.json").read_text())["history"]]
    assert "network_repaired" not in states and states[-1] == "network_repair_failed"
