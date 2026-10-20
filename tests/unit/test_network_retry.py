"""Unattended retry of exactly the network change the person confirmed at first boot.

The journal, completion marker and retry record are real files in a real directory. The system probes (discovery,
diagnosis, link state, the repair itself) are plain functions of the shapes the production modules return."""
import json
from types import SimpleNamespace

import pytest

import firstboot_statemachine as fsm
import network_retry as nr

DIFF = {"action": "add", "file": "/etc/network/interfaces", "before": ["iface vmbr0 inet6 static"],
        "after": ["iface vmbr0 inet6 static", "iface vmbr0 inet dhcp"]}
PROPOSAL = {"needs_repair": True, "mode": "additive", "target": "vmbr0", "diff": DIFF, "reason": ""}


def _journal(tmp_path, *, confirmed=True, repaired=False, committed=True, proposal=PROPOSAL):
    states = ["created", "detected", "discovered", "proposed"] + (["confirmed"] if confirmed else [])
    history = [{"state": s} for s in states]
    history[3]["diagnosis"] = proposal
    if repaired:
        history.append({"state": "network_repaired"})
    else:
        history.append({"state": "network_repair_failed"})
    journal = {"state": "committed" if committed else "packages_installed", "history": history}
    (tmp_path / "journal.json").write_text(json.dumps(journal))
    if committed:
        fsm.mark_complete(tmp_path)
    return journal


def _env(**overrides):
    calls = []
    env = dict(
        discover_fn=lambda: {"facts": [], "lifeline_ok": False},
        diagnose_fn=lambda discovery: PROPOSAL,
        link_up_fn=lambda: True,
        repair_fn=lambda mode, target: calls.append((mode, target)) or SimpleNamespace(
            ok=True, detail="vmbr0 gained a dhcp stanza", refusal_code=None,
            verification={"address": True, "gateway": True, "dns": True, "https": True}),
    )
    env.update(overrides)
    return env, calls


def test_only_a_confirmed_and_failed_change_is_ever_authorized_for_retry():
    j = {"history": [{"state": "proposed", "diagnosis": PROPOSAL}, {"state": "confirmed"},
                     {"state": "network_repair_failed"}]}
    assert nr.authorized_change(j) == {"mode": "additive", "target": "vmbr0", "diff": DIFF}
    unconfirmed = {"history": [{"state": "proposed", "diagnosis": PROPOSAL}]}
    assert nr.authorized_change(unconfirmed) is None
    repaired = {"history": j["history"] + [{"state": "network_repaired"}]}
    assert nr.authorized_change(repaired) is None
    no_mode = {"history": [{"state": "proposed", "diagnosis": dict(PROPOSAL, mode=None)}, {"state": "confirmed"}]}
    assert nr.authorized_change(no_mode) is None


def test_a_different_proposal_is_not_the_change_that_was_confirmed():
    authorized = {"mode": "additive", "target": "vmbr0", "diff": DIFF}
    assert nr.same_change(authorized, PROPOSAL)
    assert not nr.same_change(authorized, dict(PROPOSAL, target="vmbr1"))
    assert not nr.same_change(authorized, dict(PROPOSAL, mode="replace"))
    assert not nr.same_change(authorized, dict(PROPOSAL, diff=dict(DIFF, after=["iface vmbr0 inet static"])))
    assert not nr.same_change(authorized, dict(PROPOSAL, needs_repair=False))


def test_nothing_runs_before_first_boot_has_committed(tmp_path):
    _journal(tmp_path, committed=False)
    env, calls = _env()
    assert nr.attempt(tmp_path, **env)["action"] == "awaiting_first_boot" and not calls


def test_the_confirmed_change_is_reapplied_and_the_success_is_recorded_with_its_evidence(tmp_path):
    _journal(tmp_path)
    env, calls = _env()
    result = nr.attempt(tmp_path, **env)
    assert result["action"] == "applied_ok" and calls == [("additive", "vmbr0")]
    record = json.loads((tmp_path / nr.RETRY_FILE).read_text())
    assert record["verified"]["verification"] == {"address": True, "gateway": True, "dns": True, "https": True}
    assert nr.attempt(tmp_path, **env)["action"] == "already_verified" and len(calls) == 1   # never again


def test_a_connection_that_came_up_by_itself_is_recorded_and_nothing_is_changed(tmp_path):
    _journal(tmp_path)
    env, calls = _env(discover_fn=lambda: {"facts": [], "lifeline_ok": True})
    assert nr.attempt(tmp_path, **env)["action"] == "verified_without_change" and not calls


def test_no_link_means_wait_without_touching_the_network(tmp_path):
    _journal(tmp_path)
    env, calls = _env(link_up_fn=lambda: False)
    result = nr.attempt(tmp_path, **env)
    assert result["action"] == "waiting_for_link" and not calls
    assert json.loads((tmp_path / nr.RETRY_FILE).read_text())["verified"] is None


