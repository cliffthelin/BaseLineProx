"""Boundary 3: image installation and boot verification (Milestone 1, §4).

QEMU invocation construction (sparse-file-only, `guestfwd`-isolated
networking, mandatory boot-order enforcement), and periodic
screendump-based progress capture, reproducing decision record 03's
proven pattern (serial-only monitoring of this installer is not
viable - confirmed directly, the installer's own progress output goes
to the VGA console, not the serial port).

**Honest limitation, not silently automated**: decision record 03's
own Gate-C-equivalent verification ("the literal `Finished: 'ok'`
message") was read from a captured screendump by a vision-capable
agent (Claude Code), not by OCR - no OCR tooling is installed on this
host, and this module does not install any (`tesseract-ocr` would be a
host package install, out of scope per this project's standing
constraints). `capture_screendumps` here provides the fully-automatable
capture/save mechanism; `CompletionCheck` is the typed result a caller
(human or vision-capable agent) fills in after reading a captured PNG -
this module does not claim to autonomously read console text.

No longer responsible for producing working destination networking -
see the PRD's §3a and Gate A's own repair-based redefinition.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


class InstallRunner:
    def run(self, argv: list[str], timeout: float = 30, cwd: Path | None = None) -> "InstallProc":
        raise NotImplementedError

    def popen(self, argv: list[str], cwd: Path | None = None,
              monitor_socket: Path | None = None) -> "InstallProcess":
        raise NotImplementedError

    def path_exists(self, path: Path) -> bool:
        raise NotImplementedError

    def file_size(self, path: Path) -> int:
        raise NotImplementedError

    def truncate_sparse_file(self, path: Path, size_bytes: int) -> None:
        raise NotImplementedError

    def now(self) -> float:
        raise NotImplementedError

    def sleep(self, seconds: float) -> None:
        raise NotImplementedError


@dataclass
class InstallProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class InstallProcess:
    """A handle to a running (or finished) subprocess - separate from
    InstallProc (a completed run's result) because QEMU is long-lived
    and needs polling/waiting/killing, not a single blocking call."""

    def poll(self) -> int | None:
        raise NotImplementedError

    def wait(self, timeout: float | None = None) -> int:
        raise NotImplementedError

    def kill_process_group(self) -> None:
        raise NotImplementedError

    def send_monitor_command(self, command: str) -> str:
        """Send an HMP command over the QEMU monitor socket (e.g.
        `screendump <path>`), return the response text."""
        raise NotImplementedError


class RealInstallRunner(InstallRunner):
    def run(self, argv, timeout=30, cwd=None):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                   cwd=str(cwd) if cwd else None)
            return InstallProc(proc.returncode, proc.stdout, proc.stderr)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return InstallProc(returncode=-1, stderr=str(exc))

    def popen(self, argv, cwd=None, monitor_socket=None):
        return _RealInstallProcess(argv, cwd, monitor_socket=monitor_socket)

    def path_exists(self, path):
        return Path(path).exists()

    def file_size(self, path):
        return Path(path).stat().st_size

    def truncate_sparse_file(self, path, size_bytes):
        with open(path, "wb") as f:
            f.truncate(size_bytes)

    def now(self):
        return time.monotonic()

    def sleep(self, seconds):
        time.sleep(seconds)


class _RealInstallProcess(InstallProcess):
    def __init__(self, argv, cwd, monitor_socket: Path | None = None):
        self._proc = subprocess.Popen(argv, cwd=str(cwd) if cwd else None, start_new_session=True)
        self._monitor_socket = monitor_socket

    def poll(self):
        return self._proc.poll()

    def wait(self, timeout=None):
        return self._proc.wait(timeout=timeout)

    def kill_process_group(self):
        try:
            os.killpg(self._proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def send_monitor_command(self, command, timeout: float = 5.0) -> str:
        """A real HMP client over the QEMU monitor's unix socket -
        connect, drain the banner, send the command, read the reply.
        Matches this project's own proven vnc_type.py pattern."""
        if self._monitor_socket is None:
            raise RuntimeError("no monitor_socket configured for this process")
        import socket
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect(str(self._monitor_socket))
            try:
                s.recv(4096)  # banner
            except socket.timeout:
                pass
            s.sendall((command + "\n").encode())
            time.sleep(0.3)
            try:
                return s.recv(65536).decode("utf-8", errors="replace")
            except socket.timeout:
                return ""
        finally:
            s.close()


@dataclass
class QemuInvocation:
    argv: list[str]
    device_inventory: dict = field(default_factory=dict)


def build_sparse_install_invocation(
    *, target_image: Path, prepared_iso: Path, mac: str, smbios_product: str,
    serial_log: Path, memory_mb: int = 3072, smp: int = 2,
    restrict_network: bool = True, monitor_socket: Path | None = None,
) -> QemuInvocation:
    """Sparse-file-only, guestfwd/restrict-isolated networking, no
    other drives, no host block-device paths - matching decision
    record 03's accepted design exactly. `-boot order=d` (CD-ROM
    first) is correct for the *install* run; a *post-install* boot
    must instead use `order=c` (disk first) with the CD-ROM detached -
    see decision record 04's fresh-OVMF finding that installer media
    left first in boot order can silently re-enter itself against an
    already-installed disk."""
    argv = [
        "qemu-system-x86_64",
        "-enable-kvm", "-cpu", "host", "-m", str(memory_mb), "-smp", str(smp),
        "-drive", f"file={target_image},format=raw,if=virtio,cache=none",
        "-cdrom", str(prepared_iso),
        "-boot", "order=d,once=d",
        "-nic", f"user,restrict={'on' if restrict_network else 'off'},mac={mac}",
        "-smbios", f"type=1,product={smbios_product}",
        "-serial", f"file:{serial_log}",
    ]
    if monitor_socket is not None:
        argv += ["-monitor", f"unix:{monitor_socket},server,nowait"]

    device_inventory = {
        "drives": [
            f"file={target_image.name},format=raw,if=virtio (sparse target)",
            f"cdrom={prepared_iso.name} (read-only installer ISO)",
        ],
        "network": f"user (SLIRP), restrict={'on' if restrict_network else 'off'}, mac={mac} - no bridge/tap, no host device passthrough",
        "no_other_drives": True,
        "no_host_block_device_paths": True,
    }
    return QemuInvocation(argv=argv, device_inventory=device_inventory)


def build_postinstall_boot_invocation(
    *, target_image: Path, mac: str, smbios_product: str, serial_log: Path,
    memory_mb: int = 3072, smp: int = 2, restrict_network: bool = True,
    monitor_socket: Path | None = None,
) -> QemuInvocation:
    """Disk-only boot, no CD-ROM at all - the installer media is never
    left attached, so it cannot be silently re-entered (decision
    record 04's confirmed defect in the naive approach)."""
    argv = [
        "qemu-system-x86_64",
        "-enable-kvm", "-cpu", "host", "-m", str(memory_mb), "-smp", str(smp),
        "-drive", f"file={target_image},format=raw,if=virtio,cache=none",
        "-boot", "order=c",
        "-nic", f"user,restrict={'on' if restrict_network else 'off'},mac={mac}",
        "-smbios", f"type=1,product={smbios_product}",
        "-serial", f"file:{serial_log}",
    ]
    if monitor_socket is not None:
        argv += ["-monitor", f"unix:{monitor_socket},server,nowait"]
    device_inventory = {
        "drives": [f"file={target_image.name},format=raw,if=virtio (installed target, no installer media attached)"],
        "network": f"user (SLIRP), restrict={'on' if restrict_network else 'off'}, mac={mac}",
        "no_cdrom_attached": True,
    }
    return QemuInvocation(argv=argv, device_inventory=device_inventory)


def create_sparse_target(runner: InstallRunner, path: Path, size_gb: int) -> None:
    runner.truncate_sparse_file(path, size_gb * (1 << 30))


@dataclass
class ScreendumpCapture:
    """One captured frame - the caller (human or vision-capable agent)
    is responsible for reading its text content; this module only
    captures and timestamps it."""
    t: float
    ppm_path: Path


def capture_screendumps(runner: InstallRunner, process: InstallProcess, out_dir: Path, *,
                         interval_s: float = 10.0, max_captures: int = 180) -> list[ScreendumpCapture]:
    """Periodic screendump via the QEMU monitor socket, matching
    decision record 03's proven progress-monitoring mechanism - serial
    log alone is not viable for this installer (confirmed directly:
    the installer's own diagnostic output goes to the VGA console, not
    the serial port). Stops early if the process exits."""
    captures: list[ScreendumpCapture] = []
    for i in range(max_captures):
        if process.poll() is not None:
            break
        ppm_path = out_dir / f"screendump_{i:04d}.ppm"
        process.send_monitor_command(f"screendump {ppm_path}")
        captures.append(ScreendumpCapture(t=runner.now(), ppm_path=ppm_path))
        runner.sleep(interval_s)
    return captures


@dataclass
class CompletionCheck:
    """The typed result of checking a captured screendump for the
    installer's own literal completion message - never QEMU's exit
    code, never partition-table inference alone (Gate C's stated
    requirement). `checked_by` records who/what actually read the
    text, since this module cannot do so autonomously without OCR
    tooling this project does not install."""
    found: bool
    matched_text: str = ""
    screendump: Path | None = None
    checked_by: str = ""  # e.g. "claude-code-vision-read" or "tesseract-ocr:v5.x" once available


COMPLETION_MESSAGE_SUBSTRING = "Finished: 'ok'"


def run_bounded(runner: InstallRunner, process: InstallProcess, timeout_s: float) -> tuple[bool, int | None]:
    """Wait for the QEMU process to exit on its own, killing the whole
    process group (not just the parent) on timeout - matching decision
    record 02/03's `_run_bounded` pattern. Returns (timed_out, exit_code)."""
    try:
        rc = process.wait(timeout=timeout_s)
        return False, rc
    except subprocess.TimeoutExpired:
        process.kill_process_group()
        try:
            rc = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            rc = None
        return True, rc


def verify_image_structure(runner: InstallRunner, target_image: Path) -> dict:
    """Static, file-based verification only - never a loop device or
    mount, matching this project's whole-session discipline."""
    fdisk = runner.run(["fdisk", "-l", str(target_image)], timeout=15)
    blkid = runner.run(["blkid", "-p", str(target_image)], timeout=15)
    return {
        "fdisk_rc": fdisk.returncode,
        "fdisk_summary": fdisk.stdout.strip()[:800],
        "blkid_rc": blkid.returncode,
        "blkid_summary": blkid.stdout.strip()[:800],
    }


def scan_for_forbidden_bytes(runner: InstallRunner, target_image: Path, forbidden: list[bytes],
                              chunk_size: int = 64 * 1024 * 1024) -> dict:
    """Streamed, chunked byte scan of the final installed image for
    any credential canary - never load a multi-GB sparse image fully
    into memory at once."""
    found = {s: False for s in forbidden}
    overlap = max((len(s) for s in forbidden), default=0)
    prev_tail = b""
    with open(target_image, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            window = prev_tail + chunk
            for s in forbidden:
                if s in window:
                    found[s] = True
            prev_tail = chunk[-overlap:] if overlap else b""
    return {s.decode(errors="replace"): v for s, v in found.items()}
