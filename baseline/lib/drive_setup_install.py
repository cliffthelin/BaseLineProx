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

    def kill_process_using_path(self, path: Path) -> bool:
        """Real fix, decision record 113: a prior run's own QEMU
        process, uniquely identified by this exact monitor-socket path
        in its argv, may still be alive and holding the workspace (and
        the real device) even though this new run just rebuilt fresh
        ISOs/answer files - nothing ever killed it before. Returns
        whether a live process was found and killed."""
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

    def kill_process_using_path(self, path):
        found = subprocess.run(["pgrep", "-f", str(path)], capture_output=True, text=True)
        pids = [int(p) for p in found.stdout.split() if p.strip()]
        killed = False
        for pid in pids:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
                killed = True
            except (ProcessLookupError, PermissionError):
                pass
        return killed


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


def _network_argv(*, mac: str, restrict_network: bool,
                   guestfwd_host: str | None, guestfwd_port: int | None) -> list:
    """Real bug found live, 2026-09-29 (a real regression from decision
    record 03's own already-proven fix): `-nic user,restrict=on,mac=...`
    alone blocks the VM from reaching *any* real host-bound TCP
    service via SLIRP's `10.0.2.2` gateway - demonstrated directly, at
    the time, with a real `io: Connection refused` on the installer's
    own answer-file POST, and re-confirmed the same way here. DHCP/DNS/
    router-advertisement traffic works because SLIRP implements those
    protocols *internally*, not because anything is proxied to a real
    host socket. `guestfwd=tcp:<host>:<port>-tcp:127.0.0.1:<port>`
    punches one explicit, single-service exception through
    `restrict=on` - stronger isolation than a blanket "block LAN/
    internet only" approach, since it's "block everything, except this
    one named service." `guestfwd` isn't expressible via the `-nic`
    shorthand at all - it needs the long `-netdev` + `-device
    virtio-net-pci` form."""
    if guestfwd_host and guestfwd_port:
        netdev = (f"user,id=net0,restrict={'on' if restrict_network else 'off'},"
                  f"guestfwd=tcp:{guestfwd_host}:{guestfwd_port}-tcp:127.0.0.1:{guestfwd_port}")
        return ["-netdev", netdev, "-device", f"virtio-net-pci,netdev=net0,mac={mac}"]
    return ["-nic", f"user,restrict={'on' if restrict_network else 'off'},mac={mac}"]