def test_a_changed_situation_is_never_repaired_without_a_new_confirmation(tmp_path):
    _journal(tmp_path)
    env, calls = _env(diagnose_fn=lambda d: dict(PROPOSAL, target="vmbr1"))
    result = nr.attempt(tmp_path, **env)
    assert result["action"] == "proposal_changed" and not calls


def test_a_failed_attempt_is_recorded_and_retried_later_not_given_up(tmp_path):
    _journal(tmp_path)
    failing = lambda mode, target: SimpleNamespace(ok=False, detail="rolled back", refusal_code=None, verification={})
    env, _ = _env(repair_fn=failing)
    assert nr.attempt(tmp_path, **env)["action"] == "applied_failed"
    record = json.loads((tmp_path / nr.RETRY_FILE).read_text())
    assert record["verified"] is None and record["attempts"][-1]["action"] == "applied_failed"
    env2, calls = _env()
    assert nr.attempt(tmp_path, **env2)["action"] == "applied_ok" and calls


def test_only_the_most_recent_attempts_are_kept(tmp_path):
    _journal(tmp_path)
    env, _ = _env(link_up_fn=lambda: False)
    for _ in range(nr.ATTEMPTS_KEPT + 20):
        nr.attempt(tmp_path, **env)
    record = json.loads((tmp_path / nr.RETRY_FILE).read_text())
    assert len(record["attempts"]) == nr.ATTEMPTS_KEPT and record["attempt_count"] == nr.ATTEMPTS_KEPT + 20


def test_a_network_that_first_boot_verified_needs_no_retry(tmp_path):
    _journal(tmp_path, repaired=True)
    env, calls = _env()
    assert nr.attempt(tmp_path, **env)["action"] == "nothing_to_retry" and not calls


def test_the_timer_stops_only_when_nothing_is_left_to_retry():
    for action in ("already_verified", "verified_without_change", "applied_ok", "nothing_to_retry"):
        assert action in nr.FINISHED
    for action in ("awaiting_first_boot", "waiting_for_link", "proposal_changed", "applied_failed"):
        assert action not in nr.FINISHED


def test_the_installed_units_and_provisioning_match(tmp_path):
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    provision = (repo / "boot/provision.sh").read_text()
    for name in ("baseline-network-retry.service", "baseline-network-retry.timer", "baseline/bin/baseline-network-retry",
                 "baseline/lib/network_retry.py", "systemctl enable baseline-network-retry.timer"):
        assert name in provision, name
    unit = (repo / "boot/baseline-network-retry.service").read_text()
    assert "ExecStart=/opt/baseline/bin/baseline-network-retry" in unit and "ReadOnlyPaths=/opt/baseline" in unit
    assert (repo / "baseline/bin/baseline-network-retry").stat().st_mode & 0o111


def test_a_bridge_port_renamed_by_the_new_machine_step_is_still_the_confirmed_change_but_nothing_else_may_differ():
    import network_retry as nr
    base = "iface vmbr0 inet6 static\n        address fec0::1/64\n        bridge-ports {nic}\n        bridge-fd 0\niface vmbr0 inet dhcp\n"
    authorized = {"mode": "additive", "target": "vmbr0", "diff": {"after": base.format(nic="ens3")}}
    same = {"needs_repair": True, "mode": "additive", "target": "vmbr0", "diff": {"after": base.format(nic="enp0s3")}}
    assert nr.same_change(authorized, same)
    other_address = dict(same, diff={"after": base.format(nic="enp0s3").replace("fec0::1", "fec0::2")})
    other_stanza = dict(same, diff={"after": base.format(nic="enp0s3").replace("inet dhcp", "inet static")})
    other_target = dict(same, target="vmbr1")
    for changed in (other_address, other_stanza, other_target):
        assert not nr.same_change(authorized, changed)


def test_the_proposal_as_a_list_of_lines_gets_the_same_bridge_port_treatment():
    import network_retry as nr
    lines = ["iface vmbr0 inet6 static", "        address fec0::1/64", "        bridge-ports {nic}", "iface vmbr0 inet dhcp"]
    authorized = {"mode": "additive", "target": "vmbr0", "diff": {"after": [l.format(nic="ens3") for l in lines]}}
    renamed = {"needs_repair": True, "mode": "additive", "target": "vmbr0", "diff": {"after": [l.format(nic="enp0s3") for l in lines]}}
    different = {"needs_repair": True, "mode": "additive", "target": "vmbr0",
                 "diff": {"after": [l.format(nic="enp0s3").replace("inet dhcp", "inet static") for l in lines]}}
    assert nr.same_change(authorized, renamed) and not nr.same_change(authorized, different)


def test_an_unreadable_carrier_file_is_not_a_link(tmp_path):
    """Reading `carrier` of an administratively-down interface raises EINVAL; the retry service used to die with a traceback on it."""
    import network_retry as nr
    up, down = tmp_path / "up", tmp_path / "down"
    up.write_text("1\n")
    down.mkdir()                      # reading a directory raises OSError, as EINVAL does
    assert nr.carrier_up(up) is True
    assert nr.carrier_up(down) is False
    assert nr.carrier_up(tmp_path / "absent") is False
