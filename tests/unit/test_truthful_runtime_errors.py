"""Failure injection: production reads/requests must not manufacture evidence."""
import pytest

from fake_runner import FakeRunner, FakeProc
import config_apply as ca
import config_diff as cd
import control_panel_web as panel
import proxmox_vm_metrics as metrics
import physical_device_safety as safety
from test_physical_device_safety import FakeRunner as DiskRunner


@pytest.mark.parametrize("result", [FakeProc(127, "", "missing"), FakeProc(0, "{}", ""), FakeProc(0, "invalid", "")])
def test_vm_inventory_failure_cannot_claim_no_vms(result):
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "pvesh", result)])
    with pytest.raises(metrics.MetricsError):
        metrics.list_vms(runner)


def test_rrd_failure_cannot_claim_empty_history():
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "pvesh", FakeProc(1, "", "denied"))])
    with pytest.raises(metrics.MetricsError):
        metrics.vm_rrd_history(runner, "localhost", 100)


def test_unknown_vm_measurements_are_not_zero():
    runner = FakeRunner(command_responses=[
        (lambda a: a[2].endswith("/qemu"), FakeProc(0, '[{"vmid":100,"status":"running"}]', "")),
        (lambda a: a[2].endswith("/lxc"), FakeProc(0, "[]", "")),
    ])
    vm = metrics.list_vms(runner)[0]
    assert vm.cpu is None and vm.mem is None


def test_failed_ethtool_read_cannot_claim_features_disabled():
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "ethtool", FakeProc(1, "", "denied"))])
    with pytest.raises(cd.ReadbackError):
        cd.read_current_ethtool_config(runner, "eth0")


def test_partial_ethtool_output_cannot_claim_missing_features_disabled():
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "ethtool", FakeProc(0, "", ""))])
    with pytest.raises(cd.ReadbackError):
        cd.read_current_ethtool_config(runner, "eth0")


def test_diff_http_reports_unavailable_instead_of_success():
    runner = FakeRunner(files={"/config.json": '{"proxmox":{"ethtool_gro":false}}'},
                        command_responses=[(lambda a: a[0] == "ethtool", FakeProc(1, "", "denied"))])
    result = panel.handle_differences(runner, config_path="/config.json")
    assert result.status == 503 and result.outcome == "refused"
    assert "REAL-002" in result.body["reason"]


def test_iperf_service_submission_cannot_claim_listening():
    runner = FakeRunner()
    result = ca.apply_iperf3_config(runner, {"role":"server", "port":5201})
    assert result.ok is False
    assert "REAL-003" in result.detail


def test_selected_restore_categories_require_config_member_and_never_extract_archive_paths():
    runner = FakeRunner(files={"/mnt/INSTALLER_CACHE/backups/restore.tar.gz": ""},
        command_responses=[(lambda a: a[:2] == ["tar", "-tzf"], FakeProc(0, "mnt/USER_ADMIN/data\n", ""))])
    result = ca.apply_handoff_config(runner, {"restored_categories":["network"],
        "archive_path":"/mnt/INSTALLER_CACHE/backups/restore.tar.gz"})
    assert result.ok is False and "install-config.json" in result.detail
    assert len(runner.calls) == 1 and runner.calls[0][0:2] == ["tar", "-tzf"]


def test_boot_ancestry_with_one_missing_serial_remains_unknown():
    runner = DiskRunner(findmnt_root="/dev/mapper/root", pkname_graph={"/dev/mapper/root":["sda","sdb"]},
                        udevadm_by_path={"/dev/sda":"Boot-A"})
    assert safety.get_boot_device_serial(runner) is None


def test_cyclic_boot_branch_cannot_be_ignored_beside_identified_disk():
    runner = DiskRunner(findmnt_root="/dev/mapper/root",
        pkname_graph={"/dev/mapper/root":["sda","dm-0"],"/dev/dm-0":["dm-0"]},
        udevadm_by_path={"/dev/sda":"Boot-A"})
    assert safety.get_boot_device_serial(runner) is None


def test_hardware_probe_failure_is_visible_on_the_page():
    import hardware_inventory as hi
    import baseline_web
    runner = FakeRunner(command_responses=[(lambda a: True, FakeProc(127, "", "missing"))])
    inventory = hi.collect_all(runner)
    assert len(inventory["errors"]) == 4
    assert "REAL-006" in baseline_web._render_inventory(inventory)


