"""Real Drive Administration actions for the merged web app (decision
record 83/84). Direct instruction: "this application will never get
off the ground if your solution is terminal commands" - every action
here is real code the web app itself executes, never a script handed
to the operator to run in a terminal.

**Real self-elevation, not a pre-elevated process** (decision record
84, direct correction: "I refuse to keep fixing this with the
terminal I have stated the application does it and if the application
wants root then the application is going to have to ask for it and
run it s root"). `baseline-web.service` is **not** required to run as
root for Drive Administration to work: the operator's own submitted
password (typed into the modal, never a terminal) is piped straight to
a real `sudo -S` - the exact same identity `sudo` would check in any
terminal, just invoked by this process instead of a shell.
`verify_sudo_password` does a cheap, real preflight (`sudo -S -k true`)
so a wrong password is reported cleanly before any real destructive
command is ever attempted; `SudoRunner` then re-uses that same
password for the actual privileged calls this action needs, one
`sudo -S` invocation per real command - never a bare unauthenticated
subprocess call, and the password itself lives only in memory for the
duration of one HTTP request, never logged, never written to disk.

Every destructive action validates its target device via
`physical_device_safety.validate_target_device` first - never a
bare, unvalidated operator-typed path. The drives it may act on are
**restricted** (v0.2 row 55, direct instruction 2026-10-01: "this
can't have any effect outside of the SK hynix"): the SK hynix drives in
`ALLOWED_TARGET_SERIALS`, plus any drive deliberately added with
`enroll_drive` (direct instruction 2026-10-03; `drive_enrollment.py`),
which needs the typed serial to match the drive and a human
confirmation. This replaced an earlier "selectable, never restricted"
design; `allowed_target_serials()` is the one source of the set.

Each `ACTIONS` entry pairs one human-readable description with the
exact callable that runs - the web page's modal renders the same
description this module executes against, so there is never a second,
drifting copy of "what this button actually does."
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import drive_enrollment
import drive_guard
import drive_installer
import hitl
import persist_bind_mounts as pbm
import physical_device_safety as pds
import settings_store
import web_gate

# Real bug found live, 2026-09-29: `build_self_installer` used to
# default `repo_root` to a *hardcoded* `Path("/opt/baseline").parent`
# (`/opt`) - wrong even on its own terms (iso_builder.build_current_iso
# needs `repo_root / "boot"` and `repo_root / "baseline"` to exist
# directly, not two levels up), and `/opt/baseline` doesn't exist at
# all outside a real systemd-deployed install. Derived from this
# file's own real, current location instead - correct by construction
# whether this code is running from `/opt/baseline` in production or
# a dev checkout at any other path, since it always finds itself.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

from repair import Runner


# The two SK hynix drives Baseline is set up with (decision records 45-47): the
# PC601 holding the Proxmox install and the PC401 that is the Baseline drive.
# Direct instruction, 2026-10-01: "this can't have any effect outside of the SK
# hynix". So this is an ENFORCED allowlist, not a pre-selection hint: the picker
# offers only these, and every device action refuses any other drive before it
# runs anything (`perform_action`). It reverses an earlier recorded instruction
# that targets should not be locked to two drives (v0.2 row 55). Matched by
# serial because two drives of one model would otherwise look identical.
ALLOWED_TARGET_SERIALS = frozenset({"MD89N41071210AP4E", "FD01N6557110C271B"})
DEFAULT_TARGET_SERIALS = ALLOWED_TARGET_SERIALS      # older name, same set


def allowed_target_serials() -> frozenset:
    """The SK hynix drives plus the drives deliberately enrolled since (drive_enrollment.py)."""
    return ALLOWED_TARGET_SERIALS | drive_enrollment.enrolled_serials()


# ---------------------------------------------------------------------------
# Real self-elevation (decision record 84) - the web app's own
# mechanism for becoming root for exactly one privileged call, using
# the password the operator just typed into the modal. `executor` is
# always `subprocess.run` in production; tests inject a fake recorder
# so no real `sudo`/password is ever needed to prove the argv shape
# and password-piping are correct.
# ---------------------------------------------------------------------------

def sudo_argv(argv: list) -> list:
    """`-S` reads the password from stdin (never a CLI argument - would
    leak via `ps`/shell history); `-k` forces a genuine fresh prompt
    every call rather than silently reusing sudo's own timestamp cache
    from some unrelated earlier use elsewhere on the machine; `-p ''`
    suppresses sudo's own interactive prompt text, which would
    otherwise end up mixed into captured stdout for no reason here."""
    return ["sudo", "-S", "-k", "-p", "", *argv]


def verify_sudo_password(password: str, *, executor=None) -> bool:
    """A cheap, real preflight: does this password actually authenticate
    this operator via the machine's own real `sudo`? `true` is the
    smallest real command that proves the identity check alone,
    without yet risking any actual privileged action - a wrong
    password is reported cleanly here, before `SudoRunner` ever
    attempts a real destructive call."""
    executor = executor or subprocess.run
    proc = executor(sudo_argv(["true"]), input=(password + "\n").encode(),
                     capture_output=True, timeout=10)
    return proc.returncode == 0


class SudoRunner:
    """A `repair.Runner`-compatible object that re-executes every real
    call through `sudo -S`, using one password supplied at
    construction (the operator's own submission for this one HTTP
    request - never cached, never reused across requests). Only the
    methods this module's own actions actually reach are implemented;
    reads (`read_text`/`path_exists`/`listdir`) stay plain,
    unprivileged calls, since every real path these actions touch
    (`/proc/self/mounts`, `/etc/fstab`, `lsblk` output) is
    world-readable and sudo-wrapping a read would be a pointless,
    strictly riskier no-op."""

    def __init__(self, password: str, *, executor=None):
        self.password = password
        self._executor = executor or subprocess.run

    def _sudo(self, argv: list, *, extra_input: bytes = b"", timeout: int = 30):
        raw = self._executor(sudo_argv(argv), input=(self.password + "\n").encode() + extra_input,
                              capture_output=True, timeout=timeout)
        stdout = raw.stdout.decode(errors="replace") if isinstance(raw.stdout, bytes) else raw.stdout
        stderr = raw.stderr.decode(errors="replace") if isinstance(raw.stderr, bytes) else raw.stderr
        return subprocess.CompletedProcess(argv, raw.returncode, stdout, stderr)

    def run(self, argv: list, timeout: int = 10):
        return self._sudo(argv, timeout=timeout)

    def makedirs(self, path: str) -> None:
        self._sudo(["mkdir", "-p", path])

    def append_text(self, path: str, content: str) -> None:
        self._sudo(["tee", "-a", path], extra_input=content.encode())

    def write_text_atomic(self, path: str, content: str) -> None:
        """Real atomicity via a root-owned temp file + `mv` on the
        same filesystem (atomic rename), not a bare in-place `tee` -
        matches `repair.RealRunner.write_text_atomic`'s own real
        guarantee, just achieved through two real `sudo` calls instead
        of direct Python syscalls this non-root process can't make."""
        tmp = f"{path}.tmp-sudorunner"
        self._sudo(["tee", tmp], extra_input=content.encode())
        self._sudo(["mv", tmp, path])

    def remove(self, path: str) -> None:
        self._sudo(["rm", "-rf", path])

    def read_text(self, path: str) -> str:
        from pathlib import Path
        return Path(path).read_text()

    def path_exists(self, path: str) -> bool:
        from pathlib import Path
        return Path(path).exists()

    def listdir(self, path: str) -> list:
        from pathlib import Path
        p = Path(path)
        return sorted(p.iterdir()) if p.exists() else []

    def as_pds_runner(self) -> "_SudoPdsAdapter":
        """Real bug this closes: `resolve_target`/`wipe_signatures`
        take a *separate* `physical_device_safety.Runner`
        (`run(argv) -> str`, a different, older, simpler shape than
        this class's own `repair.Runner`-style `run(argv, timeout) ->
        CompletedProcess`) - when a caller omitted it, both silently
        fell back to a fresh, real but **unauthenticated**
        `physical_device_safety.Runner()`, so the wipe never actually
        carried this same real root privilege. This adapter shares the
        exact same password/executor so the whole action - validation,
        wipe, and the LVM create calls - runs under one real,
        consistent `sudo` identity, not two different ones."""
        return _SudoPdsAdapter(self)


class _SudoPdsAdapter:
    """Exposes `SudoRunner`'s real `sudo`-piping through
    `physical_device_safety.Runner`'s own interface (`run(argv) ->
    str`, stdout only) - see `SudoRunner.as_pds_runner`.

    Real bug found live (first time `build_self_installer`'s real
    `pds_runner` path was actually exercised against a real request,
    not just `FakeRunner`): this adapter used to implement only `run`,
    but `physical_device_safety.validate_target_device` also calls
    `lstat`/`realpath`/`read_size_file` - crashed with `AttributeError`
    mid-request, which the client sees as a silently broken connection
    ("nothing happened" - no redirect, no banner, because the fetch
    never got a real response to parse). None of those three need
    real privilege (plain filesystem/sysfs reads, the same as
    `physical_device_safety.Runner`'s own unprivileged implementations)
    - delegated to a plain `pds.Runner()` instance rather than
    reimplemented here a second time."""

    def __init__(self, sudo_runner: SudoRunner):
        self._sudo_runner = sudo_runner
        self._plain = pds.Runner()

    def run(self, argv: list) -> str:
        return self._sudo_runner.run(argv, timeout=30).stdout

    def lstat(self, path: str):
        return self._plain.lstat(path)

    def realpath(self, path: str) -> str:
        return self._plain.realpath(path)

    def read_size_file(self, dev_name: str) -> str:
        return self._plain.read_size_file(dev_name)


def pkexec_argv(argv: list) -> list:
    """Direct instruction, 2026-09-29: "Make the application ask for
    the sudo password through Ubuntu best practices... following
    documented methods and policies from the OS provider" - `pkexec`
    is exactly that (the same real mechanism GParted, GNOME Disks,
    and the Software installer all use). Confirmed live on this
    machine: GNOME Shell already runs its own built-in PolicyKit
    authentication agent (no separate agent process, no custom
    `.policy` action file needed - the built-in default
    `org.freedesktop.policykit.exec` action already covers this),
    and a real `pkexec whoami` test genuinely returned `root` after
    the operator authenticated through GNOME's own native dialog.
    Unlike `sudo -S`, no password is ever piped through this
    process's own stdin, sent in any HTTP request, or seen by this
    web app's own code at all - it goes straight to PolicyKit's
    agent, entirely outside the browser."""
    return ["pkexec", *argv]


