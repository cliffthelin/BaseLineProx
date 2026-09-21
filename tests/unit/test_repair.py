import json

import repair
import repair_rollback
from conftest import make_ready_runner, healthy_facts, broken_facts, VMBR0_BRIDGE


def test_full_pipeline_success():
    runner = make_ready_runner()
    result = repair.reset_interface_to_dhcp(runner, observed_dev="vmbr0", requested_by="test",
                                             proposed_target="vmbr0", operator_present=True,
                                             check_lifeline_fn=broken_facts)
    assert result.ok
    assert result.outcome == "success"
    # The rewrite landed, backup exists and byte-verifies, rollback was
    # armed then cancelled only after verification succeeded.
    assert "iface vmbr0 inet dhcp" in runner.files["/etc/network/interfaces"]
    assert any(c[:1] == ["systemd-run"] for c in runner.calls)
    assert any(c[:2] == ["systemctl", "stop"] for c in runner.calls)
    # No fallback to ifdown/ifup, ever.
    assert not any(c and c[0] in ("ifdown", "ifup") for c in runner.calls)


def test_refuses_when_target_already_healthy():
    runner = make_ready_runner()
    result = repair.reset_interface_to_dhcp(runner, observed_dev="vmbr0", requested_by="test",
                                             operator_present=True, check_lifeline_fn=healthy_facts)
    assert not result.ok
    assert result.outcome == "refused"
    assert "already_healthy" in result.detail
    assert "/etc/network/interfaces" not in runner.writes


def test_refuses_on_cluster_membership():
    runner = make_ready_runner(clustered=True)
    result = repair.reset_interface_to_dhcp(runner, observed_dev="vmbr0", requested_by="test",
                                             operator_present=True, check_lifeline_fn=broken_facts)
    assert not result.ok
    assert "cluster_member" in result.detail
    assert not runner.writes


def test_refuses_ifupdown2_missing_no_fallback():
    runner = make_ready_runner()
    # which ifreload fails outright - no ifupdown2 on this host.
    runner.command_responses.insert(0, (lambda a: a[:2] == ["which", "ifreload"],
                                         __import__("fake_runner").FakeProc(1, "", "")))
    result = repair.reset_interface_to_dhcp(runner, observed_dev="vmbr0", requested_by="test",
                                             operator_present=True, check_lifeline_fn=broken_facts)
    assert not result.ok
    assert "unsupported_environment" in result.detail
    assert not any(c and c[0] in ("ifdown", "ifup") for c in runner.calls)
    assert not runner.writes


def test_ambiguous_topology_refuses_via_pipeline():
    ambiguous = """auto lo
iface lo inet loopback

iface eth0 inet manual

auto vmbr0
iface vmbr0 inet static
    address 10.0.2.15/24
    gateway 10.0.2.2
    bridge-ports eth0

auto vmbr1
iface vmbr1 inet static
    address 10.0.3.15/24
    gateway 10.0.3.2
    bridge-ports eth0
"""
    runner = make_ready_runner(files={"/etc/network/interfaces": ambiguous})
    result = repair.reset_interface_to_dhcp(runner, observed_dev="eth0", requested_by="test",
                                             operator_present=True, check_lifeline_fn=broken_facts)
    assert not result.ok
    assert "topology_ambiguous" in result.detail
    assert not runner.writes


def test_connection_guard_blocks_unattended_with_protected_session():
    runner = make_ready_runner(protected_session=True)
    result = repair.reset_interface_to_dhcp(runner, observed_dev="vmbr0", requested_by="test",
                                             operator_present=False, check_lifeline_fn=broken_facts)
    assert not result.ok
    assert "protected_connection_unattended" in result.detail
    assert not runner.writes


def test_connection_guard_allows_with_operator_present_and_logs_disclosure():
    runner = make_ready_runner(protected_session=True)
    result = repair.reset_interface_to_dhcp(runner, observed_dev="vmbr0", requested_by="test",
                                             operator_present=True, check_lifeline_fn=broken_facts)
    assert result.ok
    log = runner.files[str(repair.EVENT_LOG)]
    assert "protected_sessions_disclosed" in log


