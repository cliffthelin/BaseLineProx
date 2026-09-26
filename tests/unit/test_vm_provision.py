"""Unit tests for vm_provision.py (Track A6 follow-on) - generalizes
Track A4's proven manual qm workflow into reusable, Runner-tested code.
No real qm/pvesh is ever invoked - the FakeRunner records every argv
and returns scripted results, matching repair.py's established
convention."""
from fake_runner import FakeProc, FakeRunner

import vm_provision as vp


# -- pure argv builders: the actual command contract -----------------------

def test_next_free_vmid_argv():
    assert vp.next_free_vmid_argv() == ["pvesh", "get", "/cluster/nextid"]


def test_create_vm_argv_shape():
    argv = vp.create_vm_argv(201, "debian-example", iso="local:iso/debian-12.iso")
    assert argv == [
        "qm", "create", "201",
        "--name", "debian-example",
        "--memory", "2048",
        "--cores", "2",
        "--net0", "virtio,bridge=vmbr0",
        "--scsi0", "local-lvm:8",
        "--ide2", "local:iso/debian-12.iso,media=cdrom",
        "--boot", "order=ide2;scsi0",
    ]


def test_attach_persistence_disk_argv_shape():
    argv = vp.attach_persistence_disk_argv(201, size_gb=4)
    assert argv == ["qm", "set", "201", "--scsi1", "baseline-persist:4"]


def test_destroy_vm_argv_purges_by_default():
    assert vp.destroy_vm_argv(201) == ["qm", "destroy", "201", "--purge"]


def test_destroy_vm_argv_without_purge():
    assert vp.destroy_vm_argv(201, purge=False) == ["qm", "destroy", "201"]


def test_reassign_persistence_disk_argv_shape():
    argv = vp.reassign_persistence_disk_argv(201, "unused0", 202)
    assert argv == ["qm", "disk", "move", "201", "unused0", "--target-vmid", "202"]


# -- next_free_vmid(): real parsing of pvesh output -------------------------

def test_next_free_vmid_parses_pvesh_output():
    runner = FakeRunner(command_responses=[
        (lambda a: a == ["pvesh", "get", "/cluster/nextid"], FakeProc(0, "203\n", "")),
    ])
    assert vp.next_free_vmid(runner) == 203


def test_next_free_vmid_raises_on_pvesh_failure():
    runner = FakeRunner(command_responses=[
        (lambda a: a == ["pvesh", "get", "/cluster/nextid"], FakeProc(1, "", "connection refused")),
    ])
    try:
        vp.next_free_vmid(runner)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "connection refused" in str(exc)


# -- create_vm() / attach_persistence_disk() / start_vm() / stop_vm() ------

def test_create_vm_reports_success():
    runner = FakeRunner()
    result = vp.create_vm(runner, 201, "debian-example", iso="local:iso/debian-12.iso")
    assert result.ok is True
    assert runner.calls[0][:3] == ["qm", "create", "201"]


def test_create_vm_reports_the_real_failure_detail():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["qm", "create"], FakeProc(1, "", "VM 201 already exists")),
    ])
    result = vp.create_vm(runner, 201, "debian-example", iso="local:iso/debian-12.iso")
    assert result.ok is False
    assert "already exists" in result.detail


def test_attach_persistence_disk_reports_success():
    runner = FakeRunner()
    result = vp.attach_persistence_disk(runner, 201, size_gb=4)
    assert result.ok is True
    assert runner.calls[0] == ["qm", "set", "201", "--scsi1", "baseline-persist:4"]


def test_start_and_stop_vm_call_qm_directly():
    runner = FakeRunner()
    vp.start_vm(runner, 201)
    vp.stop_vm(runner, 201)
    assert runner.calls == [["qm", "start", "201"], ["qm", "stop", "201"]]


# -- retire_vm_preserving_persistence(): the exact ordering A4 proved -------

def test_retire_reassigns_the_disk_before_destroying():
    runner = FakeRunner()
    result = vp.retire_vm_preserving_persistence(runner, 201, 202, unused_key="unused0")
    assert result.ok is True
    assert runner.calls[0] == ["qm", "disk", "move", "201", "unused0", "--target-vmid", "202"]
    assert runner.calls[1] == ["qm", "destroy", "201", "--purge"]


def test_retire_never_destroys_if_the_reassignment_fails():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:3] == ["qm", "disk", "move"], FakeProc(1, "", "no such unused disk")),
    ])
    result = vp.retire_vm_preserving_persistence(runner, 201, 202, unused_key="unused0")
    assert result.ok is False
    assert "NOT destroyed" in result.detail
    # the destroy argv must never even have been attempted
    assert ["qm", "destroy", "201", "--purge"] not in runner.calls


def test_retire_reports_when_destroy_fails_after_a_successful_reassignment():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["qm", "destroy"], FakeProc(1, "", "VM is locked")),
    ])
    result = vp.retire_vm_preserving_persistence(runner, 201, 202, unused_key="unused0")
    assert result.ok is False
    assert "reassigned to VM 202" in result.detail
    assert "VM is locked" in result.detail