class PkexecRunner:
    """A `repair.Runner`-compatible object that re-executes every real
    privileged call through `pkexec` (see `pkexec_argv`) - the
    Drive Administration action-authorization mechanism this project
    actually uses now, replacing the HTML-form password field
    `SudoRunner` needed. `SudoRunner`/`verify_sudo_password` remain in
    this module unchanged - `settings_web.SudoPasswordVerifier` (login,
    a different real question: "does this browser session belong to
    someone who knows the password," not "authorize this one
    destructive action") still uses them directly.

    `timeout` defaults generously (300s) - unlike a piped `sudo -S`
    call, this genuinely waits on a human looking at their screen and
    typing into a real dialog, not a fixed subprocess round-trip."""

    def __init__(self, *, executor=None, timeout: int = 300):
        self._executor = executor or subprocess.run
        self._default_timeout = timeout

    def _pkexec(self, argv: list, *, extra_input: bytes = b"", timeout: int | None = None):
        raw = self._executor(pkexec_argv(argv), input=extra_input,
                              capture_output=True, timeout=timeout or self._default_timeout)
        stdout = raw.stdout.decode(errors="replace") if isinstance(raw.stdout, bytes) else raw.stdout
        stderr = raw.stderr.decode(errors="replace") if isinstance(raw.stderr, bytes) else raw.stderr
        return subprocess.CompletedProcess(argv, raw.returncode, stdout, stderr)

    def run(self, argv: list, timeout: int | None = None):
        return self._pkexec(argv, timeout=timeout)

    def makedirs(self, path: str) -> None:
        self._pkexec(["mkdir", "-p", path])

    def append_text(self, path: str, content: str) -> None:
        self._pkexec(["tee", "-a", path], extra_input=content.encode())

    def write_text_atomic(self, path: str, content: str) -> None:
        tmp = f"{path}.tmp-pkexecrunner"
        self._pkexec(["tee", tmp], extra_input=content.encode())
        self._pkexec(["mv", tmp, path])

    def remove(self, path: str) -> None:
        self._pkexec(["rm", "-rf", path])

    def read_text(self, path: str) -> str:
        from pathlib import Path
        return Path(path).read_text()

    def path_exists(self, path: str) -> bool:
        from pathlib import Path
        return Path(path).exists()

    def listdir(self, path: str) -> list:
        from pathlib import Path
        p = Path(path)
        return sorted(p.iterdir()) if p.exists() else []

    def as_pds_runner(self) -> "_PkexecPdsAdapter":
        return _PkexecPdsAdapter(self)


class _PkexecPdsAdapter:
    """Mirrors `_SudoPdsAdapter` for `PkexecRunner` - see its own
    docstring for why `lstat`/`realpath`/`read_size_file` delegate to
    a plain, unprivileged `pds.Runner()` rather than going through
    `pkexec` themselves (none of the three need real privilege)."""

    def __init__(self, pkexec_runner: PkexecRunner):
        self._pkexec_runner = pkexec_runner
        self._plain = pds.Runner()

    def run(self, argv: list) -> str:
        return self._pkexec_runner.run(argv, timeout=self._pkexec_runner._default_timeout).stdout

    def lstat(self, path: str):
        return self._plain.lstat(path)

    def realpath(self, path: str) -> str:
        return self._plain.realpath(path)

    def read_size_file(self, dev_name: str) -> str:
        return self._plain.read_size_file(dev_name)


MIN_TARGET_SIZE_BYTES = 50_000_000_000  # 50GB - excludes small USB sticks/SD cards by construction
PERSISTENCE_VG_NAME = "baseline_persist"


class DriveInventoryError(RuntimeError):
    """A drive or LVM probe failed; its result is not an empty inventory."""


def _run_drive_inventory(runner, argv, label):
    try:
        proc = runner.run(argv, timeout=15)
    except Exception as exc:
        raise DriveInventoryError(f"{label} probe unavailable: {type(exc).__name__}: {exc}") from exc
    if getattr(proc, "returncode", 1) != 0:
        detail = getattr(proc, "stderr", "") or f"exit {proc.returncode}"
        raise DriveInventoryError(f"{label} probe failed: {detail.strip()}")
    output = getattr(proc, "stdout", None)
    if not isinstance(output, str):
        raise DriveInventoryError(f"{label} output unavailable")
    return output


# ---------------------------------------------------------------------------
# Real drive enumeration - lists every candidate device an operator could
# pick, classifies its real physical type, and excludes the machine's
# own boot device by construction (never even shown as a choice).
# ---------------------------------------------------------------------------

def list_candidate_drives_argv() -> list:
    """`-P` (key="value" pairs) rather than plain columns - MODEL
    strings routinely contain spaces ("Samsung SSD 980 PRO with
    Heatsink 2TB"), which a naive whitespace split would misparse into
    the wrong column."""
    return ["lsblk", "-d", "-n", "-P", "-o", "NAME,SIZE,MODEL,TRAN,ROTA,SERIAL,TYPE"]


def parse_lsblk_pairs(text: str) -> list:
    """Parses real `lsblk -P` (key="value" pairs) output into dicts -
    the shared raw parser every `lsblk`-based function in this module
    uses, regardless of which columns were requested."""
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            tokens = shlex.split(line)
            if not tokens or any("=" not in token for token in tokens):
                raise ValueError("missing key/value field")
            pairs = [token.split("=", 1) for token in tokens]
            if any(not key for key, _ in pairs) or len({key for key, _ in pairs}) != len(pairs):
                raise ValueError("empty or duplicate field")
            rows.append(dict(pairs))
        except ValueError as exc:
            raise DriveInventoryError(f"malformed lsblk row: {line!r}: {exc}") from exc
    return rows


def parse_candidate_drives(text: str) -> list:
    """`TYPE=disk` only - excludes partitions/loop/rom devices lsblk's
    own `-d` flag doesn't already filter out on every kernel."""
    return [row for row in parse_lsblk_pairs(text) if row.get("TYPE") == "disk"]


def drive_partition_summary_argv() -> list:
    """`-b` for real byte counts (not human-rounded strings), so
    aggregating used space across a drive's partitions is exact, not
    reparsed from "1.8T"-style strings."""
    return ["lsblk", "-P", "-b", "-o", "NAME,TYPE,FSTYPE,FSUSED,FSSIZE,MOUNTPOINT,PKNAME"]


def _format_bytes(n: float) -> str:
    """Simple binary-prefix formatting for a summary line - matches
    lsblk's own SIZE column convention (GiB/TiB), not meant to be
    exact to the byte in the rendered text."""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if n < 1024 or unit == "PiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"  # pragma: no cover - unreachable for any real drive size


def _partition_summary_from_rows(rows: list, drive_name: str) -> dict:
    """The actual computation, pure - shared by `summarize_drive_
    partitions` (one real `lsblk` call for a single drive) and
    `list_candidate_drives` (one real `lsblk` call for the whole
    system, reused for every candidate drive instead of re-querying
    once per drive). Never fabricates a used-space number for an
    unmounted filesystem, a raw LVM PV, or a bare partition table with
    no filesystem at all - reports those honestly as not contributing
    to "used", rather than guessing 0 or skipping the drive's real
    partition count."""
    own_row = next((r for r in rows if r.get("NAME") == drive_name), None)
    children = [r for r in rows if r.get("PKNAME") == drive_name]
    partition_count = sum(1 for r in children if r.get("TYPE") == "part")

    # A drive is either a bare disk with its own filesystem directly on
    # it (no partition table at all, e.g. this project's own rebuilt
    # LVM PVs or a whole-disk ext4 drive) or has real partitions - real
    # "used" space only ever comes from a segment that is genuinely
    # mounted right now, on either shape.
    relevant = ([own_row] if own_row and not children else children)
    mounted = [r for r in relevant if r.get("MOUNTPOINT") and r.get("FSUSED")]
    if not mounted:
        usage_text = "not mounted"
    else:
        used = sum(int(r["FSUSED"]) for r in mounted)
        total = sum(int(r["FSSIZE"]) for r in mounted if r.get("FSSIZE"))
        usage_text = f"{_format_bytes(used)} used of {_format_bytes(total)}" if total else _format_bytes(used) + " used"
    return {"partition_count": partition_count, "usage_text": usage_text}


def summarize_drive_partitions(runner: Runner, drive_name: str) -> dict:
    """Real partition count and real, mounted-only used/total bytes
    for one real drive (`drive_name`, e.g. `"sdb"` - no `/dev/` prefix,
    matching `lsblk`'s own `NAME`/`PKNAME` convention)."""
    output = _run_drive_inventory(runner, drive_partition_summary_argv(), "lsblk partition summary")
    return _partition_summary_from_rows(parse_lsblk_pairs(output), drive_name)


def classify_drive_type(*, tran: str, rota: str, model: str, usb_bridge_model: str | None = None) -> str:
    """Real classification, not a guess from the transport alone.

    Real finding this project's own target drives exposed: a USB-NVMe
    bridge chip reports `ROTA=1` (rotational) for a genuinely solid-
    state drive - `ROTA` is only trustworthy on a *direct* (non-USB)
    transport. Worse, a bridge-chip-attached drive's own marketing
    model string routinely gives no NVMe hint at all (a real,
    confirmed-NVMe "Samsung SSD 980 PRO with Heatsink 2TB" says
    nothing about NVMe there) - direct correction: "This is not an SSD
    drive is NVME."

    So `usb_bridge_model` (the USB bridge *chip's* own reported model,
    `physical_device_safety.get_usb_bridge_model` - a real, non-
    privileged signal) is checked first and is authoritative when
    present: this project has three independently confirmed-real NVMe
    drives, all reporting a Realtek `RTL92xx` bridge
    (`RTL9220DP_PCIe0`/`RTL9220DP_PCIe1`/`RTL9210B-CG`) - a real
    `RTL92` bridge, or any bridge model that says "PCIe" itself, means
    NVMe regardless of what the drive's own marketing string claims.
    A consumer HDD/SSD USB enclosure (Seagate "Backup+_Hub_BK", WD
    "Elements_25A3" in this project's own real hardware) reports its
    own brand there instead - no false NVMe signal.

    Only when no bridge-chip signal is available does this fall back
    to the model string, then (off USB only) the kernel's own `ROTA`
    flag, and finally an honest "USB" when a USB-attached device gives
    no real hint either way at all - never a guessed "HDD" or "SSD"."""
    bridge_lower = (usb_bridge_model or "").lower()
    if "pcie" in bridge_lower or bridge_lower.startswith("rtl92"):
        return "NVMe"
    model_lower = (model or "").lower()
    if tran == "nvme" or "nvme" in model_lower:
        return "NVMe"
    if "ssd" in model_lower:
        return "SSD"
    if tran == "usb":
        return "USB"
    if rota == "1":
        return "HDD"
    if rota == "0":
        return "SSD"
    return "Other"


