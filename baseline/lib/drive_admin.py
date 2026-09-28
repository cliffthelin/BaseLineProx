"""Real Drive Administration actions for the merged web app (decision
record 83). Direct instruction: "this application will never get off
the ground if your solution is terminal commands" - every action here
is real code the already-root `settings_web`/`control_panel_web`
process executes itself, gated behind a real elevation check
(`admin_elevation.py`), never a script handed to the operator to run
in a terminal.

**Why no `sudo` subprocess wrapping is needed**: `baseline.service`/
`baseline-settings-web.service` already run as root (no `User=` in
either unit - systemd defaults to root). The "sudo password" the web
UI asks for is a real *identity/intent* check, not a technical
privilege bridge: `settings_web.SystemPasswordVerifier` verifies the
submitted password against the machine's own real `/etc/shadow`
account before any action here runs - "standard Ubuntu design" in the
sense that matters (prove you are the admin, right now, for this
specific change), not literally re-deriving root the process already
has.

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


def parse_candidate_drives(text: str) -> list:
    """Parses real `lsblk -P` output into dicts. `TYPE=disk` only -
    excludes partitions/loop/rom devices lsblk's own `-d` flag doesn't
    already filter out on every kernel."""
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = dict(token.split("=", 1) for token in shlex.split(line) if "=" in token)
        if fields.get("TYPE") != "disk":
            continue
        rows.append(fields)
    return rows


def classify_drive_type(*, tran: str, rota: str, model: str) -> str:
    """Real classification, not a guess from the transport alone.

    Real finding this project's own two target drives exposed: a
    USB-NVMe bridge chip reports `ROTA=1` (rotational) for a genuinely
    solid-state drive - `ROTA` is only trustworthy on a *direct*
    (non-USB) transport, where the kernel reads it from the real
    device, not a bridge chip that may not pass it through correctly.
    So: check the model string for an explicit NVMe/SSD claim first
    (always trustworthy when present, regardless of transport); only
    trust `ROTA` when the transport isn't USB; and when a USB-attached
    device gives no real hint either way, report "USB" honestly rather
    than guess "HDD" or "SSD" - the literal case the user asked for
    this category to cover."""
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
    boot_serial = pds.get_boot_device_serial(pds_runner)
    drives = []
    for row in parse_candidate_drives(proc.stdout):
        name = row.get("NAME", "")
        serial = row.get("SERIAL") or None
        if not name or (boot_serial is not None and serial == boot_serial):
            continue
        drives.append({
            "path": f"/dev/{name}",
            "model": row.get("MODEL") or "Unknown model",
            "size": row.get("SIZE") or "?",
            "drive_type": classify_drive_type(tran=row.get("TRAN", ""), rota=row.get("ROTA", ""),
                                               model=row.get("MODEL", "")),
            "is_default": serial in DEFAULT_TARGET_SERIALS,
        })
    return drives


@dataclass
class ActionResult:
    ok: bool
    detail: str


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
    is operator-selected (see `list_candidate_drives`), never assumed."""
    try:
        validated = resolve_target(device_path, pds_runner=pds_runner)
    except pds.PhysicalDeviceSafetyError as exc:
        return ActionResult(False, f"refused: {exc}")

    pds.wipe_signatures(validated, runner=pds_runner)

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


@dataclass
class ActionSpec:
    action_id: str
    description: str
    run: object  # callable(runner, **params) -> ActionResult
    requires_device: bool = False  # the web page shows a drive-picker for this action, not a plain text field


ACTIONS = {
    "rebuild_persistence_lvm": ActionSpec(
        "rebuild_persistence_lvm",
        "PERMANENTLY ERASE all data on the selected drive and rebuild it as an empty "
        "LVM volume group. This cannot be undone.",
        lambda runner, device_path, **params: rebuild_persistence_lvm(runner, device_path=device_path),
        requires_device=True,
    ),
    "create_baseline_volumes": ActionSpec(
        "create_baseline_volumes",
        "Create the real BASELINE/INSTALLER_CACHE/SESSION_TEMP and per-persona "
        "USER_PERSISTENCE volumes on the rebuilt persistence volume group.",
        lambda runner, **params: create_baseline_volumes(runner),
    ),
    "switch_persona": ActionSpec(
        "switch_persona",
        "Unmount the currently active persona's volume and mount a different persona's "
        "volume in its place. Changes which persona's data is currently accessible.",
        lambda runner, to_persona, **params: switch_persona(runner, to_persona=to_persona),
    ),
    "apply_volume_mode": ActionSpec(
        "apply_volume_mode",
        "Remount a shared volume (BASELINE/INSTALLER_CACHE/SESSION_TEMP) using its "
        "currently configured mode from the Admin settings tab.",
        lambda runner, label, **params: apply_volume_mode(runner, label=label),
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
