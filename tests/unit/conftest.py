import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import repair
from fake_runner import FakeRunner, FakeProc

VMBR0_BRIDGE = """auto lo
iface lo inet loopback

iface enp0s31f6 inet manual

auto vmbr0
iface vmbr0 inet static
    address 10.0.2.15/24
    netmask 255.255.255.0
    gateway 10.0.2.2
    bridge-ports enp0s31f6
    bridge-stp off
"""


def healthy_facts():
    return [
        {"fact": "nic_detected", "ok": True, "detail": ""},
        {"fact": "driver_bound", "ok": True, "detail": ""},
        {"fact": "carrier_present", "ok": True, "detail": ""},
        {"fact": "address_assigned", "ok": True, "detail": ""},
        {"fact": "gateway_reachable", "ok": True, "detail": ""},
    ]


def broken_facts():
    return [
        {"fact": "nic_detected", "ok": True, "detail": ""},
        {"fact": "driver_bound", "ok": True, "detail": ""},
        {"fact": "carrier_present", "ok": True, "detail": ""},
        {"fact": "address_assigned", "ok": True, "detail": ""},
        {"fact": "gateway_reachable", "ok": False, "detail": "10.0.2.2: no ping reply"},
    ]


def make_ready_runner(files=None, target="vmbr0", new_addr="10.0.2.20/24", gateway="10.0.2.2",
                       clustered=False, protected_session=False, syntax_ok=True, apply_ok=True,
                       verify_ok=True):
    files = files if files is not None else {"/etc/network/interfaces": VMBR0_BRIDGE}
    r = FakeRunner(files=files)

    r.script(lambda a: a[:2] == ["which", "ifreload"], FakeProc(0, "/usr/sbin/ifreload\n", ""))
    r.script(lambda a: a[:1] == ["dpkg-query"], FakeProc(0, "3.2.0", ""))
    r.script(lambda a: a[:1] == ["pvecm"],
             FakeProc(0, "", "") if not clustered else FakeProc(0, "Cluster information\nNodes: 3\n", ""))
    r.script(lambda a: a[:1] == ["ss"],
             FakeProc(0, "State  Recv-Q Send-Q Local Address:Port  Peer Address:Port\n", "") if not protected_session
             else FakeProc(0, "State  Recv-Q Send-Q Local Address:Port  Peer Address:Port\n"
                              "ESTAB  0      0      10.0.2.15:22       10.0.2.99:51000\n", ""))
    r.script(lambda a: a[:1] == ["systemd-run"], FakeProc(0, "", ""))
    r.script(lambda a: a[:2] == ["systemctl", "stop"], FakeProc(0, "", ""))
    r.script(lambda a: a[:2] == ["ifreload", "--syntax-check"],
             FakeProc(0, "", "") if syntax_ok else FakeProc(1, "", "syntax error near bridge-ports"))
    r.script(lambda a: a == ["ifreload", "-a"],
             FakeProc(0, "", "") if apply_ok else FakeProc(1, "", "ifreload: apply failed"))

    if verify_ok:
        r.script(lambda a: a[:5] == ["ip", "-4", "-o", "addr", "show"],
                 FakeProc(0, f"3: {target}    inet {new_addr} brd 10.0.2.255 scope global {target}\\       valid_lft forever preferred_lft forever\n", ""))
        r.script(lambda a: a[:4] == ["ip", "-4", "route", "show"],
                 FakeProc(0, f"default via {gateway} dev {target}\n", ""))
        r.script(lambda a: a[:1] == ["ping"], FakeProc(0, "", ""))
    else:
        r.script(lambda a: a[:5] == ["ip", "-4", "-o", "addr", "show"], FakeProc(0, "", ""))
        r.script(lambda a: a[:4] == ["ip", "-4", "route", "show"], FakeProc(0, "", ""))

    return r


@pytest.fixture
def ready_runner():
    return make_ready_runner()


@pytest.fixture(autouse=True)
def _isolated_settings_store(tmp_path, monkeypatch):
    """settings_store.py and registry.py (decision record 89) both talk
    to sqlite directly (no Runner injection - see their own module
    docstrings for why) - without this, any test that doesn't pass an
    explicit path would hit real default paths
    (`/etc/baseline/settings/master_config.db`,
    `/mnt/BASELINE/registry/foundation.db`) on whatever machine runs
    the suite. Autouse so this is true for every test in the suite by
    construction, not just ones that remember to opt in."""
    import settings_store
    import registry
    monkeypatch.setattr(settings_store, "DEFAULT_DB_PATH", str(tmp_path / "master_config.db"))
    monkeypatch.setattr(registry, "GLOBAL_DB_PATH", str(tmp_path / "foundation.db"))


# ---------------------------------------------------------------------------
# Hardware safety guard (autouse, every test). See test_hardware_safety_guard.py for why it exists:
# a test must be INCAPABLE of touching real hardware whatever the code under test does. It refuses, at
# the lowest level, to launch QEMU, run disk / partition / mount / privilege / service-control commands,
# or open a device node under /dev.
# ---------------------------------------------------------------------------