def list_candidate_drives(runner: Runner, *, pds_runner=None) -> list:
    """Every real, non-boot block device at least `MIN_TARGET_SIZE_BYTES`
    - the actual candidate list an operator picks from. The machine's
    own boot device is excluded by construction (compared by real
    serial, via `physical_device_safety.get_boot_device_serial` - the
    same self-detection `validate_target_device` itself relies on, not
    re-derived here), so it can never even appear as a choice, let
    alone be selected."""
    pds_runner = pds_runner or pds.Runner()
    candidate_output = _run_drive_inventory(runner, list_candidate_drives_argv(), "candidate drive list")
    # One real, whole-system lsblk call for every candidate drive's
    # partition count/usage, not one re-query per drive.
    tree_output = _run_drive_inventory(runner, drive_partition_summary_argv(), "drive partition summary")
    tree_rows = parse_lsblk_pairs(tree_output)
    boot_serial = pds.get_boot_device_serial(pds_runner)
    if not isinstance(boot_serial, str) or not boot_serial.strip():
        raise DriveInventoryError("machine boot-drive identity unavailable; candidate drives cannot be safely listed")
    allowed = allowed_target_serials()
    drives = []
    for row in parse_candidate_drives(candidate_output):
        name = row.get("NAME", "")
        serial = row.get("SERIAL") or None
        if not name or (boot_serial is not None and serial == boot_serial):
            continue
        if serial not in allowed:
            continue      # never offered, and never probed: not an SK hynix or enrolled drive
        path = f"/dev/{name}"
        tran = row.get("TRAN", "")
        # Only a USB-attached device can sit behind a bridge chip -
        # skip the extra real query entirely for a direct SATA/NVMe
        # device, where this signal never applies anyway.
        usb_bridge_model = pds.get_usb_bridge_model(pds_runner, path) if tran == "usb" else None
        summary = _partition_summary_from_rows(tree_rows, name)
        baseline_status = detect_baseline_drive(runner, path)
        drives.append({
            "path": path,
            "serial": serial,
            "model": row.get("MODEL") or "Unknown model",
            "size": row.get("SIZE") or "?",
            "drive_type": classify_drive_type(tran=tran, rota=row.get("ROTA", ""),
                                               model=row.get("MODEL", ""), usb_bridge_model=usb_bridge_model),
            "is_default": serial in DEFAULT_TARGET_SERIALS,
            "partition_count": summary["partition_count"],
            "usage_text": summary["usage_text"],
            **baseline_status,
        })
    # Direct instruction, 2026-09-29: any real Baseline-installed drive
    # goes to the top of the list, in its own "Baseline Installed"
    # group - a stable sort so the real, already-established ordering
    # among the rest (and among Baseline drives themselves) is
    # preserved, not scrambled.
    drives.sort(key=lambda d: 0 if d["is_baseline_drive"] else 1)
    return drives


def list_enrollable_drives(runner: Runner, *, pds_runner=None) -> list:
    """The non-boot drives that are not yet allowed and report a serial - what an operator may enroll.

    Only the one whole-system `lsblk -d` listing is read (the same listing `list_candidate_drives` already reads,
    which includes these drives anyway); nothing else about them is probed - no partitions, no volume groups - until
    a person enrolls one. A drive that reports no serial cannot be enrolled: the serial is its identity."""
    pds_runner = pds_runner or pds.Runner()
    output = _run_drive_inventory(runner, list_candidate_drives_argv(), "enrollable drive list")
    boot_serial = pds.get_boot_device_serial(pds_runner)
    if not isinstance(boot_serial, str) or not boot_serial.strip():
        raise DriveInventoryError("machine boot-drive identity unavailable; enrollment candidates cannot be safely listed")
    allowed = allowed_target_serials()
    drives = []
    for row in parse_candidate_drives(output):
        serial = row.get("SERIAL") or ""
        if not row.get("NAME") or not serial or serial == boot_serial or serial in allowed:
            continue
        drives.append({"path": f"/dev/{row['NAME']}", "serial": serial,
                       "model": row.get("MODEL") or "Unknown model", "size": row.get("SIZE") or "?"})
    return drives


def detect_baseline_drive(runner: Runner, device_path: str) -> dict:
    """Real, per-drive Baseline-install status (direct instruction,
    2026-09-29): does this specific drive have its own real LVM volume
    group, and if so, which of the real Baseline volumes actually
    exist on it? `is_baseline_drive` is True the moment *any* real
    Baseline volume is found there (a genuinely partial, in-progress
    install is still "a Baseline drive," not nothing) - `missing_
    baseline_volumes` lists the real, individually-checkable gaps
    `repair_scan_and_fix` would close. A drive with no real volume
    group at all (`find_vg_for_device` returns None) is honestly
    reported as not a Baseline drive, with no missing-volumes list -
    there's no VG yet to be missing anything *from*."""
    vg_name = find_vg_for_device(runner, device_path)
    if vg_name is None:
        return {"is_baseline_drive": False, "vg_name": None, "missing_baseline_volumes": []}
    detection = drive_installer.detect_existing_baseline_install(runner, vg_name=vg_name)
    if detection.get("error"):
        raise DriveInventoryError(f"Baseline volume inventory failed for {vg_name}: {detection['error']}")
    return {
        "is_baseline_drive": bool(detection["found_volumes"]),
        "vg_name": vg_name,
        "missing_baseline_volumes": detection["missing_volumes"] if detection["found_volumes"] else [],
    }


@dataclass
class ActionResult:
    ok: bool
    detail: str


def reread_partition_table_argv(device_path: str) -> list:
    """Real bug this closes: `wipefs -a` clears the on-disk signature
    bytes, but the kernel can keep serving its own already-cached view
    of the old partition table (and any partition device nodes it
    created from it) until told to re-read - `pvcreate` then correctly
    refuses with "device is partitioned" even though the disk itself
    no longer has one. `--rereadpt` forces that re-read; needs real
    root (`BLKRRPART` requires `CAP_SYS_ADMIN`), same as the wipe and
    create steps around it."""
    return ["blockdev", "--rereadpt", device_path]


def pvcreate_argv(device_path: str) -> list:
    return ["pvcreate", "-ff", "-y", device_path]


def vgcreate_argv(vg_name: str, device_path: str) -> list:
    return ["vgcreate", vg_name, device_path]


def resolve_target(device_path: str, *, pds_runner=None) -> dict:
    """Real validation via physical_device_safety - refuses (raises
    PhysicalDeviceSafetyError) unless the real, currently-attached
    device at `device_path` is a genuine, non-boot block device of at
    least `MIN_TARGET_SIZE_BYTES` AND its serial is one of
    `allowed_target_serials()`. Any other drive, however real and large, is
    refused (direct instruction, 2026-10-01) until it is enrolled."""
    return pds.validate_target_device(device_path, expected_serial=sorted(allowed_target_serials()),
                                      min_size_bytes=MIN_TARGET_SIZE_BYTES, runner=pds_runner)


def rebuild_persistence_lvm(runner: Runner, *, device_path: str, pds_runner=None) -> ActionResult:
    """The highest-risk action: wipes `device_path`'s existing
    partition signatures and rebuilds it as an empty LVM volume group
    (`PERSISTENCE_VG_NAME`). Real validation first via `resolve_target`
    - refuses outright unless the real attached device at that path is
    a genuine, non-boot, sufficiently large block device; `device_path`
    is operator-selected (see `list_candidate_drives`), never assumed.

    `pds_runner` defaults to `runner.as_pds_runner()` when `runner`
    supports it (a real `SudoRunner`) - real bug found live (decision
    record 84's own follow-up): omitting this previously fell back to
    a fresh, unauthenticated `physical_device_safety.Runner()`, so
    validation and the wipe step never actually shared the operator's
    real, just-verified `sudo` identity with the LVM create calls that
    came right after them."""
    if pds_runner is None and hasattr(runner, "as_pds_runner"):
        pds_runner = runner.as_pds_runner()
    try:
        validated = resolve_target(device_path, pds_runner=pds_runner)
    except pds.PhysicalDeviceSafetyError as exc:
        return ActionResult(False, f"refused: {exc}")

    try:
        drive_guard.require_may_format(validated["path"], run=_lsblk_run(pds_runner))
    except drive_guard.DataProtectionError as exc:
        return ActionResult(False, str(exc))
    pds.wipe_signatures(validated, runner=pds_runner)

    # Real bug this closes: `wipefs -a` clears the on-disk signature
    # bytes, but the kernel can keep serving its own already-cached
    # partition table until told to re-read it - `pvcreate` then
    # refuses with "device is partitioned" even though the disk no
    # longer has one on it. Best-effort: some kernels/devices report a
    # harmless error here even when the re-read genuinely succeeded,
    # so this is never treated as fatal on its own - `pvcreate`'s own
    # real result right after it is what actually decides success.
    runner.run(reread_partition_table_argv(validated["path"]), timeout=15)

    pv_proc = runner.run(pvcreate_argv(validated["path"]), timeout=60)
    if pv_proc.returncode != 0:
        return ActionResult(False, f"pvcreate failed: {pv_proc.stderr.strip()}")

    vg_proc = runner.run(vgcreate_argv(PERSISTENCE_VG_NAME, validated["path"]), timeout=60)
    if vg_proc.returncode != 0:
        return ActionResult(False, f"vgcreate failed: {vg_proc.stderr.strip()}")

    return ActionResult(True, f"{validated['path']} rebuilt as LVM volume group {PERSISTENCE_VG_NAME!r}")


