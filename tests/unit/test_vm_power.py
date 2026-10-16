"""Start, shut down and details for the TUI's VMs tab (operator 2026-10-14, item 9: the tab "shows when I have made a VM but nothing more").

Pure functions: the exact Proxmox commands for a VM or container, validated, and the text shown for a row. The TUI only calls these."""
import pytest

import proxmox_vm_metrics as pvm
import vm_power as vp


@pytest.mark.parametrize("kind,action,argv", [
    ("qemu", "start", ["qm", "start", "101"]), ("qemu", "shutdown", ["qm", "shutdown", "101"]),
    ("lxc", "start", ["pct", "start", "101"]), ("lxc", "shutdown", ["pct", "shutdown", "101"]),
])
def test_the_commands_are_exactly_the_proxmox_ones(kind, action, argv):
    assert vp.power_argv(kind, 101, action) == argv


@pytest.mark.parametrize("args", [
    ("kvm", 101, "start"), ("qemu", 101, "reboot"), ("qemu", "101; reboot", "start"), ("qemu", 99, "start"), ("qemu", True, "start"),
    ("qemu", None, "start"), ("qemu", 1_000_000_000, "start"), ("qemu", -5, "start"), ("qemu", 101, "stop"), ("qemu", 101, "destroy"),
])
def test_nothing_else_reaches_a_command(args):
    with pytest.raises(ValueError):
        vp.power_argv(*args)


def test_only_a_stopped_machine_can_be_started_and_only_a_running_one_shut_down():
    stopped, running = pvm.VmStatus(vmid=101, name="a", status="stopped"), pvm.VmStatus(vmid=102, name="b", status="running")
    unknown = pvm.VmStatus(vmid=103, name="c", status="unknown")
    assert vp.allowed_action(stopped) == "start" and vp.allowed_action(running) == "shutdown"
    assert vp.allowed_action(unknown) is None


def test_the_message_after_an_action_says_what_happened_and_never_claims_more():
    ok = vp.result_message("start", "web", 101, returncode=0, output="")
    assert "Start requested" in ok and "web" in ok and "101" in ok
    failed = vp.result_message("shutdown", "web", 101, returncode=2, output="VM is locked (backup)\n")
    assert "failed" in failed.lower() and "locked" in failed
    assert "unavailable" in vp.result_message("start", "web", 101, returncode=None, output="").lower()


def test_details_list_what_is_known_and_say_unknown_for_the_rest():
    vm = pvm.VmStatus(vmid=101, name="ubuntu-desk", type="qemu", status="running", cpu=0.123, mem=2 * 2**30, maxmem=4 * 2**30,
                      disk=3 * 2**30, maxdisk=32 * 2**30, netin=1024, netout=2048, uptime=3725)
    text = vp.details(vm)
    for fragment in ("ubuntu-desk", "101", "virtual machine", "running", "12.3%", "2048 MiB of 4096 MiB", "3.0 GiB of 32.0 GiB", "1h2m"):
        assert fragment in text, fragment
    sparse = vp.details(pvm.VmStatus(vmid=200, name="svc", type="lxc", status="stopped"))
    assert "container" in sparse and "unknown" in sparse