import builtins
import os
import re
import subprocess

_FORBIDDEN_PROGRAMS = re.compile(
    r"^(qemu(-system-.+|-img|-io|-nbd)?|kvm|wipefs|mkfs(\..+)?|mke2fs|mkswap|sgdisk|gdisk|sfdisk|fdisk|cfdisk|parted|partprobe|"
    r"partx|dd|shred|blkdiscard|pvcreate|pvremove|pvresize|pvmove|vgcreate|vgremove|vgextend|vgreduce|vgchange|lvcreate|"
    r"lvremove|lvchange|lvresize|lvextend|lvreduce|mount|umount|losetup|tune2fs|e2label|resize2fs|e2fsck|fsck(\..+)?|"
    r"cryptsetup|nvme|efibootmgr|grub-install|update-grub|reboot|poweroff|shutdown|halt|sudo|pkexec|su|systemctl|"
    r"virsh|multipass|docker|podman)$"
)
_SAFE_DEVICES = {"/dev/null", "/dev/zero", "/dev/urandom", "/dev/random", "/dev/stdin", "/dev/stdout", "/dev/stderr",
                 "/dev/tty", "/dev/fd"}


class HardwareSafetyViolation(AssertionError):
    """A test tried to touch real hardware. An AssertionError so no code under test can swallow it as an ordinary
    failure by catching a narrower exception type."""


def _program_names_in_shell_string(command: str) -> list:
    return re.findall(r"[A-Za-z0-9_./-]+", command)


def _check_argv(args, shell=False) -> None:
    if isinstance(args, (str, bytes, os.PathLike)):
        words = _program_names_in_shell_string(os.fsdecode(args))
        candidates = words if shell or " " in os.fsdecode(args) else words[:1]
    else:
        argv = [os.fsdecode(a) for a in args]
        candidates = argv[:1]
        if argv and os.path.basename(argv[0]) in ("sh", "bash", "dash", "zsh", "env", "nohup", "setsid", "timeout", "nice", "ionice", "xargs"):
            for a in argv[1:]:
                candidates += _program_names_in_shell_string(a)
    for word in candidates:
        if _FORBIDDEN_PROGRAMS.match(os.path.basename(word)):
            raise HardwareSafetyViolation(
                f"a test tried to run {os.path.basename(word)!r} for real. Tests must use FakeRunner / injected "
                f"runners; they may never launch QEMU or run disk, mount, privilege or service commands.")


def _check_device_path(path) -> None:
    try:
        p = os.fsdecode(path)
    except TypeError:
        return
    if p.startswith("/dev/") and p not in _SAFE_DEVICES and not p.startswith("/dev/fd/"):
        raise HardwareSafetyViolation(f"a test tried to open the device node {p!r}; tests may never touch real devices")


@pytest.fixture(autouse=True)
def _hardware_safety_guard(monkeypatch):
    real_popen = subprocess.Popen

    class GuardedPopen(real_popen):
        _hardware_safety_guard = True

        def __init__(self, args, *a, **kw):
            _check_argv(args, shell=bool(kw.get("shell")))
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)

    def _blocked_os(name):
        real = getattr(os, name)

        def wrapper(cmd, *a, **kw):
            _check_argv(cmd if isinstance(cmd, (str, bytes)) else cmd, shell=True)
            return real(cmd, *a, **kw)
        return wrapper

    for name in ("system", "popen"):
        monkeypatch.setattr(os, name, _blocked_os(name))

    for name in ("execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp", "execlpe", "spawnv", "spawnvp"):
        if hasattr(os, name):
            real = getattr(os, name)
            monkeypatch.setattr(os, name, (lambda real: lambda path, *a, **k: (_check_argv([path]), real(path, *a, **k))[1])(real))

    real_open, real_os_open = builtins.open, os.open

    def guarded_open(file, *a, **kw):
        _check_device_path(file)
        return real_open(file, *a, **kw)

    def guarded_os_open(path, *a, **kw):
        _check_device_path(path)
        return real_os_open(path, *a, **kw)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(os, "open", guarded_os_open)

    # Reading what is ON a real drive (drive_guard's lsblk) is read-only, but a test must still never depend on
    # the real machine's drives: every test that exercises it supplies a fake drive explicitly.
    try:
        import drive_admin
        # Backup freshness lives on the real drive; tests state it explicitly (default: a fresh backup exists).
        monkeypatch.setattr(drive_admin, "backup_is_fresh", lambda: True)
    except ImportError:
        pass
    try:
        import drive_guard

        def _no_real_drive_reads(argv):
            raise HardwareSafetyViolation(
                f"a test tried to read a real drive's contents with {argv[0]!r}; pass a fake `run=` instead")
        monkeypatch.setattr(drive_guard, "_default_run", _no_real_drive_reads)
    except ImportError:
        pass