def create_baseline_volumes(runner: Runner, *, vg_name: str = PERSISTENCE_VG_NAME,
                             personas: tuple = drive_installer.DEFAULT_PERSONAS) -> ActionResult:
    """Reuses `drive_installer.ensure_baseline_volumes` directly - the
    real, already-tested orchestration (adaptive sizing, per-volume
    mount options, fstab entries) for creating BASELINE/INSTALLER_CACHE
    /SESSION_TEMP plus one USER_<PERSONA> volume per
    persona. Not reimplemented here."""
    plan = drive_installer.ensure_baseline_volumes(runner, vg_name=vg_name, personas=personas)
    failed = [name for name, result in plan.items() if not result.ok]
    if failed:
        return ActionResult(False, f"volume(s) failed: {', '.join(failed)}")
    return ActionResult(True, f"real volumes ensured on {vg_name!r} for personas {personas}")


def switch_persona(runner: Runner, *, to_persona: str) -> ActionResult:
    """Reuses `persist_bind_mounts.switch_active_persona` directly.
    `credential_ok=True` is safe here specifically because this
    module's own caller (the web route) already required a real,
    live `admin_elevation` ticket before ever reaching this function -
    the credential proof already happened one layer up, not skipped."""
    result = pbm.switch_active_persona(runner, to_persona=to_persona, credential_ok=True)
    return ActionResult(result.applied, result.detail)


def apply_volume_mode(runner: Runner, *, label: str) -> ActionResult:
    """Real enforcement of settings_store.py's `volumes.*_mode`
    setting (decision record 80 built the storage; this is the
    previously-deferred "real application" half). Reads the live
    setting, maps it to a real mount-option string, and remounts the
    already-mounted shared volume with it. Refuses cleanly if the
    volume isn't currently mounted - remounting something not mounted
    is meaningless, not silently treated as success."""
    key_by_label = {
        "BASELINE": "baseline_mode", "INSTALLER_CACHE": "installer_cache_mode",
        "SESSION_TEMP": "session_temp_mode",
    }
    if label not in key_by_label:
        return ActionResult(False, f"{label!r} is not a shared volume with a configurable mode")
    mode = settings_store.get_setting("volumes", key_by_label[label])
    mountpoint = next((mp for _, _, _, lbl, mp in drive_installer.SHARED_VOLUMES if lbl == label), None)
    if mountpoint is None or not pbm.is_mounted(runner, mountpoint):
        return ActionResult(False, f"{label} is not currently mounted - nothing to remount")
    # "write-only" has no real Linux mount-option equivalent (per
    # drive_installer.settings_store's own storage-only disclaimer,
    # decision record 80) - mapped to the closest real, honest
    # approximation (read-write) rather than silently misrepresenting
    # an unenforceable mode as applied.
    options = {"read-only": "ro", "read-write": "rw", "write-only": "rw"}.get(mode, "rw")
    proc = runner.run(drive_installer.remount_argv(mountpoint, options), timeout=15)
    if proc.returncode != 0:
        return ActionResult(False, f"remount failed: {proc.stderr.strip()}")
    return ActionResult(True, f"{label} remounted {options} (setting: {mode!r})")


def install_drive(runner, *, device_path, pds_runner=None, vg_name: str = PERSISTENCE_VG_NAME,
                   personas: tuple = drive_installer.DEFAULT_PERSONAS) -> ActionResult:
    """The real "Install" action - direct instruction: the operator
    should see one Install button, not two separate steps left for
    them to run in order. Wipes+rebuilds the selected drive as an LVM
    volume group, then creates the real BASELINE/INSTALLER_CACHE/
    SESSION_TEMP and per-persona volumes on it. Stops at the first
    failure - never attempts to create volumes on a volume group that
    was never actually created."""
    rebuild_result = rebuild_persistence_lvm(runner, device_path=device_path, pds_runner=pds_runner)
    if not rebuild_result.ok:
        return rebuild_result
    volumes_result = create_baseline_volumes(runner, vg_name=vg_name, personas=personas)
    if not volumes_result.ok:
        return ActionResult(False, f"{rebuild_result.detail}; but {volumes_result.detail}")
    return ActionResult(True, f"{rebuild_result.detail}; {volumes_result.detail}")


def _cache_package_directory(runner, root: str, identity: dict) -> str:
    """Require the package archive directory to remain on the cache filesystem."""
    path = f"{root}/packages"
    resolved = runner.run(["readlink", "-e", path], timeout=10)
    if resolved.returncode != 0 or resolved.stdout.strip() != path:
        raise RuntimeError("INSTALLER_CACHE/packages is missing, redirected, or not canonical")
    mounted = runner.run(["findmnt", "--json", "--target", path, "-o", "TARGET,UUID"], timeout=10)
    try:
        filesystems = json.loads(mounted.stdout)["filesystems"]
    except (ValueError, KeyError, TypeError):
        filesystems = []
    if (mounted.returncode != 0 or len(filesystems) != 1
            or filesystems[0].get("uuid") != identity.get("uuid")
            or filesystems[0].get("target") != root):
        raise RuntimeError("INSTALLER_CACHE/packages is not on the identified cache filesystem")
    return path


def check_cache_updates(runner, root: str = "/mnt/INSTALLER_CACHE") -> list:
    """Find newer APT artifacts already represented in INSTALLER_CACHE.

    APT refreshes its signed repository indexes, then its candidate version is
    compared with each cached Debian archive using dpkg's version semantics.
    Only package/firmware artifacts are candidates here; pinned ISOs, OCI
    images, and reviewed VM scripts keep their independent publisher workflows.
    """
    import installer_cache as ic
    import installer_sources

    root = str(root)
    identity = installer_sources.cache_identity(runner, root)
    package_dir = _cache_package_directory(runner, root, identity)
    refreshed = runner.run([
        "apt-get", "-o", "Acquire::AllowInsecureRepositories=false",
        "-o", "Acquire::AllowDowngradeToInsecureRepositories=false",
        "-o", "APT::Get::AllowUnauthenticated=false", "update",
    ], timeout=600)
    if refreshed.returncode != 0:
        detail = (refreshed.stderr or refreshed.stdout or "no diagnostic output").strip()
        raise RuntimeError(f"APT repository index refresh failed: {detail}")

    try:
        cached_files = ic._listdir_with_sizes(runner, package_dir)
        catalog = ic.catalog()
    except Exception as exc:
        raise RuntimeError(f"could not inspect cached package artifacts: {exc}") from exc

    updates = []
    for entry in catalog:
        if entry.kind not in (ic.KIND_PACKAGE, ic.KIND_FIRMWARE):
            continue
        matches = [(name, size) for name, size in cached_files if ic._matches(entry, name)]
        if not matches:
            continue

        versions = []
        for name, _size in matches:
            path = f"{package_dir}/{name}"
            package = runner.run(["dpkg-deb", "--field", path, "Package", "Version", "Architecture"], timeout=30)
            if package.returncode != 0:
                raise RuntimeError(f"cached package metadata failed for {name}: {package.stderr.strip()}")
            fields = package.stdout.splitlines()
            if len(fields) != 3 or fields[0] != entry.entry_id or not fields[1] or not fields[2]:
                raise RuntimeError(f"cached package identity/version is malformed for {name}")
            versions.append((fields[1], fields[2], path))

        newest = versions[0]
        for candidate in versions[1:]:
            comparison = runner.run(["dpkg", "--compare-versions", candidate[0], "gt", newest[0]], timeout=10)
            if comparison.returncode == 0:
                newest = candidate
            elif comparison.returncode != 1:
                raise RuntimeError(f"dpkg could not compare cached versions for {entry.entry_id}")

        current_version, architecture, cached_path = newest
        policy = runner.run(["apt-cache", "policy", f"{entry.entry_id}:{architecture}"], timeout=30)
        if policy.returncode != 0:
            raise RuntimeError(f"APT candidate lookup failed for {entry.entry_id}:{architecture}: {policy.stderr.strip()}")
        candidate_lines = [line.split(":", 1)[1].strip() for line in policy.stdout.splitlines()
                           if line.strip().startswith("Candidate:")]
        if len(candidate_lines) != 1 or not candidate_lines[0] or candidate_lines[0] == "(none)":
            raise RuntimeError(f"APT has no unambiguous candidate for {entry.entry_id}:{architecture}")
        candidate_version = candidate_lines[0]
        comparison = runner.run(["dpkg", "--compare-versions", candidate_version, "gt", current_version], timeout=10)
        if comparison.returncode == 0:
            updates.append({"package": entry.entry_id, "architecture": architecture,
                            "current_version": current_version, "candidate_version": candidate_version,
                            "cached_path": cached_path})
        elif comparison.returncode != 1:
            raise RuntimeError(f"dpkg could not compare APT and cached versions for {entry.entry_id}")
    return updates


def update_selected(runner, *, selected: list, **params) -> ActionResult:
    """Refresh newer cached .deb archives without installing them on the host."""
    if not selected:
        return ActionResult(False, "no volumes selected")
    if set(selected) != {"INSTALLER_CACHE"}:
        return ActionResult(False, "select only INSTALLER_CACHE; other volumes do not store updateable package artifacts")
    import installer_cache as ic
    import installer_sources

    root = ic.DEFAULT_CACHE_ROOT
    try:
        initial_identity = installer_sources.cache_identity(runner, root)
        package_dir = _cache_package_directory(runner, root, initial_identity)
        updates = check_cache_updates(runner)
        if not updates:
            final_identity = installer_sources.cache_identity(runner, root)
            if final_identity != initial_identity:
                return ActionResult(False, "INSTALLER_CACHE identity changed during the update check")
            return ActionResult(True, "APT indexes refreshed; no newer versions of cached package artifacts were found")

        # APT verifies archive hashes against its signed repository metadata.
        # Direct its archive store to the identified cache volume and use
        # download-only mode so no host package is installed or upgraded.
        package_dir = f"{root}/{ic.SUBDIR[ic.KIND_PACKAGE]}"
        requested = [
            (f"{item['package']}={item['candidate_version']}" if item["architecture"] == "all"
             else f"{item['package']}:{item['architecture']}={item['candidate_version']}")
            for item in updates
        ]
        downloaded = runner.run([
            "apt-get", "-o", f"Dir::Cache::archives={package_dir}",
            "-o", f"Dir::Cache::archives::partial={package_dir}/partial",
            "-o", "Acquire::AllowInsecureRepositories=false",
            "-o", "Acquire::AllowDowngradeToInsecureRepositories=false",
            "-o", "APT::Get::AllowUnauthenticated=false",
            "--download-only", "--reinstall", "--yes", "--no-install-recommends",
            "install", *requested,
        ], timeout=1800)
        if downloaded.returncode != 0:
            detail = (downloaded.stderr or downloaded.stdout or "no diagnostic output").strip()
            return ActionResult(False, f"APT archive download failed; no update claimed: {detail}")

        final_identity = installer_sources.cache_identity(runner, root)
        if final_identity != initial_identity:
            return ActionResult(False, "INSTALLER_CACHE identity changed during archive download")
        package_dir = _cache_package_directory(runner, root, final_identity)
        cached_files = ic._listdir_with_sizes(runner, package_dir)
        verified = []
        for item in updates:
            found = False
            for name, _size in cached_files:
                if not name.endswith(".deb") or not name.lower().startswith(item["package"].lower() + "_"):
                    continue
                path = f"{package_dir}/{name}"
                result = runner.run(["dpkg-deb", "--field", path, "Package", "Version", "Architecture"], timeout=30)
                fields = result.stdout.splitlines() if result.returncode == 0 else []
                if fields == [item["package"], item["candidate_version"], item["architecture"]]:
                    found = True
                    break
            if not found:
                return ActionResult(False, f"downloaded {item['package']} archive did not pass package/version verification")
            verified.append(f"{item['package']} {item['current_version']} -> {item['candidate_version']}")
        return ActionResult(True, "Verified in INSTALLER_CACHE: " + ", ".join(verified))
    except Exception as exc:
        return ActionResult(False, f"cache update failed: {type(exc).__name__}: {exc}")