def test_unrelated_connection_does_not_block():
    files = {"/etc/network/interfaces": VMBR0_BRIDGE}
    runner = make_ready_runner(files=files)
    runner.script(lambda a: a[:1] == ["ss"],
                  __import__("fake_runner").FakeProc(
                      0, "State  Recv-Q Send-Q Local Address:Port  Peer Address:Port\n"
                         "ESTAB  0      0      10.0.2.15:51234    10.0.2.1:80\n", ""))
    result = repair.reset_interface_to_dhcp(runner, observed_dev="vmbr0", requested_by="test",
                                             operator_present=False, check_lifeline_fn=broken_facts)
    assert result.ok  # port 51234 isn't protected - no reason to require attendance


def test_concurrent_config_change_between_backup_and_write_refuses():
    runner = make_ready_runner()
    real_read = runner.read_text
    call_count = {"n": 0}
    target_path = "/etc/network/interfaces"

    def flaky_read(path):
        text = real_read(path)
        # Simulate someone editing the live file between the backup read
        # (read #2 of the target path: #1 is plan_repair's own read) and
        # the immediately-before-write revalidation (read #3).
        if path == target_path:
            call_count["n"] += 1
            if call_count["n"] == 3:
                return text + "\n# edited by someone else\n"
        return text

    runner.read_text = flaky_read
    result = repair.reset_interface_to_dhcp(runner, observed_dev="vmbr0", requested_by="test",
                                             operator_present=True, check_lifeline_fn=broken_facts)
    assert not result.ok
    assert "concurrent_config_change" in result.detail
    assert "iface vmbr0 inet dhcp" not in runner.files["/etc/network/interfaces"]


def test_target_bound_verification_not_fooled_by_global_masking():
    """Even if the (fake, caller-supplied) global lifeline says nothing
    useful either way, verify_target is scoped to the target device's own
    address/route/gateway - a live tether or second NIC elsewhere can't
    make this pass. Here the device-bound probes themselves report a
    still-broken target after apply, and the result must be a rollback,
    not a false success."""
    runner = make_ready_runner(verify_ok=False)
    result = repair.reset_interface_to_dhcp(runner, observed_dev="vmbr0", requested_by="test",
                                             operator_present=True, check_lifeline_fn=broken_facts)
    assert not result.ok
    assert result.outcome == "rolled_back"
    # Rollback must be left ARMED, not raced with an inline restore/cancel.
    assert not any(c[:2] == ["systemctl", "stop"] for c in runner.calls)
    assert "iface vmbr0 inet dhcp" in runner.files["/etc/network/interfaces"]  # write did happen


def test_independent_rollback_survives_process_restart_after_apply():
    """Simulates Baseline being killed right after 'applied': the original
    reset_interface_to_dhcp() call never gets to run its own rollback
    logic (verification fails, so it returns leaving the timer armed) -
    then a *fresh*, unrelated call into repair_rollback (standing in for
    the independently-armed systemd timer firing later, in a process that
    never touched the original Python call) restores correctly from
    persisted state alone."""
    runner = make_ready_runner(verify_ok=False)
    result = repair.reset_interface_to_dhcp(runner, observed_dev="vmbr0", requested_by="test",
                                             operator_present=True, check_lifeline_fn=broken_facts)
    assert result.outcome == "rolled_back"
    assert "iface vmbr0 inet dhcp" in runner.files["/etc/network/interfaces"]

    # Now flip the runner's ifreload back to success for the restore path,
    # and hand it to repair_rollback with NOTHING but the attempt id -
    # the same information a systemd ExecStart would have.
    runner.command_responses.insert(0, (lambda a: a == ["ifreload", "-a"],
                                         __import__("fake_runner").FakeProc(0, "", "")))
    rc = repair_rollback.same_boot_rollback(result.attempt_id, runner=runner)
    assert rc == 0
    assert "iface vmbr0 inet static" in runner.files["/etc/network/interfaces"]
    assert "iface vmbr0 inet dhcp" not in runner.files["/etc/network/interfaces"]
    assert not repair.read_pending_manifest(runner)


