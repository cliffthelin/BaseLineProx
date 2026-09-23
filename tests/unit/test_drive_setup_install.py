"""Unit tests for drive_setup_install.py - QEMU invocation construction,
screendump-based progress capture, bounded process waiting, and static
(file-based, no loop device) image verification. FakeInstallRunner/
FakeInstallProcess-scripted where a process boundary is involved;
scan_for_forbidden_bytes is tested against real small files since it's
pure byte-stream logic with no external process."""
import subprocess
from pathlib import Path

import pytest

import drive_setup_install as di
from drive_setup_install import InstallRunner, InstallProc, InstallProcess


class FakeInstallProcess(InstallProcess):
    def __init__(self, exit_code=None, raise_timeout_on_wait=False):
        self._exit_code = exit_code
        self._raise_timeout = raise_timeout_on_wait
        self.monitor_commands = []
        self.killed = False

    def poll(self):
        return self._exit_code

    def wait(self, timeout=None):
        if self._raise_timeout:
            self._raise_timeout = False  # only the first wait() times out
            raise subprocess.TimeoutExpired(cmd="qemu-system-x86_64", timeout=timeout)
        return self._exit_code if self._exit_code is not None else 0

    def kill_process_group(self):
        self.killed = True

    def send_monitor_command(self, command):
        self.monitor_commands.append(command)
        return "(qemu) "


class FakeInstallRunner(InstallRunner):
    def __init__(self):
        self.command_responses = []
        self.calls = []
        self.truncated = {}
        self._clock = 1_700_000_000.0
        self.sleeps = []

    def script(self, predicate, proc: InstallProc):
        self.command_responses.append((predicate, proc))

    def run(self, argv, timeout=30, cwd=None):
        self.calls.append(list(argv))
        for predicate, proc in self.command_responses:
            if predicate(argv):
                return proc
        return InstallProc(0, "", "")

    def popen(self, argv, cwd=None):
        raise NotImplementedError("tests construct FakeInstallProcess directly")

    def path_exists(self, path):
        return str(path) in self.truncated

    def file_size(self, path):
        return self.truncated.get(str(path), 0)

    def truncate_sparse_file(self, path, size_bytes):
        self.truncated[str(path)] = size_bytes

    def now(self):
        return self._clock

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self._clock += seconds


# --------------------------------------------------------------------------
# QEMU invocation construction
# --------------------------------------------------------------------------

def test_sparse_install_invocation_boots_cdrom_first_once():
    inv = di.build_sparse_install_invocation(
        target_image=Path("/ws/target.img"), prepared_iso=Path("/ws/prepared.iso"),
        mac="52:54:00:ba:5e:11", smbios_product="baseline-test",
        serial_log=Path("/ws/serial.log"),
    )
    assert "-boot" in inv.argv
    boot_idx = inv.argv.index("-boot")
    assert inv.argv[boot_idx + 1] == "order=d,once=d"


def test_sparse_install_invocation_uses_only_sparse_target_and_iso():
    inv = di.build_sparse_install_invocation(
        target_image=Path("/ws/target.img"), prepared_iso=Path("/ws/prepared.iso"),
        mac="52:54:00:ba:5e:11", smbios_product="baseline-test",
        serial_log=Path("/ws/serial.log"),
    )
    drive_args = [a for a in inv.argv if a.startswith("file=")]
    assert len(drive_args) == 1
    assert "target.img" in drive_args[0]
    assert any("prepared.iso" in a for a in inv.argv)
    assert inv.device_inventory["no_other_drives"] is True
    assert inv.device_inventory["no_host_block_device_paths"] is True


def test_sparse_install_invocation_network_is_slirp_restricted_by_default():
    inv = di.build_sparse_install_invocation(
        target_image=Path("/ws/target.img"), prepared_iso=Path("/ws/prepared.iso"),
        mac="52:54:00:ba:5e:11", smbios_product="baseline-test",
        serial_log=Path("/ws/serial.log"),
    )
    nic_arg = next(a for a in inv.argv if a.startswith("user,"))
    assert "restrict=on" in nic_arg
    assert "mac=52:54:00:ba:5e:11" in nic_arg


def test_postinstall_boot_invocation_never_attaches_cdrom():
    """Decision record 04's confirmed defect: installer media left
    first in boot order can silently re-enter itself against an
    already-installed disk. The post-install boot invocation must not
    attach any CD-ROM at all."""
    inv = di.build_postinstall_boot_invocation(
        target_image=Path("/ws/target.img"), mac="52:54:00:ba:5e:11",
        smbios_product="baseline-test", serial_log=Path("/ws/serial.log"),
    )
    assert not any("-cdrom" in a for a in inv.argv)
    assert inv.device_inventory["no_cdrom_attached"] is True
    boot_idx = inv.argv.index("-boot")
    assert inv.argv[boot_idx + 1] == "order=c"