def find_vg_for_device(runner, device_path: str) -> str | None:
    """Real PV -> VG lookup. `device_path` is usually the whole disk
    (`/dev/sdd`), but `pvcreate` is commonly run against one of its
    partitions (`/dev/sdd3`) - matched by prefix, not exact equality,
    since that's the real relationship between a disk and its own PV.

    `sudo -n` (real bug found live, 2026-09-29): called during plain
    page rendering (an unprivileged runner - no destructive action, no
    pkexec dialog involved) as well as during the real `repair`
    action - a bare `pvs` fails with "Permission denied" for a plain
    user on this real machine, which this function's own `returncode
    != 0` check then silently reports as "no VG found," indistinguish-
    able from a genuinely-empty result. This machine's own sudoers
    file has `pvs` specifically passwordless (confirmed live via `sudo
    -n -l`) - `-n` fails cleanly rather than hanging on any machine
    where that isn't configured."""
    output = _run_drive_inventory(runner, ["sudo", "-n", "pvs", "--noheadings", "-o", "pv_name,vg_name"], "LVM PV/VG list")
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2:
            raise DriveInventoryError(f"malformed LVM PV/VG row: {line!r}")
        if parts[0].startswith(device_path):
            return parts[1]
    return None


def repair_scan_and_fix(runner, *, device_path, **params) -> ActionResult:
    """The real, per-drive Repair action (direct instruction,
    2026-09-29): scans this drive's own real volume group for missing
    Baseline volumes and creates only what's actually missing - reuses
    `drive_installer.ensure_baseline_volumes`'s own idempotent
    guarantee (never reformats or touches a volume that already
    exists), rather than a bespoke "fix" path of its own. Each missing
    volume this finds is the same real, individually-listable
    validation failure the drive card itself shows."""
    try:
        vg_name = find_vg_for_device(runner, device_path)
    except DriveInventoryError as exc:
        return ActionResult(False, f"drive/LVM inventory failed; repair not attempted: {exc}")
    if vg_name is None:
        return ActionResult(False, f"{device_path} has no real LVM volume group - nothing to repair")
    detection = drive_installer.detect_existing_baseline_install(runner, vg_name=vg_name)
    if detection["has_existing_install"]:
        return ActionResult(True, f"{vg_name}: every Baseline volume already present - nothing to repair")
    plan = drive_installer.ensure_baseline_volumes(runner, vg_name=vg_name)
    failed = [label for label, result in plan.items() if not result.ok]
    fixed = [label for label, result in plan.items() if result.ok and result.created]
    if failed:
        return ActionResult(False, f"repair on {vg_name} still failing: {', '.join(failed)}")
    return ActionResult(True, f"{vg_name} repaired - created {', '.join(fixed) if fixed else '(nothing needed creating)'}")


def mount_logical_volume(runner, *, device_path, lv_name="root", mountpoint=None,
                          on_progress=None, **params) -> ActionResult:
    """Real, discoverable "mount an existing logical volume for
    inspection" action (direct instruction, 2026-09-29: "The
    application has to handle not manual scripts nobody will
    remember"). Activates the selected drive's own real volume group,
    then mounts the named logical volume read-write at a real,
    predictable location under `/mnt` - the exact two real commands
    (`vgchange -ay`, `mount`) that would otherwise have to be
    remembered and re-typed by hand every single time. Read-write by
    design (direct instruction) - genuinely mounts, not a dry run."""
    progress = on_progress or (lambda line: None)
    try:
        _check_lv_name(lv_name)
        if mountpoint is not None:
            _check_mountpoint(mountpoint)
    except ValueError as exc:
        return ActionResult(False, f"refused: invalid parameter: {exc}")
    try:
        vg_name = find_vg_for_device(runner, device_path)
    except DriveInventoryError as exc:
        return ActionResult(False, f"drive/LVM inventory failed; mount not attempted: {exc}")
    if vg_name is None:
        return ActionResult(False, f"{device_path} has no real LVM volume group - nothing to mount")
    progress(f"Activating volume group {vg_name}...")
    activate = runner.run(["vgchange", "-ay", vg_name])
    if activate.returncode != 0:
        return ActionResult(False, f"activating {vg_name} failed: {activate.stderr.strip()}")
    lv_path = f"/dev/{vg_name}/{lv_name}"
    if not runner.path_exists(lv_path):
        return ActionResult(False, f"{lv_path} does not exist in {vg_name}")
    target = mountpoint or f"/mnt/{vg_name}-{lv_name}-inspect"
    progress(f"Creating mountpoint {target}...")
    runner.makedirs(target)
    progress(f"Mounting {lv_path} read-write at {target}...")
    result = runner.run(["mount", "-o", "rw", lv_path, target])
    if result.returncode != 0:
        return ActionResult(False, f"mounting {lv_path} at {target} failed: {result.stderr.strip()}")
    return ActionResult(True, f"{lv_path} mounted read-write at {target}")


def unmount_logical_volume(runner, *, device_path, lv_name="root", mountpoint=None,
                            on_progress=None, **params) -> ActionResult:
    """The real counterpart to `mount_logical_volume` - a discoverable
    button, not a one-off `umount` a human has to remember to run
    later. Refuses cleanly (never a fake success) if the target isn't
    actually mounted."""
    progress = on_progress or (lambda line: None)
    try:
        _check_lv_name(lv_name)
        if mountpoint is not None:
            _check_mountpoint(mountpoint)
    except ValueError as exc:
        return ActionResult(False, f"refused: invalid parameter: {exc}")
    try:
        vg_name = find_vg_for_device(runner, device_path)
    except DriveInventoryError as exc:
        return ActionResult(False, f"drive/LVM inventory failed; unmount not attempted: {exc}")
    if vg_name is None:
        return ActionResult(False, f"{device_path} has no real LVM volume group - nothing to unmount")
    target = mountpoint or f"/mnt/{vg_name}-{lv_name}-inspect"
    progress(f"Unmounting {target}...")
    result = runner.run(["umount", target])
    if result.returncode != 0:
        return ActionResult(False, f"unmounting {target} failed: {result.stderr.strip()}")
    return ActionResult(True, f"{target} unmounted")


def unmount_mounted_partition(runner, *, device_path, expected_serial, partition_mountpoint,
                              on_progress=None, **params) -> ActionResult:
    """Unmount a mounted partition only after proving it belongs to the selected serial."""
    try:
        _check_partition_mountpoint(partition_mountpoint)
        _check_expected_serial(expected_serial)
    except ValueError as exc:
        return ActionResult(False, f"refused: invalid parameter: {exc}")
    progress = on_progress or (lambda line: None)
    mounted = runner.run(["findmnt", "--noheadings", "--output", "SOURCE", "--target", partition_mountpoint])
    source = mounted.stdout.strip() if mounted.returncode == 0 else ""
    if not source.startswith("/dev/") or "\n" in source:
        return ActionResult(False, f"refused: {partition_mountpoint} is not a mounted block-device partition")
    ownership = runner.run(["lsblk", "--noheadings", "--output", "PKNAME", "--", source])
    identity = runner.run(["udevadm", "info", "--query=property", f"--name={device_path}"])
    parent_names = ownership.stdout.split()
    serials = [line.partition("=")[2] for line in identity.stdout.splitlines()
              if line.startswith("ID_SERIAL_SHORT=")]
    expected_parent = os.path.basename(device_path)
    if (ownership.returncode != 0 or identity.returncode != 0 or len(parent_names) != 1
            or parent_names[0] != expected_parent or serials != [expected_serial]):
        return ActionResult(False, f"refused: mounted source {source} is not proven to belong to selected drive serial {expected_serial}")
    progress(f"Unmounting {partition_mountpoint} from {source} on serial {expected_serial}...")
    result = runner.run(["umount", "--", partition_mountpoint])
    if result.returncode != 0:
        return ActionResult(False, f"unmounting {partition_mountpoint} failed: {result.stderr.strip()}")
    return ActionResult(True, f"{partition_mountpoint} unmounted from {source} on serial {expected_serial}")


