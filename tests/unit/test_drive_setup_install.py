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
        self.existing_paths = set()
        self.killed_paths = []
        self.kill_process_using_path_returns = True
        self.scripted_popen_process = None

    def script(self, predicate, proc: InstallProc):
        self.command_responses.append((predicate, proc))

    def run(self, argv, timeout=30, cwd=None):
        self.calls.append(list(argv))
        for predicate, proc in self.command_responses:
            if predicate(argv):
                return proc
        return InstallProc(0, "", "")

    def popen(self, argv, cwd=None, monitor_socket=None):
        self.calls.append(list(argv))
        if self.scripted_popen_process is not None:
            return self.scripted_popen_process
        raise NotImplementedError("tests construct FakeInstallProcess directly")

    def kill_process_using_path(self, path):
        self.killed_paths.append(str(path))
        return self.kill_process_using_path_returns

    def path_exists(self, path):
        if str(path) in self.existing_paths:
            return True
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

def test_sparse_install_invocation_boots_cdrom_first_once_then_falls_back_to_disk():
    """Real bug found live, 2026-09-29 (decision record 116): `once=d`
    only overrides the VERY FIRST boot of this QEMU process's life -
    every later boot within the same still-running process (including
    the auto installer's own guest-triggered reboot after a successful
    install) falls back to the *base* `order=` value. The previous
    `order=d,once=d` used `d` as both, so every reboot re-selected the
    CD-ROM and re-entered the installer against the now-already-
    installed disk - confirmed live via a real install that reached
    99% ("make system bootable"), rebooted, and was observed via a
    real screendump back at "Preparing installer mount points..." (a
    fresh installer boot, not the newly-installed disk). The base
    order must be `c` (disk) so only the first boot uses the CD-ROM."""
    inv = di.build_sparse_install_invocation(
        target_image=Path("/ws/target.img"), prepared_iso=Path("/ws/prepared.iso"),
        mac="52:54:00:ba:5e:11", smbios_product="baseline-test",
        serial_log=Path("/ws/serial.log"),
    )
    assert "-boot" in inv.argv
    boot_idx = inv.argv.index("-boot")
    assert inv.argv[boot_idx + 1] == "order=c,once=d"


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


def test_sparse_install_invocation_omits_serial_property_by_default():
    inv = di.build_sparse_install_invocation(
        target_image=Path("/ws/target.img"), prepared_iso=Path("/ws/prepared.iso"),
        mac="52:54:00:ba:5e:11", smbios_product="baseline-test",
        serial_log=Path("/ws/serial.log"),
    )
    drive_arg = next(a for a in inv.argv if a.startswith("file="))
    assert "serial=" not in drive_arg