def build_sparse_install_invocation(
    *, target_image: Path, prepared_iso: Path, mac: str, smbios_product: str,
    serial_log: Path, memory_mb: int = 3072, smp: int = 2,
    restrict_network: bool = True, monitor_socket: Path | None = None,
    guestfwd_host: str | None = None, guestfwd_port: int | None = None,
    target_serial: str | None = None,
) -> QemuInvocation:
    """Sparse-file-only, guestfwd/restrict-isolated networking, no
    other drives, no host block-device paths - matching decision
    record 03's accepted design exactly (see `_network_argv`'s own
    docstring for the real bug this restores the fix for).

    `-boot order=c,once=d` (real bug found live, 2026-09-29, decision
    record 116): `once=d` overrides the boot device for the VERY FIRST
    boot of this QEMU process's life only - every *subsequent* boot
    within the same still-running process (including the auto
    installer's own VM-triggered `reboot` after a successful
    install, confirmed live via a real screendump reading "INFO:
    Rebooting system after successful installation") falls back to the
    **base** `order=` value. The code previously used `order=d,once=d`
    - `d` as *both* the override and the base - so every reboot,
    forever, kept re-selecting the CD-ROM and silently re-entered the
    installer environment from scratch against the now-already-
    installed disk, exactly the failure this docstring already warned
    about (see decision record 04) without the code ever actually
    implementing the fix for it. Confirmed live: a real install that
    reached 99% ("make system bootable") and genuinely rebooted was
    then observed, via a real screendump, back at "Preparing installer
    mount points..." - a full fresh boot of the installer ISO again,
    not the newly-installed disk - which re-failed the answer-file
    fetch (a fresh session token is generated per invocation, so a
    second auto-install attempt within the same process can never
    complete). `order=c` as the base value means any reboot after the
    first uses the disk - now the just-installed, bootable Proxmox
    system - instead of re-entering the CD-ROM's installer. This
    matches decision record 04's own already-documented finding that
    installer media left first in boot order can silently re-enter
    itself against an already-installed disk - this fix is the first
    time that finding was actually applied within this same,
    self-rebooting QEMU session rather than assumed to only matter for
    a hypothetical separate, later boot invocation.

    `guestfwd_host`/`guestfwd_port` (real bug found live, 2026-09-29):
    when given, punches the one real `guestfwd` exception through
    `restrict=on` the answer-file fetch actually needs - omitted (the
    default), this falls back to the plain `-nic` shorthand, which
    real testing proved cannot reach any host service at all.

    `target_serial` (real bug found live, 2026-09-29, decision record
    114): the answer file's own `filter.ID_SERIAL_SHORT` asks
    Proxmox's installer to target the disk by its real hardware
    serial - but plain `-drive file=<real device>,if=virtio` never
    exposes that serial to the VM at all. The VM's own udev sees
    a blank/absent serial on the virtio-blk device regardless of what
    the *host* device's real serial is, so the filter genuinely
    matches nothing - confirmed live, "Installation failed: filter did
    not match any device", well past decision record 112's own
    variable-shadowing fix (which was real and necessary, but not
    sufficient on its own).

    `serial=` is a **device** property, not a block-format/backend
    option - real, direct evidence: appending it onto the combined
    `-drive if=virtio,...,serial=...` shorthand fails immediately with
    a real QEMU error, `Block format 'raw' does not support the option
    'serial'` (confirmed live against the actual installed QEMU
    10.2.1). An interim fix moved `serial=` onto a separate `-device
    virtio-blk-pci,drive=...,serial=...` instead - that launched, but
    the real install still failed with the exact same filter error.
    Live diagnosis on the VM's own already-booted, already-failed
    shell (`udevadm info --query=property`, real HMP `sendkey`
    keystrokes typed in and read back via screendump, never guessed)
    proved why: `virtio-blk-pci` devices only ever populate udev's
    `ID_SERIAL` property, never `ID_SERIAL_SHORT` - a second,
    disposable hot-attached test disk (`virtio-scsi-pci` + `scsi-hd`,
    never touching the real target) confirmed `ID_SERIAL_SHORT` *is*
    populated correctly, but only for a SCSI-attached device. Proxmox's
    own filter checks `ID_SERIAL_SHORT` specifically, which no
    virtio-blk device can ever satisfy regardless of what `serial=`
    value is set. When `target_serial` is given, the target disk is
    therefore attached via `virtio-scsi-pci` + `scsi-hd` instead of
    `virtio-blk-pci`."""
    if target_serial:
        argv = [
            "qemu-system-x86_64",
            "-enable-kvm", "-cpu", "host", "-m", str(memory_mb), "-smp", str(smp),
            "-drive", f"file={target_image},format=raw,if=none,id=targetdisk,cache=none",
            "-device", "virtio-scsi-pci,id=targetscsi",
            "-device", f"scsi-hd,drive=targetdisk,bus=targetscsi.0,serial={target_serial}",
            "-cdrom", str(prepared_iso),
            "-boot", "order=c,once=d",
            *_network_argv(mac=mac, restrict_network=restrict_network,
                           guestfwd_host=guestfwd_host, guestfwd_port=guestfwd_port),
            "-smbios", f"type=1,product={smbios_product}",
            "-serial", f"file:{serial_log}",
        ]
    else:
        argv = [
            "qemu-system-x86_64",
            "-enable-kvm", "-cpu", "host", "-m", str(memory_mb), "-smp", str(smp),
            "-drive", f"file={target_image},format=raw,if=virtio,cache=none",
            "-cdrom", str(prepared_iso),
            "-boot", "order=c,once=d",
            *_network_argv(mac=mac, restrict_network=restrict_network,
                           guestfwd_host=guestfwd_host, guestfwd_port=guestfwd_port),
            "-smbios", f"type=1,product={smbios_product}",
            "-serial", f"file:{serial_log}",
        ]
    if monitor_socket is not None:
        argv += ["-monitor", f"unix:{monitor_socket},server,nowait"]

    device_inventory = {
        "drives": [
            f"file={target_image.name},format=raw,if={'none (virtio-scsi-pci/scsi-hd, serial set - ID_SERIAL_SHORT-visible)' if target_serial else 'virtio'} (sparse target)",
            f"cdrom={prepared_iso.name} (read-only installer ISO)",
        ],
        "network": (f"user (SLIRP), restrict={'on' if restrict_network else 'off'}, mac={mac}"
                    + (f", guestfwd tcp:{guestfwd_host}:{guestfwd_port}->127.0.0.1:{guestfwd_port}"
                       if guestfwd_host and guestfwd_port else "")
                    + " - no bridge/tap, no host device passthrough"),
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


def send_monitor_command_via_socket(monitor_socket: Path, command: str, *, timeout: float = 5.0) -> str:
    """The same real, safe HMP-over-unix-socket pattern
    `_RealInstallProcess.send_monitor_command` already uses (connect,
    drain the banner, send one command, read the reply, close) - as a
    standalone function reachable with only the monitor socket's real
    path on disk, not a live `InstallProcess` object. Needed because a
    real, already-running install's own Python process handle does not
    survive past the single web request that launched it - only the
    socket file itself persists on disk for as long as QEMU is alive.

    Real bug found live, 2026-09-29 (direct instruction: "keep things
    improving"): a manual `nc`-piped `screendump ...\\nquit\\n` sent to
    this same socket accidentally terminated a real, in-progress
    install - `quit` is a genuine QEMU monitor command, not just a way
    to close the shell pipe. This function's own contract is the fix:
    it sends *exactly* the one real command asked for and nothing
    else, ever - there is no code path here that can send `quit`."""
    import socket
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(monitor_socket))
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