def test_rollback_restores_broken_but_known_state_even_if_still_unreachable():
    """The original static config may itself have been unreachable (why a
    repair was proposed at all) - rollback success is judged on the bytes
    being restored and the reload completing, never on the gateway
    actually answering afterward."""
    runner = make_ready_runner(verify_ok=False)
    result = repair.reset_interface_to_dhcp(runner, observed_dev="vmbr0", requested_by="test",
                                             operator_present=True, check_lifeline_fn=broken_facts)
    assert result.outcome == "rolled_back"

    # ifreload -a succeeds (config applies cleanly) but the device-bound
    # probes still fail afterward too - the ORIGINAL config was already
    # broken, which is exactly why this repair was proposed in the first
    # place.
    runner.command_responses.insert(0, (lambda a: a == ["ifreload", "-a"],
                                         __import__("fake_runner").FakeProc(0, "", "")))
    rc = repair_rollback.same_boot_rollback(result.attempt_id, runner=runner)
    assert rc == 0

    log_lines = [json.loads(l) for l in runner.files[str(repair.EVENT_LOG)].splitlines()]
    confirmed = [r for r in log_lines if r["step"] == "rollback_confirmed"][0]
    assert confirmed["config_restoration_confirmed"] is True
    assert confirmed["connectivity_restored"] is False


def test_backup_retention_keeps_at_least_10_or_30_days():
    runner = make_ready_runner()
    now = runner.now()
    # 15 closed attempts: 5 recent (within 30 days), 10 older-but-within-
    # the-10-attempt floor, plus extras older than both thresholds.
    ages_days = [1, 2, 3, 4, 5, 40, 45, 50, 55, 60, 65, 70, 75, 80, 400]
    for i, age in enumerate(ages_days):
        attempt_id = f"attempt-{i}"
        adir = repair._attempt_dir(attempt_id)
        runner.write_text_atomic(str(adir / "backup_manifest.json"), json.dumps({"files": {}, "closure_hash": "x"}))
        runner.write_text_atomic(str(adir / "attempt_status.json"),
                                  json.dumps({"outcome": "success", "closed_at": now - age * 86400}))
    repair.prune_old_backups(runner)
    remaining = {p.split("/")[-1] for p in runner.dirs if p.startswith(str(repair.REPAIR_STATE_DIR) + "/attempt-")}
    # The 10 most recent must all survive (retention floor), regardless of age.
    for i in range(10):
        assert f"attempt-{i}" in remaining
    # The very oldest (400 days, 11th-from-newest) must be pruned.
    assert "attempt-14" not in remaining


def test_never_prunes_an_unclosed_incomplete_attempt():
    runner = make_ready_runner()
    adir = repair._attempt_dir("incomplete-1")
    runner.write_text_atomic(str(adir / "backup_manifest.json"), json.dumps({"files": {}, "closure_hash": "x"}))
    # No attempt_status.json written - this attempt never closed.
    repair.prune_old_backups(runner)
    assert runner.path_exists(str(adir / "backup_manifest.json"))


def test_boot_time_recovery_noop_when_nothing_pending():
    runner = make_ready_runner()
    rc = repair_rollback.boot_time_recovery(runner=runner)
    assert rc == 0
    assert not runner.appends  # nothing logged - the common case on every normal boot


def test_boot_time_recovery_restores_when_manifest_pending():
    """Stands in for the permanent dormant recovery service's own logic
    (not yet wired to an installed systemd unit - see repair_rollback.py's
    module docstring): given only a pending manifest and a backup on disk,
    with no reference to the original Python call that armed it, recovery
    restores the original config."""
    runner = make_ready_runner(verify_ok=False)
    result = repair.reset_interface_to_dhcp(runner, observed_dev="vmbr0", requested_by="test",
                                             operator_present=True, check_lifeline_fn=broken_facts)
    assert result.outcome == "rolled_back"
    assert repair.read_pending_manifest(runner) is not None  # still pending - rollback hasn't fired yet

    runner.command_responses.insert(0, (lambda a: a == ["ifreload", "-a"],
                                         __import__("fake_runner").FakeProc(0, "", "")))
    rc = repair_rollback.boot_time_recovery(runner=runner)
    assert rc == 0
    assert "iface vmbr0 inet static" in runner.files["/etc/network/interfaces"]
    assert repair.read_pending_manifest(runner) is None
    log_lines = [json.loads(l) for l in runner.files[str(repair.EVENT_LOG)].splitlines()]
    assert any(r["step"] == "boot_recovery_triggered" for r in log_lines)