def test_sparse_install_invocation_threads_target_serial_via_scsi_device_form():
    """Real bug found live, 2026-09-29 (decision record 114): the
    answer file's own `filter.ID_SERIAL_SHORT` asks Proxmox's installer
    to target the disk by its real hardware serial, but plain
    `-drive file=<dev>,if=virtio` never exposes any serial to the
    guest - confirmed live, a real install reached "Installation
    failed: filter did not match any device" even with decision record
    112's variable-shadowing fix already applied and correct.

    Two real, live-diagnosed corrections were needed: `serial=` is a
    QEMU **device** property, not a block-format option (a first
    attempt on the combined `-drive if=virtio,...,serial=...`
    shorthand failed immediately with a real QEMU error). A second,
    separate `-device virtio-blk-pci,...,serial=...` form then
    launched cleanly but still failed the *same* filter error - live
    `udevadm` inspection on the guest's own already-booted shell proved
    `virtio-blk-pci` only ever populates udev's `ID_SERIAL`, never
    `ID_SERIAL_SHORT`; a disposable hot-attached `virtio-scsi-pci` +
    `scsi-hd` test disk confirmed `ID_SERIAL_SHORT` *is* populated
    correctly for a SCSI-attached device. The target disk must
    therefore attach via `virtio-scsi-pci` + `scsi-hd`, not
    `virtio-blk-pci`, whenever a serial is being set."""
    inv = di.build_sparse_install_invocation(
        target_image=Path("/dev/sdd"), prepared_iso=Path("/ws/prepared.iso"),
        mac="52:54:00:ba:5e:11", smbios_product="baseline-test",
        serial_log=Path("/ws/serial.log"),
        target_serial="FD01N6557110C271B",
    )
    drive_arg = next(a for a in inv.argv if a.startswith("file="))
    assert "serial=" not in drive_arg  # never on the -drive line itself
    assert "file=/dev/sdd" in drive_arg
    assert "format=raw,if=none" in drive_arg
    assert "id=targetdisk" in drive_arg

    assert "-device" in inv.argv
    device_args = [inv.argv[i + 1] for i, a in enumerate(inv.argv) if a == "-device"]
    assert not any(a.startswith("virtio-blk-pci") for a in device_args)
    scsi_controller_arg = next(a for a in device_args if a.startswith("virtio-scsi-pci"))
    scsi_hd_arg = next(a for a in device_args if a.startswith("scsi-hd"))
    assert "id=targetscsi" in scsi_controller_arg
    assert "drive=targetdisk" in scsi_hd_arg
    assert "bus=targetscsi.0" in scsi_hd_arg

    boot_idx = inv.argv.index("-boot")
    assert inv.argv[boot_idx + 1] == "order=c,once=d"  # decision record 116
    assert "serial=FD01N6557110C271B" in scsi_hd_arg


def test_sparse_install_invocation_network_is_slirp_restricted_by_default():
    inv = di.build_sparse_install_invocation(
        target_image=Path("/ws/target.img"), prepared_iso=Path("/ws/prepared.iso"),
        mac="52:54:00:ba:5e:11", smbios_product="baseline-test",
        serial_log=Path("/ws/serial.log"),
    )
    nic_arg = next(a for a in inv.argv if a.startswith("user,"))
    assert "restrict=on" in nic_arg
    assert "mac=52:54:00:ba:5e:11" in nic_arg


def test_sparse_install_invocation_uses_guestfwd_when_given():
    """Real bug found live, 2026-09-29 (a regression from decision
    record 03's own already-proven fix): plain `-nic user,restrict=on`
    blocks the guest from reaching *any* real host-bound TCP service -
    confirmed directly, twice, with a real `Connection refused` (the
    installer's own answer-file POST, and an independent bash
    `/dev/tcp` probe). `guestfwd` punches the one real exception
    needed back through - it isn't expressible via the `-nic`
    shorthand at all, needing the long `-netdev`/`-device` form."""
    inv = di.build_sparse_install_invocation(
        target_image=Path("/ws/target.img"), prepared_iso=Path("/ws/prepared.iso"),
        mac="52:54:00:ba:5e:11", smbios_product="baseline-test",
        serial_log=Path("/ws/serial.log"),
        guestfwd_host="10.0.2.100", guestfwd_port=8443,
    )
    assert "-nic" not in inv.argv  # guestfwd isn't expressible via the shorthand
    assert "-netdev" in inv.argv
    netdev_arg = inv.argv[inv.argv.index("-netdev") + 1]
    assert "guestfwd=tcp:10.0.2.100:8443-tcp:127.0.0.1:8443" in netdev_arg
    assert "restrict=on" in netdev_arg
    assert "-device" in inv.argv
    device_arg = inv.argv[inv.argv.index("-device") + 1]
    assert device_arg == "virtio-net-pci,netdev=net0,mac=52:54:00:ba:5e:11"
    assert "guestfwd" in inv.device_inventory["network"]


def test_sparse_install_invocation_falls_back_to_plain_nic_without_guestfwd():
    inv = di.build_sparse_install_invocation(
        target_image=Path("/ws/target.img"), prepared_iso=Path("/ws/prepared.iso"),
        mac="52:54:00:ba:5e:11", smbios_product="baseline-test",
        serial_log=Path("/ws/serial.log"),
    )
    assert "-netdev" not in inv.argv
    assert "-nic" in inv.argv


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


