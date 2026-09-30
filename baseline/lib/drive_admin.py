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
bare, unvalidated operator-typed path. Per that module's own
documented, direct-instruction design ("Expected serial doesn't seem
like it should be forced... Default is not and I do not want it
restricted"), the target device is **selectable**, not hardcoded to
exactly two serials: `list_candidate_drives` enumerates every real,
non-boot block device on the machine so an operator can pick any of
them. `DEFAULT_TARGET_SERIALS` (this project's own two pre-authorized
disposable drives) only marks which candidate is pre-selected by
default in the picker - it is a suggestion, never a restriction; any
other real, sufficiently large, non-boot device validates and runs
identically.

Each `ACTIONS` entry pairs one human-readable description with the
exact callable that runs - the web page's modal renders the same
description this module executes against, so there is never a second,
drifting copy of "what this button actually does."
"""
from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

import drive_installer
import persist_bind_mounts as pbm
import physical_device_safety as pds
import settings_store

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

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError


# This project's own two pre-authorized disposable drives (decision
# records 45-47) - marks the default *pre-selection* in the drive
# picker only. Never a restriction: any other real, non-boot, large
# enough device validates and runs identically (see module docstring).
DEFAULT_TARGET_SERIALS = {"MD89N41071210AP4E", "FD01N6557110C271B"}


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
        rows.append(dict(token.split("=", 1) for token in shlex.split(line) if "=" in token))
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
    proc = runner.run(drive_partition_summary_argv(), timeout=15)
    if proc.returncode != 0:
        return {"partition_count": None, "usage_text": "unknown"}
    return _partition_summary_from_rows(parse_lsblk_pairs(proc.stdout), drive_name)


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
    proc = runner.run(list_candidate_drives_argv(), timeout=15)
    if proc.returncode != 0:
        return []
    # One real, whole-system lsblk call for every candidate drive's
    # partition count/usage, not one re-query per drive.
    tree_proc = runner.run(drive_partition_summary_argv(), timeout=15)
    tree_rows = parse_lsblk_pairs(tree_proc.stdout) if tree_proc.returncode == 0 else []
    boot_serial = pds.get_boot_device_serial(pds_runner)
    drives = []
    for row in parse_candidate_drives(proc.stdout):
        name = row.get("NAME", "")
        serial = row.get("SERIAL") or None
        if not name or (boot_serial is not None and serial == boot_serial):
            continue
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
    least `MIN_TARGET_SIZE_BYTES`. Deliberately unrestricted by serial
    (`expected_serial` omitted) - any real candidate `list_candidate_drives`
    listed validates, per physical_device_safety.py's own documented,
    direct-instruction design; `DEFAULT_TARGET_SERIALS` only affects
    which candidate the UI pre-selects, never which ones this function
    accepts."""
    return pds.validate_target_device(device_path, min_size_bytes=MIN_TARGET_SIZE_BYTES, runner=pds_runner)


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
    /SESSION_TEMP plus one USER_PERSISTENCE_<PERSONA> volume per
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


def check_cache_updates(runner) -> list:
    """Real per-volume "is a newer compatible version available"
    check - direct instruction, 2026-09-29. Honestly empty right now:
    no real update source is wired up for any cached artifact yet (the
    curated Helper-Scripts in vm_scripts.SCRIPT_MANIFEST are
    deliberately manually-pinned/reviewed, never auto-checked or
    auto-updated by design; the cached Proxmox source ISO and any
    distro ISO have no real version-tracking built yet). Returning a
    real empty list here, not a fabricated "nothing available" per
    item - there is a real difference between "checked, found
    nothing" and "never checked," and this module does not blur it."""
    return []


def update_selected(runner, *, selected: list, **params) -> ActionResult:
    """The real "Update" action (direct instruction, 2026-09-29):
    check each selected Baseline volume for a newer compatible version
    of what it caches, and apply the ones chosen. Honest placeholder
    for the actual apply step - `check_cache_updates` never returns
    anything yet (see its own docstring for why), so there is nothing
    real to apply. Refuses plainly rather than faking success."""
    if not selected:
        return ActionResult(False, "no volumes selected")
    return ActionResult(
        False, "update-checking is not implemented yet - no real 'newer version available' "
               "source exists for any cached artifact in this build")


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
    proc = runner.run(["sudo", "-n", "pvs", "--noheadings", "-o", "pv_name,vg_name"], timeout=15)
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith(device_path):
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
    vg_name = find_vg_for_device(runner, device_path)
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
    vg_name = find_vg_for_device(runner, device_path)
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
    vg_name = find_vg_for_device(runner, device_path)
    if vg_name is None:
        return ActionResult(False, f"{device_path} has no real LVM volume group - nothing to unmount")
    target = mountpoint or f"/mnt/{vg_name}-{lv_name}-inspect"
    progress(f"Unmounting {target}...")
    result = runner.run(["umount", target])
    if result.returncode != 0:
        return ActionResult(False, f"unmounting {target} failed: {result.stderr.strip()}")
    return ActionResult(True, f"{target} unmounted")


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
        "Check every volume on this Baseline drive for a newer compatible version of what it "
        "caches, and apply the ones you select (or all of them). Only meaningful on a real "
        "Baseline drive - shown only when one is selected.",
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
}


def describe_actions() -> list:
    return [{"action_id": spec.action_id, "description": spec.description,
              "requires_device": spec.requires_device} for spec in ACTIONS.values()]


def perform_action(runner: Runner, action_id: str, params: dict, *, on_progress=None) -> ActionResult:
    """`on_progress` (direct instruction, 2026-09-29 - "add a console
    log of what is running and doing"): threaded through as a real
    keyword argument, never required by any action's own signature -
    only `build_self_installer` actually reports through it (the one
    real, multi-minute action); every other action's own lambda simply
    doesn't forward it, so it's silently unused there, never an
    error."""
    spec = ACTIONS.get(action_id)
    if spec is None:
        return ActionResult(False, f"unknown action {action_id!r}")
    call_params = dict(params)
    if on_progress is not None:
        call_params["on_progress"] = on_progress
    return spec.run(runner, **call_params)