def test_create_sparse_target_uses_runner_not_real_filesystem():
    r = FakeInstallRunner()
    di.create_sparse_target(r, Path("/ws/target.img"), size_gb=16)
    assert r.truncated["/ws/target.img"] == 16 * (1 << 30)


# --------------------------------------------------------------------------
# Screendump-based progress capture
# --------------------------------------------------------------------------

def test_capture_screendumps_stops_when_process_exits():
    r = FakeInstallRunner()
    proc = FakeInstallProcess(exit_code=None)
    # Simulate exit after the 3rd poll by flipping exit_code mid-loop.
    call_count = {"n": 0}
    orig_poll = proc.poll

    def poll_side_effect():
        call_count["n"] += 1
        if call_count["n"] > 3:
            return 0
        return None
    proc.poll = poll_side_effect

    captures = di.capture_screendumps(r, proc, Path("/ws"), interval_s=1.0, max_captures=100)
    assert len(captures) == 3
    assert len(proc.monitor_commands) == 3
    assert all(cmd.startswith("screendump ") for cmd in proc.monitor_commands)


def test_capture_screendumps_respects_max_captures():
    r = FakeInstallRunner()
    proc = FakeInstallProcess(exit_code=None)  # never exits
    captures = di.capture_screendumps(r, proc, Path("/ws"), interval_s=1.0, max_captures=5)
    assert len(captures) == 5


def test_capture_screendumps_records_increasing_timestamps():
    r = FakeInstallRunner()
    proc = FakeInstallProcess(exit_code=None)
    captures = di.capture_screendumps(r, proc, Path("/ws"), interval_s=10.0, max_captures=3)
    times = [c.t for c in captures]
    assert times == sorted(times)
    assert times[-1] > times[0]


# --------------------------------------------------------------------------
# Bounded wait / kill-on-timeout
# --------------------------------------------------------------------------

def test_run_bounded_returns_exit_code_when_process_exits_normally():
    r = FakeInstallRunner()
    proc = FakeInstallProcess(exit_code=0)
    timed_out, rc = di.run_bounded(r, proc, timeout_s=30)
    assert not timed_out
    assert rc == 0
    assert not proc.killed


def test_run_bounded_kills_process_group_on_timeout():
    r = FakeInstallRunner()
    proc = FakeInstallProcess(exit_code=0, raise_timeout_on_wait=True)
    timed_out, rc = di.run_bounded(r, proc, timeout_s=30)
    assert timed_out
    assert proc.killed


# --------------------------------------------------------------------------
# Static image verification (file-based, no loop device)
# --------------------------------------------------------------------------

def test_verify_image_structure_uses_fdisk_and_blkid_never_mount():
    r = FakeInstallRunner()
    r.script(lambda a: a[:1] == ["fdisk"], InstallProc(0, "Disk /ws/target.img: 16 GiB", ""))
    r.script(lambda a: a[:1] == ["blkid"], InstallProc(0, "PTTYPE=\"gpt\"", ""))
    result = di.verify_image_structure(r, Path("/ws/target.img"))
    assert result["fdisk_rc"] == 0
    assert "16 GiB" in result["fdisk_summary"]
    assert result["blkid_rc"] == 0
    assert not any(c[0] in ("mount", "losetup") for c in r.calls)


def test_scan_for_forbidden_bytes_finds_canary_in_real_file(tmp_path):
    target = tmp_path / "target.img"
    target.write_bytes(b"x" * 1000 + b"SECRET_PASSWORD_CANARY" + b"y" * 1000)
    r = FakeInstallRunner()
    result = di.scan_for_forbidden_bytes(r, target, [b"SECRET_PASSWORD_CANARY", b"NOT_PRESENT"])
    assert result["SECRET_PASSWORD_CANARY"] is True
    assert result["NOT_PRESENT"] is False


def test_scan_for_forbidden_bytes_catches_canary_split_across_chunk_boundary(tmp_path):
    """The canary must be found even if a naive per-chunk scan would
    miss it because it straddles the boundary between two reads."""
    target = tmp_path / "target.img"
    canary = b"BOUNDARY_STRADDLING_CANARY_0123456789"
    chunk_size = 64
    # Position the canary so it starts a few bytes before a chunk boundary.
    prefix_len = chunk_size - 5
    target.write_bytes(b"a" * prefix_len + canary + b"b" * 200)
    r = FakeInstallRunner()
    result = di.scan_for_forbidden_bytes(r, target, [canary], chunk_size=chunk_size)
    assert result[canary.decode()] is True


def test_scan_for_forbidden_bytes_empty_file(tmp_path):
    target = tmp_path / "empty.img"
    target.write_bytes(b"")
    r = FakeInstallRunner()
    result = di.scan_for_forbidden_bytes(r, target, [b"anything"])
    assert result["anything"] is False