# -- send_monitor_command_via_socket / ppm_to_png / capture_live_screendump_png --
# Real bug found live, 2026-09-29: a manual `nc`-piped
# "screendump ...\nquit\n" accidentally terminated a real, in-progress
# install - `quit` is a genuine QEMU monitor command, not just a way to
# close the shell pipe. These functions are the real, safe fix.

def test_send_monitor_command_via_socket_sends_exactly_the_given_command(tmp_path):
    """Proves the real fix directly: only the one command asked for is
    ever sent - never anything else, never `quit`."""
    import socket
    import threading

    sock_path = tmp_path / "monitor.sock"
    received = []

    def _serve():
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.listen(1)
        conn, _ = srv.accept()
        conn.sendall(b"QEMU 8.0 monitor - type 'help' for more information\n(qemu) ")
        data = conn.recv(4096)
        received.append(data)
        conn.sendall(b"\r\n(qemu) ")
        conn.close()
        srv.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    import time as _time
    _time.sleep(0.1)
    di.send_monitor_command_via_socket(sock_path, "screendump /tmp/x.ppm", timeout=3.0)
    t.join(timeout=3.0)
    assert received == [b"screendump /tmp/x.ppm\n"]
    assert b"quit" not in received[0]


def _make_real_ppm(width: int, height: int, rgb: tuple) -> bytes:
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    return header + bytes(rgb) * (width * height)


def _decode_png_for_test(png_bytes: bytes) -> tuple:
    """Minimal, independent PNG chunk reader - stdlib only, deliberately
    not reusing ppm_to_png's own encoding logic, so this genuinely
    checks the encoder's real output rather than just mirroring it."""
    import struct
    import zlib
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    chunks = {}
    while pos < len(png_bytes):
        length = struct.unpack(">I", png_bytes[pos:pos + 4])[0]
        tag = png_bytes[pos + 4:pos + 8]
        data = png_bytes[pos + 8:pos + 8 + length]
        chunks.setdefault(tag, b"")
        chunks[tag] += data
        pos += 8 + length + 4
    width, height, bit_depth, color_type = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    raw = zlib.decompress(chunks[b"IDAT"])
    return width, height, bit_depth, color_type, raw


def test_ppm_to_png_round_trips_real_pixel_data():
    ppm = _make_real_ppm(2, 2, (10, 20, 30))
    png = di.ppm_to_png(ppm)
    width, height, bit_depth, color_type, raw = _decode_png_for_test(png)
    assert (width, height, bit_depth, color_type) == (2, 2, 8, 2)  # 2=RGB
    stride = 2 * 3
    for y in range(2):
        row = raw[y * (stride + 1):(y + 1) * (stride + 1)]
        assert row[0] == 0  # filter type "None"
        assert row[1:] == bytes((10, 20, 30)) * 2


def test_ppm_to_png_refuses_a_non_p6_input():
    with pytest.raises(ValueError):
        di.ppm_to_png(b"P3\nnot binary\n")


def test_capture_live_screendump_png_reads_the_real_written_file_and_cleans_up(tmp_path, monkeypatch):
    monitor_socket = tmp_path / "monitor.sock"
    written_ppm = tmp_path / "target.ppm"

    def _fake_send(sock, command, *, timeout=5.0):
        # Simulates the real QEMU monitor actually writing the file to disk.
        assert sock == monitor_socket
        assert command == f"screendump {written_ppm}"
        assert "quit" not in command
        written_ppm.write_bytes(_make_real_ppm(1, 1, (255, 0, 0)))
        return ""

    monkeypatch.setattr(di, "send_monitor_command_via_socket", _fake_send)
    monkeypatch.setattr(di.time, "sleep", lambda s: None)
    png_bytes = di.capture_live_screendump_png(monitor_socket, tmp_path=written_ppm, timeout=1.0)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert not written_ppm.exists()  # the temp PPM is cleaned up after conversion