def build_self_installer(runner, *, device_path, pds_runner=None, on_progress=None, **params) -> ActionResult:
    """The real "make this drive prove itself as a self installer"
    action (decision record 85) - direct instruction: do this through
    the web application, not a bare CLI invocation. Composes
    self_installer.build_and_write_self_installer's already-tested
    pipeline (real acquire -> real prepare-iso --fetch-from http ->
    real self-contained-ISO remaster -> real QEMU launch against the
    real device path).

    Unlike `rebuild_persistence_lvm`, none of this pipeline's five
    stages (acquire/prepare-iso/iso-build/QEMU-launch, plus the
    read-only device validation itself) needs real root - `udevadm`/
    `lsblk` device queries are unprivileged reads, and the final QEMU
    step only needs `disk`-group-level read/write on the device node,
    a different privilege model than the LVM wipe/create calls
    `rebuild_persistence_lvm` needs `SudoRunner` for.

    Real bug found live, 2026-09-29: `pds_runner` used to default to
    `runner.as_pds_runner()` "for consistency" whenever available -
    correct for `SudoRunner` (whose own adapter already delegates
    reads to a plain, unprivileged `pds.Runner()` internally), but
    wrong for `PkexecRunner` (decision record 103), whose adapter
    wraps *every* call, including plain reads, in a real `pkexec`
    authentication prompt. Since this action's own validation reads
    never needed privilege in the first place, every one of them -
    `udevadm info` for the target, then `findmnt`/`lsblk`/`udevadm`
    again for the boot-device self-check - each spawned its own
    separate, genuinely blocking authentication dialog, one after
    another, with nothing to tell the operator why device validation
    of all things needed their password. `pds_runner` now always
    defaults to a plain `pds.Runner()` directly - never derived from
    `runner` at all - since this action never has a real reason to
    authenticate its own reads, regardless of which kind of runner it
    was given.

    **The only input this action actually needs is `device_path`**
    (decision record 86, direct instruction: "I will never fill in a
    serial number... everything must be selectable without a
    keyboard") - the web page's drive-picker already supplies that with
    no typing. Every other value comes from `settings_store.py`'s
    "self_installer" group, itself only ever set via the Admin tab's
    dropdowns (never free text - `settings_store.set_setting` refuses
    anything outside a setting's own `options`), or is derived/
    generated for real inside `self_installer.py` itself (hardware
    serial from the selected device, a fresh TLS cert, the QEMU SLIRP
    gateway as `server_host`, the cached source ISO). A caller MAY still
    pass any of these explicitly via `params` as a human-override escape
    hatch - the web UI simply never exposes a text field to do so.

    **Honest limitation carried through from self_installer.py: this
    action's own success means "the real install was launched", never
    "the install finished correctly."** A human or vision-capable agent
    must still confirm the final screendump before the drive is
    actually proven."""
    import self_installer as si
    import drive_setup_acquire as dsa
    import drive_setup_answer as dsan
    import drive_setup_install as dsi
    import iso_builder as ib
    import settings_store
    import dependencies as dep

    pds_runner = pds_runner or pds.Runner()

    # Decision record 88, direct instruction: dependencies "should be
    # predefined and validated before install begins." Only a LOUD
    # failure refuses here - a SILENT one (e.g. a stale fqdn preset) is
    # still recorded for dump_configuration_snapshot/troubleshooting,
    # but was never meant to block an install by itself.
    progress = on_progress or (lambda line: None)
    progress("Running pre-install dependency checks...")
    check_results = dep.run_checks(phase=dep.PRE_INSTALL)
    failed = dep.loud_failures(check_results)
    if failed:
        summary = "; ".join(f"{r.id}: {r.detail}" for r in failed)
        return ActionResult(False, f"refusing to start - loud dependency check(s) failed: {summary}")
    # The one real consumer export_bootstrap_snapshot was actually built
    # for (its own docstring): every one of these values gets baked as
    # a literal string into the Proxmox answer.toml, which is applied
    # by the Proxmox installer's own separate environment - it can
    # never open this database itself. One snapshot call, not three
    # separate get_setting calls repeating the same (group, key) pairs.
    snapshot = settings_store.export_bootstrap_snapshot([
        ("self_installer", "lvm_size_preset"), ("self_installer", "fqdn"), ("self_installer", "memory_mb"),
    ])
    lvm_preset = params.get("lvm_size_preset") or snapshot["self_installer.lvm_size_preset"]
    lvm_sizes = si.LVM_SIZE_PRESETS[lvm_preset]
    fqdn = params.get("fqdn") or snapshot["self_installer.fqdn"]
    memory_mb = int(params.get("memory_mb") or snapshot["self_installer.memory_mb"])

    workspace = Path(params.get("workspace", "/var/tmp/baseline-self-installer"))
    result = si.build_and_write_self_installer(
        device_path=device_path,
        expected_serial=params.get("expected_serial"),
        device_min_size_bytes=int(params.get("device_min_size_bytes", 400_000_000_000)),
        pds_runner=pds_runner,
        acquire_runner=dsa.RealAcquireRunner(),
        answer_runner=dsan.RealAnswerRunner(),
        iso_builder_runner=ib.RealIsoBuilderRunner(),
        install_runner=dsi.RealInstallRunner(),
        workspace=workspace,
        repo_root=Path(params["repo_root"]) if params.get("repo_root") else REPO_ROOT,
        proxmox_source_iso=Path(params["proxmox_source_iso"]) if params.get("proxmox_source_iso") else None,
        assistant_binary=Path(params.get("assistant_binary", str(workspace / "acquire/extracted/usr/bin/proxmox-auto-install-assistant"))),
        server_host=params.get("server_host") or si.DEFAULT_SERVER_HOST,
        cert_path=Path(params["cert_path"]) if params.get("cert_path") else None,
        key_path=Path(params["key_path"]) if params.get("key_path") else None,
        fqdn=fqdn,
        memory_mb=memory_mb,
        target_mac=params.get("target_mac"),
        target_dmi_product=params.get("target_dmi_product"),
        on_progress=on_progress,
        # Direct instruction, 2026-09-29: "It has to accept my root
        # password in Linux now" - `runner` here is the real
        # `SudoRunner` built from whatever password the operator just
        # submitted to authorize this very action; reusing it as the
        # new Proxmox install's own root password means they log into
        # the freshly-installed machine with the password they already
        # know, not one they have to go find in a progress console.
        admin_password=getattr(runner, "password", None),
        **lvm_sizes,
    )
    return ActionResult(result.outcome == "applied", result.detail)


def run_health_check(runner, **params) -> ActionResult:
    """The real "adhoc" phase (decision record 88, direct instruction:
    health validations "both at boot and intervals and adhoc calls") -
    an operator-triggered run of every registered dependency, right
    now, on demand. Reuses the exact same `dependencies.run_checks`
    the pre-install gate and the boot/interval phases call - one real
    mechanism, four different triggers, not four different checks."""
    import dependencies as dep
    results = dep.run_checks(phase=dep.ADHOC)
    failed_loud = dep.loud_failures(results)
    lines = [f"[{'ok' if r.ok else ('LOUD-FAIL' if r.severity == dep.LOUD else 'silent-fail')}] {r.id}: {r.detail}"
             for r in results]
    detail = "; ".join(lines) if lines else "no dependencies are registered for the adhoc phase"
    return ActionResult(not failed_loud, detail)


@dataclass
class ActionSpec:
    action_id: str
    description: str
    run: object  # callable(runner, **params) -> ActionResult
    requires_device: bool = False  # the web page shows a drive-picker for this action, not a plain text field


ACTIONS = {
    # Listed first - decision record 86, direct instruction: "there
    # should not be a version that is not a self installed." This is
    # the default, primary path: pick a drive, click go. Every other
    # value it needs is pre-populated (settings_store.py's
    # "self_installer" group, itself only ever set via the Admin tab's
    # dropdowns) or derived/generated for real inside self_installer.py
    # - never typed.
    "build_self_installer": ActionSpec(
        "build_self_installer",
        "Build a real, self-contained Baseline installer (acquire + prepare-iso --fetch-from "
        "http + self-contained ISO remaster) from your pre-populated Admin settings, and launch "
        "the automated install against the selected drive for real. Does NOT confirm completion "
        "by itself - a human or vision-capable agent must review the final screendump before "
        "treating the drive as proven.",
        lambda runner, device_path, **params: build_self_installer(runner, device_path=device_path, **params),
        requires_device=True,
    ),
    # Direct instruction, 2026-09-29: "The only installer is a self
    # installer. There is not Create all the volumes button or
    # action." - the old human-override "install" (bare persistence,
    # no OS) and "create_volumes_on_existing_vg" actions are removed;
    # `install_drive`/`create_baseline_volumes` remain as real internal
    # functions (still used by `repair_scan_and_fix` below), just no
    # longer exposed as their own top-level actions.
    "update_selected": ActionSpec(
        "update_selected",
        "Refresh newer Debian package archives already represented in INSTALLER_CACHE using the "
        "host's APT repository trust policy. Downloads are verified and cached, never installed here. "
        "Other volumes are not package caches.",
        lambda runner, selected=(), **params: update_selected(runner, selected=list(selected)),
        requires_device=True,
    ),
    "repair": ActionSpec(
        "repair",
        "Scan this drive's Baseline volumes for real problems (missing volumes on an "
        "otherwise-real Baseline install) and create only what's actually missing - never "
        "touches or reformats a volume that already exists. Shown per-drive; each failing check "
        "is also listed individually on the drive itself.",
        lambda runner, device_path, **params: repair_scan_and_fix(runner, device_path=device_path),
        requires_device=True,
    ),
    "mount_volume": ActionSpec(
        "mount_volume",
        "Activate this drive's real volume group and mount one of its existing logical volumes "
        "(default: root) read-write at a real, predictable location under /mnt - for direct "
        "inspection or editing, not a one-off script you'd have to remember to re-run by hand.",
        lambda runner, device_path, **params: mount_logical_volume(runner, device_path=device_path, **params),
        requires_device=True,
    ),
    "unmount_volume": ActionSpec(
        "unmount_volume",
        "Unmount a logical volume this drive's mount_volume action mounted - the real "
        "counterpart, not something you have to remember to type yourself.",
        lambda runner, device_path, **params: unmount_logical_volume(runner, device_path=device_path, **params),
        requires_device=True,
    ),
    "unmount_partition": ActionSpec(
        "unmount_partition",
        "Safely unmount one mounted partition belonging to this exact drive before it is moved or tested on another machine.",
        lambda runner, device_path, **params: unmount_mounted_partition(runner, device_path=device_path, **params),
        requires_device=True,
    ),
}


def stamp_installer_identity(runner, *, device_path, on_progress=None, **params) -> ActionResult:
    """Adopt a drive that predates the installer-UUID rule (non-destructive: changes only the GPT disk GUID)."""
    try:
        serial = pds.get_device_serial(pds.Runner(), device_path) or "unknown"
    except Exception:  # noqa: BLE001 - the serial is informational in the registry
        serial = "unknown"
    result = drive_guard.stamp_installer_identity(runner, device_path, serial=serial)
    return ActionResult(result.ok, result.detail)


ACTIONS["stamp_installer_identity"] = ActionSpec(
    "stamp_installer_identity",
    "Give this drive an installer-generated identity so the installer may later format it. Only an empty drive, "
    "or one whose every partition is a Baseline volume, can be adopted; it changes nothing but the disk identifier.",
    lambda runner, device_path, **params: stamp_installer_identity(runner, device_path=device_path, **params),
    requires_device=True,
)


