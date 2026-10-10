"""Real process and procfs observations for the local QEMU VM host."""
import subprocess
import time

import pytest

import vm_host as vh


def test_real_process_observation_reads_a_live_child_and_reaped_child():
    child = subprocess.Popen(["sleep", "30"])
    try:
        assert vh._real_alive(child.pid) is True
        deadline = time.monotonic() + 2
        argv = []
        while not argv and time.monotonic() < deadline:
            argv = vh._real_cmdline(child.pid)
            if not argv:
                time.sleep(0.01)
        assert argv and argv[0].endswith("sleep")
    finally:
        child.terminate()
        child.wait(timeout=5)
    assert vh._real_alive(child.pid) is False


def test_pid_zero_is_rejected_instead_of_reported_as_a_dead_process():
    with pytest.raises(vh.VmError, match="positive process ID"):
        vh._real_alive(0)
    with pytest.raises(vh.VmError, match="positive process ID"):
        vh._real_cmdline(0)


def test_iso_inventory_rejects_a_real_file_where_a_directory_is_required():
    with pytest.raises(vh.VmError, match="ISO directory"):
        vh.list_isos("/etc/hostname")


def test_iso_inventory_rejects_a_real_symlinked_directory():
    with pytest.raises(vh.VmError, match="ISO directory.*symlink"):
        vh.list_isos("/proc/self")


def test_corrupt_real_pid_record_is_not_reported_as_missing():
    host = vh.VmHost("/var/lib/baseline-audit-no-write")
    with pytest.raises(vh.VmError, match="PID record"):
        host._recorded_pid("vm-audit", pidfile_path="/proc/self/mounts")