def ppm_to_png(ppm_bytes: bytes) -> bytes:
    """Minimal, stdlib-only P6 (binary) PPM -> PNG encoder - no new
    system dependency (no ImageMagick/ffmpeg is provisioned anywhere
    in this project) needed just to show a real QEMU screendump in a
    browser. RGB, 8-bit, no interlace, no filtering beyond the
    required per-scanline "None" filter byte - everything a raw QEMU
    screendump actually needs, nothing more."""
    import struct
    import zlib

    if not ppm_bytes.startswith(b"P6"):
        raise ValueError("not a P6 (binary) PPM")

    def _skip_ws_and_comments(data: bytes, pos: int) -> int:
        while True:
            while pos < len(data) and data[pos:pos + 1].isspace():
                pos += 1
            if pos < len(data) and data[pos:pos + 1] == b"#":
                while pos < len(data) and data[pos:pos + 1] != b"\n":
                    pos += 1
            else:
                return pos

    def _read_int(data: bytes, pos: int) -> tuple[int, int]:
        pos = _skip_ws_and_comments(data, pos)
        start = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        return int(data[start:pos]), pos

    pos = 2
    width, pos = _read_int(ppm_bytes, pos)
    height, pos = _read_int(ppm_bytes, pos)
    _maxval, pos = _read_int(ppm_bytes, pos)
    pos += 1  # the single whitespace byte required right after maxval
    pixel_data = ppm_bytes[pos:pos + width * height * 3]

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type "None"
        raw.extend(pixel_data[y * stride:(y + 1) * stride])
    compressed = zlib.compress(bytes(raw), 6)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b""))


def capture_live_screendump_png(monitor_socket: Path, *, tmp_path: Path | None = None,
                                 timeout: float = 5.0) -> bytes:
    """The real, safe, one-shot "what does the install screen look
    like right now" capture - the actual feature this project needed
    instead of a human (or an AI) hand-typing raw monitor commands
    over `nc`. Never sends `quit`; genuinely fails (raises, never a
    fake blank image) if no real install is running at this socket."""
    import os
    import tempfile
    target = Path(tmp_path) if tmp_path else Path(tempfile.gettempdir()) / f"screendump-{os.getpid()}.ppm"
    send_monitor_command_via_socket(monitor_socket, f"screendump {target}", timeout=timeout)
    time.sleep(0.5)  # the monitor reply returns before the file is necessarily flushed to disk
    ppm_bytes = target.read_bytes()
    try:
        target.unlink()
    except OSError:
        pass
    return ppm_to_png(ppm_bytes)
