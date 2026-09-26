"""Unit tests for proxmox_vm_metrics.py (Track A5) - live per-VM resource
stats via Proxmox's own pvesh CLI. Must behave cleanly with zero VMs
(the common case before Track A4 creates any), matching diagnostics.py's
established "absence is normal, not an error" discipline."""
import json

from fake_runner import FakeRunner, FakeProc

import proxmox_vm_metrics as pvm


# --------------------------------------------------------------------------
# list_vms
# --------------------------------------------------------------------------

def test_list_vms_empty_when_no_guests_exist():
    runner = FakeRunner()
    runner.command_responses = [
        (lambda a: a[:3] == ["pvesh", "get", "/nodes/localhost/qemu"], FakeProc(0, "[]", "")),
        (lambda a: a[:3] == ["pvesh", "get", "/nodes/localhost/lxc"], FakeProc(0, "[]", "")),
    ]
    result = pvm.list_vms(runner)
    assert result == []


def test_list_vms_empty_when_pvesh_missing():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:1] == ["pvesh"], FakeProc(127, "", "command not found"))]
    result = pvm.list_vms(runner)
    assert result == []


def test_list_vms_parses_real_qemu_entries():
    qemu_payload = json.dumps([
        {"vmid": 100, "name": "ubuntu-test", "status": "running", "cpu": 0.0234,
         "mem": 536870912, "maxmem": 2147483648, "disk": 0, "maxdisk": 34359738368,
         "netin": 12345, "netout": 6789, "uptime": 3600},
    ])
    runner = FakeRunner()
    runner.command_responses = [
        (lambda a: a[:3] == ["pvesh", "get", "/nodes/localhost/qemu"], FakeProc(0, qemu_payload, "")),
        (lambda a: a[:3] == ["pvesh", "get", "/nodes/localhost/lxc"], FakeProc(0, "[]", "")),
    ]
    result = pvm.list_vms(runner)
    assert len(result) == 1
    vm = result[0]
    assert vm.vmid == 100
    assert vm.name == "ubuntu-test"
    assert vm.type == "qemu"
    assert vm.status == "running"
    assert vm.cpu == 0.0234
    assert vm.mem == 536870912
    assert vm.uptime == 3600


def test_list_vms_includes_both_qemu_and_lxc():
    qemu_payload = json.dumps([{"vmid": 100, "name": "vm1", "status": "running"}])
    lxc_payload = json.dumps([{"vmid": 200, "name": "ct1", "status": "stopped"}])
    runner = FakeRunner()
    runner.command_responses = [
        (lambda a: a[:3] == ["pvesh", "get", "/nodes/localhost/qemu"], FakeProc(0, qemu_payload, "")),
        (lambda a: a[:3] == ["pvesh", "get", "/nodes/localhost/lxc"], FakeProc(0, lxc_payload, "")),
    ]
    result = pvm.list_vms(runner)
    types = {(v.vmid, v.type) for v in result}
    assert types == {(100, "qemu"), (200, "lxc")}


def test_list_vms_tolerates_missing_optional_fields():
    payload = json.dumps([{"vmid": 100, "status": "stopped"}])
    runner = FakeRunner()
    runner.command_responses = [
        (lambda a: a[:3] == ["pvesh", "get", "/nodes/localhost/qemu"], FakeProc(0, payload, "")),
        (lambda a: a[:3] == ["pvesh", "get", "/nodes/localhost/lxc"], FakeProc(0, "[]", "")),
    ]
    result = pvm.list_vms(runner)
    assert result[0].name == ""
    assert result[0].cpu == 0.0
    assert result[0].mem == 0


def test_list_vms_uses_given_node():
    runner = FakeRunner()
    runner.command_responses = [
        (lambda a: a[:3] == ["pvesh", "get", "/nodes/pve1/qemu"], FakeProc(0, "[]", "")),
        (lambda a: a[:3] == ["pvesh", "get", "/nodes/pve1/lxc"], FakeProc(0, "[]", "")),
    ]
    result = pvm.list_vms(runner, node="pve1")
    assert result == []
    assert any(a[:3] == ["pvesh", "get", "/nodes/pve1/qemu"] for a in runner.calls)


# --------------------------------------------------------------------------
# vm_rrd_history
# --------------------------------------------------------------------------

def test_vm_rrd_history_empty_when_pvesh_fails():
    runner = FakeRunner()
    runner.command_responses = [(lambda a: a[:1] == ["pvesh"], FakeProc(2, "", "no such VM"))]
    result = pvm.vm_rrd_history(runner, "localhost", 100)
    assert result == []


def test_vm_rrd_history_parses_real_samples():
    payload = json.dumps([
        {"time": 1700000000, "cpu": 0.01, "mem": 100000000, "maxmem": 200000000},
        {"time": 1700000060, "cpu": 0.02, "mem": 110000000, "maxmem": 200000000},
    ])
    runner = FakeRunner()
    runner.command_responses = [
        (lambda a: a[:3] == ["pvesh", "get", "/nodes/localhost/qemu/100/rrddata"], FakeProc(0, payload, "")),
    ]
    result = pvm.vm_rrd_history(runner, "localhost", 100)
    assert len(result) == 2
    assert result[0]["cpu"] == 0.01


def test_vm_rrd_history_uses_lxc_path_for_containers():
    runner = FakeRunner()
    runner.command_responses = [
        (lambda a: a[:3] == ["pvesh", "get", "/nodes/localhost/lxc/200/rrddata"], FakeProc(0, "[]", "")),
    ]
    result = pvm.vm_rrd_history(runner, "localhost", 200, vm_type="lxc")
    assert result == []
    assert any(a[:3] == ["pvesh", "get", "/nodes/localhost/lxc/200/rrddata"] for a in runner.calls)
