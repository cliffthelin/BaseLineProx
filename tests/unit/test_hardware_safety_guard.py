"""The test suite must be incapable of touching real hardware, whatever the code under test does.

Why this exists: on 2026-10-01 a test run with a deliberately weakened guard (a mutation check) reached the real
`build_self_installer` pipeline with a device path written `/dev/sdb`. It built an installer ISO and launched QEMU
against whatever /dev/sdb is on the machine running the tests, which was a media drive. Tests that pass fake
device names are only safe while the code under test cooperates. This guard (tests/unit/conftest.py, autouse for
every test) refuses at the lowest level: no test may launch QEMU or run a disk, partition, mount, privilege or
service-control command for real, and none may open a device node under /dev."""
import os
import subprocess

import pytest

from conftest import HardwareSafetyViolation


@pytest.mark.parametrize("argv", [
    ["qemu-system-x86_64", "-drive", "file=/dev/sdb,format=raw"], ["/usr/bin/qemu-system-x86_64"], ["qemu-img", "create"],
    ["wipefs", "-a", "/dev/sdb"], ["/usr/sbin/wipefs", "-a", "/dev/sdb"], ["sgdisk", "-Z", "/dev/sdb"],
    ["parted", "/dev/sdb", "mklabel", "gpt"], ["mkfs.ext4", "/dev/sdb1"], ["mke2fs", "/dev/sdb1"], ["dd", "if=/dev/zero", "of=/dev/sdb"],
    ["pvcreate", "/dev/sdb"], ["vgchange", "-ay"], ["lvremove", "x"], ["mount", "/dev/sdb1", "/mnt/x"], ["umount", "/mnt/x"],
    ["sudo", "-n", "true"], ["pkexec", "true"], ["systemctl", "stop", "ssh"], ["partprobe"], ["losetup", "-f"], ["cryptsetup", "open"],
    ["shutdown", "now"], ["reboot"], ["efibootmgr"], ["tune2fs", "-L", "x", "/dev/sdb1"], ["e2label", "/dev/sdb1", "x"],
    ["sh", "-c", "wipefs -a /dev/sdb"], ["bash", "-c", "echo hi && qemu-system-x86_64 -m 1"],
])
def test_dangerous_programs_are_refused_before_they_start(argv):
    with pytest.raises(HardwareSafetyViolation):
        subprocess.Popen(argv)
    with pytest.raises(HardwareSafetyViolation):
        subprocess.run(argv, capture_output=True)


def test_a_command_given_as_a_string_is_checked_too():
    with pytest.raises(HardwareSafetyViolation):
        subprocess.run("qemu-system-x86_64 -m 1", shell=True)
    with pytest.raises(HardwareSafetyViolation):
        subprocess.check_output("wipefs -a /dev/sdb", shell=True)


def test_os_level_launchers_are_refused_too():
    with pytest.raises(HardwareSafetyViolation):
        os.system("qemu-system-x86_64 -m 1")
    with pytest.raises(HardwareSafetyViolation):
        os.popen("wipefs -a /dev/sdb")


@pytest.mark.parametrize("path", ["/dev/sda", "/dev/sdb", "/dev/sdd1", "/dev/nvme0n1", "/dev/nvme1n1p2", "/dev/disk/by-id/ata-x",
                                  "/dev/mapper/pve-root", "/dev/loop0", "/dev/dm-0"])
@pytest.mark.parametrize("mode", ["rb", "wb", "r+b"])
def test_opening_a_device_node_is_refused(path, mode):
    with pytest.raises(HardwareSafetyViolation):
        open(path, mode)
    with pytest.raises(HardwareSafetyViolation):
        os.open(path, os.O_RDONLY)


def test_harmless_programs_and_pseudo_devices_still_work(tmp_path):
    assert subprocess.run(["true"]).returncode == 0
    assert subprocess.run(["echo", "hello"], capture_output=True, text=True).stdout.strip() == "hello"
    with open("/dev/null", "wb") as fh:
        fh.write(b"x")
    assert len(open("/dev/urandom", "rb").read(4)) == 4
    target = tmp_path / "a.tar.gz"
    subprocess.run(["tar", "-czf", str(target), "-C", str(tmp_path), "."], check=False, capture_output=True)


def test_the_guard_is_active_for_a_test_that_does_not_ask_for_it():
    """Autouse: there is nothing a test has to remember to opt into."""
    assert getattr(subprocess.Popen, "_hardware_safety_guard", False) is True


def test_the_violation_is_an_assertion_error_so_it_can_never_be_swallowed_as_a_normal_failure():
    assert issubclass(HardwareSafetyViolation, AssertionError)