class _LayoutCmd:
    """Adapts a privileged Runner (`run(argv, timeout) -> CompletedProcess`) to baseline_drive_layout's `(rc, out, err)`."""

    def __init__(self, runner):
        self._runner = runner

    def run(self, argv):
        proc = self._runner.run(argv, timeout=600)
        return proc.returncode, proc.stdout or "", proc.stderr or ""


def lay_out_baseline_drive(runner, *, device_path, expected_serial=None, pds_runner=None,
                          on_progress=None, **params) -> ActionResult:
    """Erase and re-lay the Baseline drive's volumes (BASELINE, INSTALLER_CACHE, SESSION_TEMP, SUBSTRATE, USER_*, ...).
    Destructive. Only runs against a drive that is empty or already Baseline's own, with nothing mounted, with an
    installer UUID (or blank), and, if it holds Baseline data, with a recent backup (all enforced before this runs)."""
    import baseline_drive_layout as bdl
    if not expected_serial or expected_serial not in allowed_target_serials():
        return ActionResult(False, "refused: layout needs the exact confirmed managed drive serial")
    say = on_progress or (lambda line: None)
    pds_runner = pds_runner or pds.Runner()
    mounted = runner.run(["lsblk", "-nr", "-o", "MOUNTPOINT", device_path], timeout=30)
    if mounted.returncode != 0:
        return ActionResult(False, "refused: could not tell whether anything on the drive is mounted")
    in_use = [line.strip() for line in (mounted.stdout or "").splitlines() if line.strip()]
    if in_use:
        return ActionResult(False, f"refused: unmount first, these are mounted: {', '.join(in_use)}")

    def validate(path, expected_serial=None, min_size_bytes=0):
        return pds.validate_target_device(path, expected_serial=expected_serial, min_size_bytes=min_size_bytes,
                                          runner=pds_runner)
    read = _lsblk_run(pds_runner)
    say(f"laying out the Baseline volumes on {device_path}")
    try:
        plan = bdl.apply(_LayoutCmd(runner), device_path, validate=validate, read_drive=read,
                         expected_serial=expected_serial)
    except (bdl.LayoutError, pds.PhysicalDeviceSafetyError, drive_guard.DataProtectionError) as exc:
        return ActionResult(False, f"refused: {exc}")
    say(f"created {len(plan)} volumes; giving the drive its installer identity")
    try:
        validated = validate(device_path, expected_serial=expected_serial, min_size_bytes=MIN_TARGET_SIZE_BYTES)
        serial = validated["serial"]
    except pds.PhysicalDeviceSafetyError as exc:
        return ActionResult(False, f"refused: {exc}")
    stamped = drive_guard.stamp_installer_identity(runner, device_path, serial=serial, read=read)
    return ActionResult(True, f"laid out {len(plan)} Baseline volumes on {device_path}. " + stamped.detail)


ACTIONS["lay_out_baseline_drive"] = ActionSpec(
    "lay_out_baseline_drive",
    "ERASE this Baseline drive and lay out its volumes again (BASELINE, INSTALLER_CACHE, SESSION_TEMP, SUBSTRATE, "
    "the USER and AppData volumes). Everything on it is lost. Refused for any drive that is not empty or already "
    "Baseline's own, for a mounted drive, for a drive without an installer identity, and, if it holds Baseline data, "
    "without a successful backup in the last 24 hours. Confirmed by a person every time.",
    lambda runner, device_path, **params: lay_out_baseline_drive(runner, device_path=device_path, **params),
    requires_device=True,
)


def enroll_drive(runner: Runner, *, device_path: str, confirm_serial: str, pds_runner=None,
                 now: float | None = None) -> ActionResult:
    """Add one drive to the drives Baseline may act on. Writes nothing to the drive itself.

    Validated again here, not only in `_prepare`: the drive at `device_path` must be a real, non-boot block device of
    at least `MIN_TARGET_SIZE_BYTES` whose own serial is exactly the one the operator typed."""
    try:
        validated = pds.validate_target_device(device_path, expected_serial=drive_enrollment.check_serial(confirm_serial),
                                               min_size_bytes=MIN_TARGET_SIZE_BYTES, runner=pds_runner)
    except (pds.PhysicalDeviceSafetyError, ValueError) as exc:
        return ActionResult(False, f"refused: {exc}")
    serial = validated["serial"]
    if serial in allowed_target_serials():
        return ActionResult(True, f"drive with serial {serial} is already one Baseline may act on; nothing changed")
    drive_enrollment.enroll(serial, size_bytes=validated["size_bytes"], model="",
                            now=time.time() if now is None else now)
    return ActionResult(True, f"enrolled drive with serial {serial}. Nothing was written to it; formatting it "
                              "still needs it to be empty or to carry an installer identity")


ACTIONS["enroll_drive"] = ActionSpec(
    "enroll_drive",
    "Add this drive to the drives Baseline may act on. Type the drive's serial exactly as it reports it; it must "
    "match. This writes nothing to the drive: formatting it later still needs it to be empty or to carry an "
    "installer identity. Confirmed by a person every time.",
    lambda runner, device_path, **params: enroll_drive(runner, device_path=device_path, **params),
    requires_device=True,
)


def describe_actions() -> list:
    return [{"action_id": spec.action_id, "description": spec.description,
              "requires_device": spec.requires_device} for spec in ACTIONS.values()]


# ---------------------------------------------------------------------------
# Request parameters. The page posts {action_id, params}; these used to be splatted straight into
# privileged functions, so a volume name like "../../sda1" built /dev/<vg>/../../sda1 and reached a drive
# outside the allowlist, and a mountpoint could be "/etc". Every action now has an allowlist of parameter
# names and each value is validated. Anything unknown, or malformed, is refused before anything runs.
# ---------------------------------------------------------------------------

_LV_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+.-]{0,63}$")
_VOLUME_LABEL_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_MOUNT_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_PATH_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._+-]{1,128}$")
_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
_DMI_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")
_SERIAL_RE = re.compile(r"^[A-Za-z0-9._-]{4,40}$")
_SAFE_PATH_ROOTS = ("/mnt/INSTALLER_CACHE/", "/etc/baseline/", "/var/lib/baseline/")
_MAX_SELECTED = 20

ACTION_PARAMS = {
    "update_installed_drive": frozenset({"device_path", "input_bundle", "recovery_folder"}),
    "build_self_installer": frozenset({"device_path", "expected_serial", "proxmox_source_iso", "server_host",
                                       "cert_path", "key_path", "target_mac", "target_dmi_product"}),
    "repair": frozenset({"device_path"}),
    "mount_volume": frozenset({"device_path", "lv_name", "mountpoint"}),
    "unmount_volume": frozenset({"device_path", "lv_name", "mountpoint"}),
    "unmount_partition": frozenset({"device_path", "partition_mountpoint"}),
    "update_selected": frozenset({"selected", "device_path"}),     # the page sends device_path for every action
    "stamp_installer_identity": frozenset({"device_path"}),
    "lay_out_baseline_drive": frozenset({"device_path"}),
    "enroll_drive": frozenset({"device_path", "confirm_serial"}),
}

# Actions that format or install over a drive. They can never run on a drive that holds data and does not carry a
# UUID generated by the installer (drive_guard.py); there is no override and a refused request gets no challenge.
DESTRUCTIVE_ACTIONS = frozenset({"build_self_installer", "lay_out_baseline_drive"})


def _lsblk_run(pds_runner):
    """Adapt a physical_device_safety runner (`run(argv) -> str`) to drive_guard's `(returncode, stdout)`."""
    runner = pds_runner or pds.Runner()

    def run(argv):
        try:
            return 0, runner.run(argv)
        except Exception:  # noqa: BLE001 - failing to look means "unknown", which protects the drive
            return 1, ""
    return run


def backup_is_fresh() -> bool:
    return _read_backup_freshness()


def _read_backup_freshness() -> bool:
    """Is there proof of a successful backup within the last 24 hours (same proof the restore gate uses)?
    Reads the freshness records on the SK hynix drive; any failure to look counts as "no proof"."""
    import time

    import backup_restore
    from repair import RealRunner
    try:
        runner, now = RealRunner(), time.time()
        return any(backup_restore.has_recent_successful_backup(runner, target=target, now=now)
                   for target in backup_restore.all_volume_targets())
    except Exception:  # noqa: BLE001
        return False


def _check_str(name: str, value) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError(f"{name} must be a single-line, non-empty string")
    return value


def _check_lv_name(value) -> str:
    value = _check_str("lv_name", value)
    if not _LV_NAME_RE.match(value):
        raise ValueError("lv_name must be a plain volume name (letters, digits, _ + . -), at most 64 characters, "
                         "with no slash or leading dash")
    return value


def _check_mountpoint(value) -> str:
    value = _check_str("mountpoint", value)
    if os.path.normpath(value) != value or not value.startswith("/mnt/"):
        raise ValueError("mountpoint must be a clean absolute path under /mnt/")
    parts = value.split("/")[2:]
    if not 1 <= len(parts) <= 3 or not all(_MOUNT_COMPONENT_RE.match(c) for c in parts):
        raise ValueError("mountpoint must be one to three plain folder names under /mnt/")
    known = {mp for *_rest, mp in drive_installer.BASELINE_VOLUMES} | {"/mnt/10TB"}
    if value in known:
        raise ValueError("mountpoint must not be one of Baseline's own volume mountpoints")
    return value