def test_package_probe_failure_is_not_package_absence():
    runner = FakeRunner(command_responses=[(lambda a: True, FakeProc(127, "", "missing"))])
    with pytest.raises(cd.ReadbackError, match="REAL-002"):
        cd.read_current_package_installed(runner, "amd64-microcode")


def test_gateway_is_not_invented_from_first_subnet_address(monkeypatch):
    import netpref
    def run(argv, **kwargs):
        return FakeProc(0, "" if "route" in argv else "2: eth0 inet 10.0.0.20/24", "")
    monkeypatch.setattr(netpref.subprocess, "run", run)
    assert netpref._device_gateway("eth0") is None


def test_failed_route_demotion_cannot_report_preserved_fallback(monkeypatch):
    import netpref
    monkeypatch.setattr(netpref, "_device_gateway", lambda dev:"10.0.0.1")
    def run(argv, **kwargs):
        if "show" in argv:
            return FakeProc(0, "default via 192.168.1.1 dev eth1", "")
        return FakeProc(1, "", "denied") if "del" in argv else FakeProc(0, "", "")
    monkeypatch.setattr(netpref.subprocess, "run", run)
    ok, detail = netpref.apply_primary("eth0")
    assert not ok and "REAL-007" in detail


def test_settings_error_reports_missing_handoff_archive(tmp_path):
    import settings_web as settings
    store = settings.LocalAppStore(tmp_path / "store.db")
    result = settings.SystemSectionApplier(store, FakeRunner()).apply(
        "handoff", {"restored_categories":["network"]})
    assert not result.applied and "handoff archive" in result.detail


def test_firstboot_does_not_claim_it_inspected_unimplemented_intent_staging():
    import firstboot_statemachine as firstboot
    status = firstboot.format_setup_intent_status()
    assert "REAL-012" in status and "unknown" in status.lower()
    assert "none staged" not in status.lower()


def test_selective_update_reports_readback_error_and_never_writes_unknown_network_state():
    import update_pipeline
    runner = FakeRunner(command_responses=[(lambda a: a[0] == "ethtool", FakeProc(1, "", "denied"))])
    result = update_pipeline.apply_selective_update(runner,
        {"proxmox":{"ethtool_gro":True}}, {"configs":["ethtool_gro"]}, network_interface="eth0")
    assert "ethtool" in result["failed"] and "REAL-002" in result["errors"]["ethtool"]
    assert not any(c[:2] == ["ethtool", "-s"] for c in runner.calls)


@pytest.mark.parametrize("entry", [{}, {"vmid":0}, {"vmid":True}, {"vmid":100,"cpu":"unknown"},
                                   {"vmid":100,"mem":-1}, {"vmid":100,"cpu":float("nan")}])
def test_malformed_vm_facts_cannot_create_invented_ids_or_measurements(entry):
    import json
    runner = FakeRunner(command_responses=[(lambda a:a[0]=="pvesh", FakeProc(0,json.dumps([entry]),""))])
    with pytest.raises(metrics.MetricsError, match="REAL-001"):
        metrics.list_vms(runner)


@pytest.mark.parametrize("content", ["/dev/sda -a\n", "DEVICESCAN -H -unknown\n", "DEVICESCAN -o\n",
                                     "DEVICESCAN -H\n/dev/sdb -a\n", "DEVICESCAN -H\nDEVICESCAN -a\n"])
def test_unrecognized_smartd_config_cannot_be_read_as_disabled_defaults(content):
    runner = FakeRunner(files={cd.SMARTD_CONF_PATH:content})
    with pytest.raises(cd.ReadbackError, match="REAL-002"):
        cd.read_current_smartd_config(runner)


def test_partial_smartd_update_cannot_erase_unrecognized_existing_config():
    import update_pipeline
    runner = FakeRunner(files={cd.SMARTD_CONF_PATH:"/dev/sda -a\n"})
    result = update_pipeline.apply_selective_update(runner, {"proxmox":{"smartd_health_check":True}},
        {"configs":["smartd_health_check"]}, network_interface="eth0")
    assert "smartd" in result["failed"] and "REAL-002" in result["errors"]["smartd"]
    assert runner.files[cd.SMARTD_CONF_PATH] == "/dev/sda -a\n" and not runner.writes
