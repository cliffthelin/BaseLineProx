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

import drive_installer
import persist_bind_mounts as pbm
import physical_device_safety as pds
import settings_store

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
    str`, stdout only) - see `SudoRunner.as_pds_runner`."""

    def __init__(self, sudo_runner: SudoRunner):
        self._sudo_runner = sudo_runner

    def run(self, argv: list) -> str:
        return self._sudo_runner.run(argv, timeout=30).stdout


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
        drives.append({
            "path": path,
            "model": row.get("MODEL") or "Unknown model",
            "size": row.get("SIZE") or "?",
            "drive_type": classify_drive_type(tran=tran, rota=row.get("ROTA", ""),
                                               model=row.get("MODEL", ""), usb_bridge_model=usb_bridge_model),
            "is_default": serial in DEFAULT_TARGET_SERIALS,
            "partition_count": summary["partition_count"],
            "usage_text": summary["usage_text"],
        })
    return drives


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
    mode = settings_store.get_setting(runner, "volumes", key_by_label[label])
    mountpoint = next((mp for _, _, lbl, mp in drive_installer.SHARED_VOLUMES if lbl == label), None)
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


# The real, currently-updatable shared volumes - the only labels
# `update_selected`'s "apply_volume_mode" update type can act on (must
# match `apply_volume_mode`'s own accepted labels).
UPDATABLE_VOLUME_LABELS = {"BASELINE", "INSTALLER_CACHE", "SESSION_TEMP"}


def update_selected(runner, *, selected: list, update_types: list, to_persona: str | None = None) -> ActionResult:
    """The real "Update" action - direct instruction: select
    partitions/volumes from the drive tree, then select the types of
    update to apply to the selection. Replaces what used to be two
    separate top-level actions (switch_persona, apply_volume_mode)
    with one real action driven by a selection plus a set of chosen
    update types. `apply_volume_mode` runs once per selected item that
    is actually a configurable shared volume; `switch_persona` is a
    single global operation (there is only ever one active persona at
    a time), so it runs once when requested regardless of how many
    items are selected, not once per selected item."""
    results = []
    if "apply_volume_mode" in update_types:
        targeted = [label for label in selected if label in UPDATABLE_VOLUME_LABELS]
        if not targeted:
            results.append(("apply_volume_mode",
                             ActionResult(False, "no selected item supports a volume mode update")))
        for label in targeted:
            results.append((label, apply_volume_mode(runner, label=label)))
    if "switch_persona" in update_types:
        if to_persona:
            results.append((f"persona:{to_persona}", switch_persona(runner, to_persona=to_persona)))
        else:
            results.append(("switch_persona",
                             ActionResult(False, "switch_persona selected but no target persona was given")))
    if not results:
        return ActionResult(False, "no update types selected")
    ok = all(r.ok for _, r in results)
    detail = "; ".join(f"{name}: {r.detail}" for name, r in results)
    return ActionResult(ok, detail)


def repair_scan_and_fix(runner, **params) -> ActionResult:
    """Placeholder for the v0.2 Repair feature - direct instruction:
    "a Repair button that tries to look for things not working and
    then fix them - this is a v0.2 button." Deliberately does not
    pretend to scan or fix anything yet: an honest "not implemented"
    refusal, never a fake success, matches this project's own
    no-fake-functionality discipline."""
    return ActionResult(False, "Repair is planned for v0.2 and is not implemented in this build yet.")


@dataclass
class ActionSpec:
    action_id: str
    description: str
    run: object  # callable(runner, **params) -> ActionResult
    requires_device: bool = False  # the web page shows a drive-picker for this action, not a plain text field


ACTIONS = {
    "install": ActionSpec(
        "install",
        "PERMANENTLY ERASE the selected drive and install a fresh Baseline persistence "
        "structure on it (LVM volume group plus BASELINE/INSTALLER_CACHE/SESSION_TEMP and "
        "per-persona volumes). This cannot be undone.",
        lambda runner, device_path, **params: install_drive(runner, device_path=device_path),
        requires_device=True,
    ),
    "update_selected": ActionSpec(
        "update_selected",
        "Apply the selected types of update (volume mount mode, active persona) to the "
        "partitions and volumes selected from the drive tree.",
        lambda runner, selected=(), update_types=(), to_persona=None, **params: update_selected(
            runner, selected=list(selected), update_types=list(update_types), to_persona=to_persona),
    ),
    "repair": ActionSpec(
        "repair",
        "(v0.2) Scan the persistence setup for problems and fix what it finds. Not yet "
        "implemented in this build.",
        lambda runner, **params: repair_scan_and_fix(runner),
    ),
}


def describe_actions() -> list:
    return [{"action_id": spec.action_id, "description": spec.description,
              "requires_device": spec.requires_device} for spec in ACTIONS.values()]


def perform_action(runner: Runner, action_id: str, params: dict) -> ActionResult:
    spec = ACTIONS.get(action_id)
    if spec is None:
        return ActionResult(False, f"unknown action {action_id!r}")
    return spec.run(runner, **params)