def _check_partition_mountpoint(value) -> str:
    value = _check_str("mountpoint", value)
    if (not re.fullmatch(r"/mnt/[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value)
            or value in ("/mnt/10TB", "/mnt/INSTALLER_CACHE")):
        raise ValueError("partition mountpoint must be a direct child of /mnt, outside the backup and installer cache")
    return value


def _check_safe_path(name: str, value) -> str:
    value = _check_str(name, value)
    if (len(value) > 4096 or not os.path.isabs(value) or os.path.normpath(value) != value
            or not value.startswith(_SAFE_PATH_ROOTS)
            or not all(_PATH_COMPONENT_RE.match(c) for c in value.split("/")[1:])):
        raise ValueError(f"{name} must be a clean absolute path inside INSTALLER_CACHE or /etc/baseline or /var/lib/baseline")
    return value


def _check_server_host(value) -> str:
    value = _check_str("server_host", value)
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if not _HOSTNAME_RE.match(value):
        raise ValueError("server_host must be an IP address or a plain host name")
    return value


def _check_expected_serial(value) -> str:
    value = _check_str("expected_serial", value)
    if not _SERIAL_RE.match(value) or value not in ALLOWED_TARGET_SERIALS:
        raise ValueError("expected_serial is not one of the drives Baseline is allowed to act on")
    return value


def _check_selected(value) -> list:
    if (not isinstance(value, list) or len(value) > _MAX_SELECTED
            or not all(isinstance(v, str) and _VOLUME_LABEL_RE.match(v) for v in value)):
        raise ValueError("selected must be a short list of volume labels")
    return list(value)


_PARAM_CHECKS = {
    "input_bundle": lambda value: _check_update_path(value),
    "recovery_folder": lambda value: _check_update_path(value),
    "device_path": lambda v: _check_str("device_path", v),
    "lv_name": _check_lv_name,
    "mountpoint": _check_mountpoint,
    "partition_mountpoint": _check_partition_mountpoint,
    "selected": _check_selected,
    "expected_serial": _check_expected_serial,
    "confirm_serial": drive_enrollment.check_serial,
    "proxmox_source_iso": lambda v: _check_safe_path("proxmox_source_iso", v),
    "cert_path": lambda v: _check_safe_path("cert_path", v),
    "key_path": lambda v: _check_safe_path("key_path", v),
    "server_host": _check_server_host,
    "target_mac": lambda v: v if isinstance(v, str) and _MAC_RE.match(v) else (_ for _ in ()).throw(
        ValueError("target_mac must look like aa:bb:cc:dd:ee:ff")),
    "target_dmi_product": lambda v: v if isinstance(v, str) and _DMI_RE.match(v) else (_ for _ in ()).throw(
        ValueError("target_dmi_product must be plain text up to 64 characters")),
}


def validate_action_params(action_id: str, params: dict) -> dict:
    """Returns a cleaned copy of `params`, or raises ValueError. Unknown parameter names are refused outright."""
    allowed = ACTION_PARAMS.get(action_id)
    if allowed is None:
        raise ValueError(f"unknown action {action_id!r}")
    if action_id == 'update_installed_drive' and set(params) != set(allowed):
        raise ValueError('missing required installer update inputs')
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ValueError(f"unknown parameter(s) for {action_id}: {', '.join(unknown)}")
    return {name: _PARAM_CHECKS[name](value) for name, value in params.items()}


def _prepare(action_id: str, params: dict, pds_runner=None) -> tuple:
    """Validate a request without running it. Returns (spec, cleaned params with the validated device path,
    serial). Raises ValueError with a refusal message for an unknown action, bad parameters, or a drive that
    is not one of the allowed SK hynix drives."""
    spec = ACTIONS.get(action_id)
    if spec is None:
        raise ValueError(f"unknown action {action_id!r}")
    try:
        call_params = validate_action_params(action_id, dict(params))
    except ValueError as exc:
        raise ValueError(f"refused: invalid parameter: {exc}") from exc
    serial = "volumes"          # update_selected acts on Baseline's volumes, not on one drive
    if spec.requires_device and action_id != "update_selected":
        # The one gate every drive action passes through. Nothing runs against a drive
        # unless it is one of the allowed SK hynix drives, and the action is handed the
        # path that was actually validated, not the string the caller supplied.
        device_path = call_params.get("device_path")
        if not device_path:
            raise ValueError(f"{action_id} needs a drive and none was given")
        if action_id == "enroll_drive":
            call_params, serial = _prepare_enrollment(call_params, pds_runner)
            return spec, call_params, serial
        try:
            validated = resolve_target(device_path, pds_runner=pds_runner)
        except pds.PhysicalDeviceSafetyError:
            raise ValueError(f"refused: Baseline acts only on the SK hynix drives it is set up with, "
                             f"and {device_path} is not one of the allowed drives") from None
        call_params["device_path"] = validated["path"]
        serial = validated["serial"]
        if action_id in DESTRUCTIVE_ACTIONS:
            try:
                if action_id == "lay_out_baseline_drive":
                    drive_guard.require_baseline_drive(validated["path"], run=_lsblk_run(pds_runner))
                drive_guard.require_may_format(validated["path"], run=_lsblk_run(pds_runner))
            except drive_guard.DataProtectionError as exc:
                raise ValueError(str(exc)) from None
            state = drive_guard.read_drive_state(validated["path"], run=_lsblk_run(pds_runner))
            if state.has_data and not backup_is_fresh():
                raise ValueError("refused: this drive holds Baseline's data and there is no proof of a successful "
                                 "backup in the last 24 hours. Run a backup first")
    return spec, call_params, serial


def _prepare_enrollment(call_params: dict, pds_runner) -> tuple:
    """Enrollment is the one action whose drive is, by definition, not yet allowed. Instead of the allowlist, the
    drive must report exactly the serial the operator typed, and still be a real, non-boot, large enough device."""
    typed = call_params.get("confirm_serial")
    if not typed:
        raise ValueError(f"refused: {call_params['device_path']} is not one of the allowed drives until it is "
                         "enrolled, and enrolling it needs its serial typed")
    try:
        validated = pds.validate_target_device(call_params["device_path"], expected_serial=typed,
                                               min_size_bytes=MIN_TARGET_SIZE_BYTES, runner=pds_runner)
    except pds.PhysicalDeviceSafetyError as exc:
        raise ValueError(f"refused: {exc}") from None
    call_params["device_path"] = validated["path"]
    return call_params, validated["serial"]


def prepare_action(action_id: str, params: dict, *, pds_runner=None) -> dict:
    """What a person is being asked to confirm: the cleaned request, the drive's serial, and a plain summary."""
    spec, call_params, serial = _prepare(action_id, params, pds_runner)
    where = f"drive {call_params['device_path']} (serial ending {serial[-6:]})" if "device_path" in call_params else "Baseline's volumes"
    target = (f"\nMounted partition location: {call_params['partition_mountpoint']}."
              if action_id == "unmount_partition" else "")
    return {"action_id": action_id, "params": call_params, "serial": serial,
            "summary": f"{spec.description}\nThis will run on {where}.{target}"}


def perform_action(runner: Runner, action_id: str, params: dict, *, on_progress=None, pds_runner=None,
                   authorization=None, hitl_store=None, origin=None) -> ActionResult:
    """`on_progress` (direct instruction, 2026-09-29 - "add a console
    log of what is running and doing"): threaded through as a real
    keyword argument, never required by any action's own signature -
    only `build_self_installer` actually reports through it (the one
    real, multi-minute action); every other action's own lambda simply
    doesn't forward it, so it's silently unused there, never an
    error.

    Every drive action needs a human confirmation, each time (hitl.py): `authorization` must be a valid,
    unused authorization for exactly this request, otherwise nothing runs. There is no flag that skips this."""
    try:
        spec, call_params, serial = _prepare(action_id, params, pds_runner)
    except ValueError as exc:
        message = str(exc)
        return ActionResult(False, message if message.startswith(("refused", "unknown action")) or "needs a drive" in message
                            else f"refused: {message}")
    try:
        # Two independent proofs: the web application asked (signed origin), and a person confirmed (hitl).
        web_gate.require(origin, "drive_action", {"action_id": action_id, "params": call_params})
    except web_gate.NotFromWebApp as exc:
        return ActionResult(False, f"refused: {exc}")
    if getattr(authorization, '_kind', None) == 'native_pending':
        if action_id not in hitl.NATIVE_POLICYKIT_ACTIONS or type(runner) is not PkexecRunner:
            return ActionResult(False, 'refused: pending native authorization requires an approved PolicyKit action and PkexecRunner')
    try:
        hitl.require(authorization, action_id, call_params, serial, store=hitl_store)
    except hitl.ConfirmationRequired as exc:
        return ActionResult(False, f"refused: this action needs a human confirmation ({exc})")
    if on_progress is not None:
        call_params["on_progress"] = on_progress
    if action_id in ("lay_out_baseline_drive", "enroll_drive"):
        call_params["pds_runner"] = pds_runner
    if action_id == "lay_out_baseline_drive":
        # Internal dispatch value, added only after the web and HITL proofs
        # verify the original request and this exact device serial.
        call_params["expected_serial"] = serial
    if action_id == "update_installed_drive":
        call_params["expected_serial"] = serial
    if action_id == "unmount_partition":
        call_params["expected_serial"] = serial
    return spec.run(runner, **call_params)


def _check_update_path(value):
    value = _check_str("installer path", value)
    if (not os.path.isabs(value) or os.path.normpath(value) != value
            or any(c in value for c in "\x00\n\r") or len(value) > 4096):
        raise ValueError("installer paths must be clean absolute paths")
    return value


def update_installed_drive(runner, *, device_path, expected_serial, input_bundle,
                           recovery_folder, on_progress=None):
    """The helper re-resolves and validates the serial before every physical write."""
    import json
    helper = REPO_ROOT / "baseline/bin/baseline-drive-update"
    if not helper.is_file():
        return ActionResult(False, "Installed-drive update helper unavailable")
    if on_progress:
        on_progress("Verifying target ownership, recovery and captured inputs before updating the installed system.")
    proc = runner.run(["/usr/bin/python3", str(helper), "--serial", expected_serial,
                       "--input-bundle", input_bundle, "--recovery-folder", recovery_folder], timeout=7200)
    if proc.returncode:
        return ActionResult(False, "Installed-drive update failed; inspect its stage journal before retrying. " +
                            (proc.stderr or "")[-2000:])
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        if result.get("state") != "updated" or result.get("boot_verified") is not False:
            raise ValueError
    except (ValueError, IndexError, TypeError):
        return ActionResult(False, "Update helper did not return a verified completion record")
    return ActionResult(True, "Installed Baseline updated with retained storage. Physical boot, internet, firewall and workload acceptance remain pending.")


ACTIONS["update_installed_drive"] = ActionSpec(
    "update_installed_drive",
    "Update a recognized installed Proxmox/Baseline drive from a captured input bundle. "
    "Verify recovery and storage identity, retain user/application/cache volumes, refresh "
    "Baseline and boot files using online package sources. Grow disposable BASELINE to at least 50 GiB "
    "when required, preserving a 16 GiB VG reserve. No partitioning, formatting, "
    "credential reset or restoration over existing user data. Boot and workload verification follow separately.",
    lambda runner, **params: update_installed_drive(runner, **params), requires_device=True)
