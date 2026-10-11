"""The real, unified installer entry point - not ad hoc terminal
commands.

Written after a real process failure this session (decision record
49): destructive commands (`wipefs`, `sgdisk`, `mkfs`) were run
directly against real hardware from chat, instead of being built here
first, reviewed, and only then run. That should never happen again -
every future real-hardware change goes through a module like this one,
tested against fakes first, exactly like every other provisioning
module in this codebase.

**Single-drive design, corrected from this session's own earlier
mistake**: `BASELINE`/`USER`/`INSTALLER_CACHE`/
`SESSION_TEMP` all live on the *same* physical drive, as additional
LVM logical volumes inside Proxmox's own existing volume group (`pve`
by default) - never a second drive, never a new partition table.
Proxmox's own boot/EFI partitions and its existing root/data logical
volumes are never touched by anything in this module - `ensure_volume`
only ever creates a *new* logical volume that doesn't exist yet, and
never reformats one that already does. That's the actual safety
property "you should not reformat" requires, and it's what makes this
module idempotent enough to also serve as the update path: re-running
it against an already-provisioned drive creates nothing new and
touches no existing data, which is exactly what pushing a later update
needs.

Free VG space is checked *before* attempting to create anything -
Proxmox's default install often allocates most/all free space to its
own thin pool, and there may genuinely not be room for these
additional volumes without a reinstall that reserves space up front
(the answer-file's `maxroot`/similar sizing options) - this module
fails closed and reports that plainly rather than guessing or
shrinking anything.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from repair import Runner


DEFAULT_VG_NAME = "pve"

# name, min_gb, max_gb, GPT/ext4 label, mountpoint - the shared
# volumes present on every install (decision records 46-49, 68, and
# the 2026-09-29 sizing-defaults instruction): BASELINE (application/
# VM/LXC state), INSTALLER_CACHE, SESSION_TEMP, SUBSTRATE.
# Never persona-scoped - there is exactly one of each per install.
#
# Sizing model, replacing the old single "desired size" per volume
# (direct instruction: "You seem really bad at sizing the volume so I
# will give you defaults"): every volume now carries its own real
# (min_gb, max_gb) range. `compute_adaptive_plan` never allocates a
# volume below its min_gb (refusing outright, all zeros, only if real
# free space can't even cover every volume's minimum) and never above
# its max_gb, however much free space actually exists - real available
# space still wins between those two bounds, it just no longer means
# "grow without limit."
SHARED_VOLUMES = (
    ("baseline_app_state", 5, 50, "BASELINE", "/mnt/BASELINE"),
    ("baseline_installer_cache", 50, 200, "INSTALLER_CACHE", "/mnt/INSTALLER_CACHE"),
    ("baseline_session_temp", 5, 50, "SESSION_TEMP", "/mnt/SESSION_TEMP"),
    # Recovery configuration + substrate (host/Proxmox-level, not
    # persona) configuration, including the one-way-hashed admin-provided
    # installer/recovery passphrase - direct instruction, 2026-09-29:
    # deliberately separate from BASELINE (which holds real app/VM/LXC
    # *state*, not this kind of small, security-relevant config data).
    # Fixed 1GB, no growth ceiling above that - this volume's whole
    # point is to stay small, non-persona, and always-present.
    ("baseline_substrate", 1, 1, "SUBSTRATE", "/mnt/SUBSTRATE"),
)

# Multiple, isolated USER volumes - "like a different
# Proxmox account," per direct instruction - not one shared volume.
# The default creator becomes "admin" (root-like, not the daily
# driver, has cross-persona access gated behind its own additional
# passphrase); "personal" is the default daily-driver persona spun up
# alongside it. Any further persona (work, a deliberately risky
# account, etc.) is opt-in, created explicitly later - never implied
# by this default (decision record 76).
DEFAULT_PERSONAS = ("admin", "personal")


def persona_label(persona: str) -> str:
    return f"USER_{persona.upper()}"


def persona_lv_name(persona: str) -> str:
    return f"baseline_user_{persona.lower()}"


def persona_mountpoint(persona: str) -> str:
    return f"/mnt/{persona_label(persona)}"


def persona_volume(persona: str, *, min_gb: int = 50, max_gb: int = 200) -> tuple:
    return (persona_lv_name(persona), min_gb, max_gb, persona_label(persona), persona_mountpoint(persona))


# Per-persona AppData (direct instruction, 2026-09-30): "Application
# data is personal owned application data and does not go anywhere
# other than an AppData persistence volume or container." It is a
# separate volume from USER on purpose - USER
# holds the person's own settings/state, AppData holds the writable
# upper layer of every installed application's overlay (appdata.py).
# Per-persona rather than shared, following the phone-OS model: app
# data belongs to a person, so it is owned by one.
def appdata_label(persona: str) -> str:
    return f"APPDATA_{persona.upper()}"


def appdata_lv_name(persona: str) -> str:
    return f"baseline_appdata_{persona.lower()}"


def appdata_mountpoint(persona: str) -> str:
    return f"/mnt/{appdata_label(persona)}"


def appdata_volume(persona: str, *, min_gb: int = 20, max_gb: int = 200) -> tuple:
    return (appdata_lv_name(persona), min_gb, max_gb, appdata_label(persona), appdata_mountpoint(persona))


def is_user_label(label: str) -> bool:
    return label.startswith("USER_") or label == "USER"


def is_appdata_label(label: str) -> bool:
    return label.startswith("APPDATA_")


def baseline_volumes_for(personas: tuple = DEFAULT_PERSONAS) -> tuple:
    """The real, complete volume set for a given persona set: the
    shared volumes plus, per persona, one USER_<PERSONA>
    and one APPDATA_<PERSONA>. `personas=()` gives just the shared
    volumes - useful for provisioning the substrate before any persona
    is created.

    Order is part of the on-disk contract: baseline_drive_layout numbers GPT
    partitions in this order. AppData is therefore appended AFTER every
    pre-existing volume rather than interleaved per persona - an
    interleaved order moved USER_PERSONAL from partition 6 to
    7, so re-applying the plan to an already laid-out Baseline drive would have
    treated the personal persona's partition as AppData."""
    return (SHARED_VOLUMES
            + tuple(persona_volume(p) for p in personas)
            + tuple(appdata_volume(p) for p in personas))


# The real, default set this module ensures unless a caller passes its
# own `personas` - admin + personal, matching DEFAULT_PERSONAS.
BASELINE_VOLUMES = baseline_volumes_for()

# Per-role mount restrictions (real follow-up work, decision record
# 71): nosuid+nodev everywhere - none of these volumes should ever
# host a setuid binary or a device node. noexec additionally on
# SESSION_TEMP (pure ephemeral session data - never anything meant to
# run) and INSTALLER_CACHE (holds ISOs/driver packages, consumed by
# name via dpkg/mount/xorriso, never executed directly). Not on
# USER - it holds the scripts inbox, and an operator may
# reasonably chmod +x and run a pushed script directly from there. Not
# on BASELINE - app/VM/LXC state may legitimately need to execute
# things it stores.
MOUNT_OPTIONS = {
    "BASELINE": "defaults,nosuid,nodev",
    "INSTALLER_CACHE": "defaults,nosuid,nodev,noexec",
    "SESSION_TEMP": "defaults,nosuid,nodev,noexec",
    # Config/recovery data only, never anything meant to run - same
    # noexec discipline as INSTALLER_CACHE/SESSION_TEMP.
    "SUBSTRATE": "defaults,nosuid,nodev,noexec",
}
_USER_MOUNT_OPTIONS = "defaults,nosuid,nodev"


def mount_options_for(label: str) -> str:
    """Every USER_<PERSONA> label (any persona) gets the
    same policy as the old singular USER did - matched by
    prefix, not by an ever-growing dict of every persona name."""
    if is_user_label(label):
        return _USER_MOUNT_OPTIONS
    # AppData holds every application's writable layer, so it gets at
    # least the persona policy. Without this branch APPDATA_* fell
    # through to bare "defaults" - setuid binaries and device nodes
    # permitted on the one volume every app can write to. Not noexec:
    # podman's own image layers live in an AppData upper layer and must
    # execute; whether a narrower policy is possible is an open question.
    if is_appdata_label(label):
        return _USER_MOUNT_OPTIONS
    return MOUNT_OPTIONS.get(label, "defaults")


FSTAB_PATH = "/etc/fstab"


@dataclass
class CommandResult:
    ok: bool
    detail: str
    created: bool = False


# ---------------------------------------------------------------------------
# Pure argv builders and output parsers
# ---------------------------------------------------------------------------

def list_logical_volumes_argv() -> list:
    """`sudo -n` (real bug found live, 2026-09-29): a plain `cane` user
    on this real machine cannot read LVM metadata at all -
    `pvs`/`vgs`/`lvs` as a bare unprivileged call fails with
    "Permission denied" (exit 5), which this project's own parsers
    treat identically to "genuinely found nothing" - masking the
    failure completely whenever the real answer also happened to be
    empty (which it always has been so far, since no real Baseline
    volumes exist anywhere yet). This machine's own real sudoers file
    has `vgs`/`lvs`/`vgchange`/`pvs` specifically passwordless (a
    deliberate, narrow, read-only allowance, confirmed live via `sudo
    -n -l`) - `-n` makes this call fail cleanly (never hang waiting
    for a password) on any machine where that isn't configured, rather
    than making anything worse than today's already-broken read.
    Destructive LVM commands (`lvcreate`/`vgcreate`/etc.) are
    deliberately NOT given this treatment - those still correctly rely
    on the caller's own already-privileged runner (`PkexecRunner`)
    during a real action, never a blanket passwordless allowance."""
    return ["sudo", "-n", "lvs", "--noheadings", "-o", "vg_name,lv_name"]


def vg_free_bytes_argv(vg_name: str) -> list:
    return ["sudo", "-n", "vgs", "--noheadings", "--units", "b", "--nosuffix", "-o", "vg_free", vg_name]


def create_logical_volume_argv(vg_name: str, lv_name: str, size: str, *, wipe_stale_signatures: bool = False) -> list:
    """`wipe_stale_signatures` makes lvcreate wipe a filesystem signature it finds where the new volume lands. That space is
    unallocated in this volume group, so it belongs to no existing volume; it is only ever leftover from an earlier install
    of the drive, which otherwise stops the reinstall (lvcreate cannot ask, and refuses). Off by default."""
    wipe = ["--wipesignatures", "y", "--yes"] if wipe_stale_signatures else []
    return ["lvcreate", "-n", lv_name, "-L", size, *wipe, vg_name]


def format_and_label_argv(lv_path: str, label: str) -> list:
    return ["mkfs.ext4", "-F", "-L", label, lv_path]


def makedirs_argv(mountpoint: str) -> list:
    return ["mkdir", "-p", mountpoint]


def mount_argv(lv_path: str, mountpoint: str, options: str | None = None) -> list:
    if options:
        return ["mount", "-o", options, lv_path, mountpoint]
    return ["mount", lv_path, mountpoint]


def remount_argv(mountpoint: str, options: str) -> list:
    return ["mount", "-o", f"remount,{options}", mountpoint]


def fstab_line(lv_path: str, mountpoint: str, options: str) -> str:
    return f"{lv_path} {mountpoint} ext4 {options} 0 2\n"


class VolumeInventoryParseError(ValueError):
    """Raised when a successful LVM command returned unusable inventory."""


def parse_logical_volumes(text: str) -> list:
    groups = []
    seen = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2:
            raise VolumeInventoryParseError(f"malformed LVM volume row: {line!r}")
        pair = (parts[0], parts[1])
        if pair in seen:
            raise VolumeInventoryParseError(f"duplicate LVM volume row: {pair!r}")
        seen.add(pair)
        groups.append(pair)
    return groups


def lv_exists(groups: list, *, vg_name: str, lv_name: str) -> bool:
    return (vg_name, lv_name) in groups


def parse_vg_free_bytes(text: str):
    text = text.strip()
    try:
        return int(text)
    except ValueError:
        return None


def _fstab_has_line(runner: Runner, line: str) -> bool:
    if not runner.path_exists(FSTAB_PATH):
        return False
    return line in runner.read_text(FSTAB_PATH)


def ensure_fstab_entry(runner: Runner, lv_path: str, mountpoint: str, options: str) -> None:
    """Idempotent: never duplicates an existing entry, so this is safe
    to call on every ensure_volume() run, not just the first."""
    line = fstab_line(lv_path, mountpoint, options)
    if not _fstab_has_line(runner, line):
        runner.append_text(FSTAB_PATH, line)


def ensure_mounted_with_options(runner: Runner, lv_path: str, mountpoint: str, options: str) -> bool:
    """Mount or refresh options; failures must reach the caller."""
    mount_proc = runner.run(mount_argv(lv_path, mountpoint, options=options), timeout=15)
    if mount_proc.returncode != 0:
        desired = runner.run(["blkid", "-s", "UUID", "-o", "value", lv_path], timeout=15)
        mounted = runner.run(["findmnt", "--mountpoint", mountpoint, "-n", "-o", "UUID"], timeout=15)
        if (desired.returncode != 0 or mounted.returncode != 0
                or not desired.stdout.strip() or len(desired.stdout.strip().splitlines()) != 1
                or desired.stdout.strip() != mounted.stdout.strip()):
            return False
        return runner.run(remount_argv(mountpoint, options), timeout=15).returncode == 0
    return True


# ---------------------------------------------------------------------------
# Runner-executed operations
# ---------------------------------------------------------------------------

# Names used before 2026-09-30, when "persistence" was dropped from every
# volume name (direct instruction). Volumes already provisioned or laid
# out under these names still exist on real disks - the Baseline drive with serial
# MD89N41071210AP4E carries them as GPT partition names - so they must be
# recognised, never silently treated as absent.
_LEGACY_LABEL_PREFIX = "USER_PERSISTENCE_"
_LEGACY_LV_PREFIX = "baseline_user_persistence_"
_LEGACY_EXACT = {
    "SUBSTRATE_PERSISTENCE": "SUBSTRATE",
    "USER_PERSISTENCE": "USER",
    "baseline_substrate_persistence": "baseline_substrate",
    "baseline_user_persistence": "baseline_user",
}


def canonical_name(name: str) -> str:
    """The current name for a label or LV name, old or new. Unrecognised
    names are returned unchanged."""
    if name in _LEGACY_EXACT:
        return _LEGACY_EXACT[name]
    if name.startswith(_LEGACY_LABEL_PREFIX):
        return "USER_" + name[len(_LEGACY_LABEL_PREFIX):]
    if name.startswith(_LEGACY_LV_PREFIX):
        return "baseline_user_" + name[len(_LEGACY_LV_PREFIX):]
    return name


def legacy_name(name: str) -> str | None:
    """The pre-2026-09-30 name for a current label or LV name, if it had
    a different one."""
    for old, new in _LEGACY_EXACT.items():
        if new == name:
            return old
    if name.startswith("USER_") and name != "USER":
        return _LEGACY_LABEL_PREFIX + name[len("USER_"):]
    if name.startswith("baseline_user_"):
        return _LEGACY_LV_PREFIX + name[len("baseline_user_"):]
    return None


def is_legacy_name(name: str) -> bool:
    return canonical_name(name) != name


def ensure_volume(runner: Runner, *, vg_name: str, lv_name: str, size: str,
                   label: str, mountpoint: str, wipe_stale_signatures: bool = False) -> CommandResult:
    """Idempotent: creates+formats+mounts `lv_name` only if it doesn't
    already exist. An already-existing volume is never reformatted -
    only (re-)mounted if not already mounted, so this is safe to run
    repeatedly, including as the update path."""
    proc = runner.run(list_logical_volumes_argv(), timeout=15)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"lvs exited {proc.returncode}")

    try:
        groups = parse_logical_volumes(proc.stdout)
    except VolumeInventoryParseError as exc:
        return CommandResult(False, str(exc))
    lv_path = f"/dev/{vg_name}/{lv_name}"
    options = mount_options_for(label)

    if lv_exists(groups, vg_name=vg_name, lv_name=lv_name):
        # A pre-existing mount may predate this fix (mounted plain, no
        # restrictive options) - ensure_mounted_with_options remounts
        # to actually apply them, not just record them for next boot.
        if not ensure_mounted_with_options(runner, lv_path, mountpoint, options):
            return CommandResult(False, f"mount failed on existing {lv_name}; not reformatted")
        ensure_fstab_entry(runner, lv_path, mountpoint, options)
        return CommandResult(True, f"{lv_name} already existed on {vg_name} - not reformatted", created=False)

    # The volume may exist under its pre-rename name. Creating the new
    # name beside it would give the person a second, empty volume and
    # split their data across two - so refuse, and leave the rename to an
    # explicit, operator-authorised step.
    old = legacy_name(lv_name)
    if old and lv_exists(groups, vg_name=vg_name, lv_name=old):
        return CommandResult(False, f"{old} exists on {vg_name}: this is {lv_name} under its "
                                    f"pre-rename name. Not creating a second volume - rename "
                                    f"it (lvrename + e2label) to adopt it.", created=False)

    create_proc = runner.run(create_logical_volume_argv(vg_name, lv_name, size,
                                                        wipe_stale_signatures=wipe_stale_signatures), timeout=30)
    if create_proc.returncode != 0:
        return CommandResult(False, f"lvcreate failed: {create_proc.stderr.strip()}")

    format_proc = runner.run(format_and_label_argv(lv_path, label), timeout=60)
    if format_proc.returncode != 0:
        return CommandResult(False, f"mkfs.ext4 failed on newly-created {lv_name}: {format_proc.stderr.strip()}")

    runner.run(makedirs_argv(mountpoint), timeout=10)
    mount_proc = runner.run(mount_argv(lv_path, mountpoint, options=options), timeout=15)
    if mount_proc.returncode != 0:
        return CommandResult(False, f"mount failed on newly-created {lv_name}: {mount_proc.stderr.strip()}")

    ensure_fstab_entry(runner, lv_path, mountpoint, options)
    return CommandResult(True, f"{lv_name} created, formatted {label}, mounted at {mountpoint}", created=True)


def detect_existing_baseline_install(runner: Runner, *, vg_name: str = DEFAULT_VG_NAME,
                                      personas: tuple = DEFAULT_PERSONAS) -> dict:
    """Real auto-detection: does `vg_name` already have every volume
    for `personas` provisioned (the three shared volumes plus one
    USER_<PERSONA> per persona)? Reuses the exact same
    `lvs` parsing ensure_volume() already uses, rather than a second
    detection mechanism that could drift out of sync with it. "Existing
    install" means ALL are present; a target with none or only some is
    reported honestly as not-yet-fully-installed - ensure_baseline_volumes()
    already creates whatever's missing regardless of this function's
    own answer, so a partial state is never blocked, only surfaced."""
    volumes = baseline_volumes_for(personas)
    proc = runner.run(list_logical_volumes_argv(), timeout=15)
    if proc.returncode != 0:
        all_names = [lv_name for lv_name, _, _, _, _ in volumes]
        return {"has_existing_install": False, "found_volumes": [], "missing_volumes": all_names,
                "error": proc.stderr.strip() or f"lvs exited {proc.returncode}"}

    try:
        groups = parse_logical_volumes(proc.stdout)
    except VolumeInventoryParseError as exc:
        all_names = [lv_name for lv_name, _, _, _, _ in volumes]
        return {"has_existing_install": False, "found_volumes": [], "missing_volumes": all_names,
                "error": str(exc)}
    found = [lv_name for lv_name, _, _, _, _ in volumes
             if lv_exists(groups, vg_name=vg_name, lv_name=lv_name)]
    # Present only under the pre-rename name: neither missing nor current.
    legacy = {lv_name: legacy_name(lv_name) for lv_name, _, _, _, _ in volumes
              if lv_name not in found and legacy_name(lv_name)
              and lv_exists(groups, vg_name=vg_name, lv_name=legacy_name(lv_name))}
    missing = [lv_name for lv_name, _, _, _, _ in volumes if lv_name not in found and lv_name not in legacy]
    return {"has_existing_install": not missing and not legacy, "found_volumes": found,
            "missing_volumes": missing, "legacy_named_volumes": legacy}


DEFAULT_SAFETY_MARGIN_BYTES = 1 * (1024 ** 3)  # never claim the last GiB of free space
DEFAULT_GROWTH_PERCENT = 20


def single_drive_plan(size_bytes: int, *, host_bytes: int,
                      personas: tuple = DEFAULT_PERSONAS,
                      growth_percent: int = DEFAULT_GROWTH_PERCENT,
                      migration_bytes: int = 0,
                      required_bytes: dict | None = None, baseline_min_gib: int = 5,
                      grow_on_demand: bool = False) -> dict:
    """Budget one complete installation, without reallocating existing contents.

    `grow_on_demand` (operator, 2026-10-11: "1 GB each volume only grows if actually used and needed"): every role starts at its measured
    need, never below 1 GiB, and the rest of the drive stays free in the volume group for volume_growth.py to hand out when a role fills.
    The role minimums and the proportional split do not apply. Without it the behaviour is exactly the earlier fixed-minimum plan.

    host_bytes includes EFI/boot, root/swap, OS pool and its metadata. Callers
    must supply measured/reserved physical bytes, never thin logical capacity.
    migration_bytes is extra concurrent staging, not the source data counted
    in destination volume requirements. This function performs no I/O.
    """
    for name, value in (("size_bytes", size_bytes), ("host_bytes", host_bytes),
                        ("migration_bytes", migration_bytes)):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be known nonnegative integer bytes")
    if type(growth_percent) is not int or not 0 <= growth_percent <= 50:
        raise ValueError("growth_percent must be an integer from 0 to 50")
    growth_bytes = (size_bytes * growth_percent + 99) // 100
    if grow_on_demand:
        return _grow_on_demand_plan(size_bytes, host_bytes, growth_bytes, migration_bytes, personas, required_bytes)
    available = size_bytes - host_bytes - growth_bytes - migration_bytes
    if type(baseline_min_gib) is not int or not 5 <= baseline_min_gib <= 4096:
        raise ValueError("BASELINE runtime reservation must be between 5 and 4096 GiB")
    volumes = tuple((name, max(lo, baseline_min_gib) if label == "BASELINE" else lo,
                     max(hi, baseline_min_gib) if label == "BASELINE" else hi, label, path)
                    for name, lo, hi, label, path in baseline_volumes_for(personas))
    if required_bytes is not None:
        if not isinstance(required_bytes, dict) or set(required_bytes) != {v[3] for v in volumes}:
            raise ValueError("required_bytes must measure every storage role exactly once")
        for value in required_bytes.values():
            if type(value) is not int or value < 0:
                raise ValueError("required_bytes must contain known nonnegative integer bytes")
        volumes = tuple((name, max(lo, (required_bytes[label] + 1024**3 - 1) // 1024**3),
                         max(hi, (required_bytes[label] + 1024**3 - 1) // 1024**3), label, path)
                        for name, lo, hi, label, path in volumes)
    sizes = compute_adaptive_plan(max(available, 0), volumes)
    if not sizes or not all(sizes.values()):
        raise ValueError("one drive cannot fit host storage, every role's minimum, growth and migration staging; "
                         "measure suitable slower storage for cold vanilla sources and infrequent templates first")
    return {"volumes_gib": sizes, "host_bytes": host_bytes,
            "growth_bytes": growth_bytes, "migration_bytes": migration_bytes,
            "safety_bytes": DEFAULT_SAFETY_MARGIN_BYTES,
            "unallocated_bytes": size_bytes - host_bytes - migration_bytes - sum(sizes.values()) * 1024**3,
            "capacity_basis": "measured-workload" if required_bytes is not None else "role-minimums",
            "executed": False}


def _grow_on_demand_plan(size_bytes, host_bytes, growth_bytes, migration_bytes, personas, required_bytes):
    labels = [v[3] for v in baseline_volumes_for(personas)]
    if required_bytes is not None and (not isinstance(required_bytes, dict) or set(required_bytes) != set(labels)
                                       or any(type(v) is not int or v < 0 for v in required_bytes.values())):
        raise ValueError("required_bytes must measure every storage role exactly once")
    gib = 1024 ** 3
    sizes = {label: max(1, -(-(required_bytes or {}).get(label, 0) // gib)) for label in labels}
    needed = host_bytes + growth_bytes + migration_bytes + DEFAULT_SAFETY_MARGIN_BYTES + sum(sizes.values()) * gib
    if size_bytes < needed:
        raise ValueError("one drive cannot fit host storage, every role's minimum, growth and migration staging; "
                         "measure suitable slower storage for cold vanilla sources and infrequent templates first")
    return {"volumes_gib": sizes, "host_bytes": host_bytes,
            "growth_bytes": growth_bytes, "migration_bytes": migration_bytes,
            "safety_bytes": DEFAULT_SAFETY_MARGIN_BYTES,
            "unallocated_bytes": size_bytes - host_bytes - migration_bytes - sum(sizes.values()) * gib,
            "capacity_basis": "grow-on-demand",
            "executed": False}


def adaptive_single_size_gb(free_bytes: int, desired_gb: int, *,
                             safety_margin_bytes: int = DEFAULT_SAFETY_MARGIN_BYTES,
                             min_gb: int = 1) -> int:
    """"There are no immutable volumes, only reasons why things should
    change or not change them" - `desired_gb` is a reasoned default,
    never a hard requirement. Returns it unchanged when real free
    space comfortably covers it; otherwise scales down to whatever is
    actually usable (never claiming the safety margin); returns 0 only
    when truly nothing usable remains, for the caller to handle."""
    usable_bytes = max(free_bytes - safety_margin_bytes, 0)
    usable_gb = usable_bytes // (1024 ** 3)
    if usable_gb >= desired_gb:
        return desired_gb
    return int(usable_gb) if usable_gb >= min_gb else 0


def compute_adaptive_plan(free_bytes: int, volumes=BASELINE_VOLUMES, *,
                           safety_margin_bytes: int = DEFAULT_SAFETY_MARGIN_BYTES) -> dict:
    """Real available space always wins, but only ever between each
    volume's own (min_gb, max_gb) range (direct instruction, 2026-09-29
    - replaces the old single-"desired size" model). Every volume gets
    its min_gb first; this refuses outright (every volume 0) only if
    real free space can't even cover every volume's minimum combined -
    never partial minimums. Whatever space remains above that combined
    minimum is then handed out proportionally to each volume's own
    room-to-grow (`max_gb - min_gb`), capped at that volume's own
    max_gb - a volume already at its cap takes no more. This is a
    single proportional pass, not a perfect bin-packing solve: if one
    volume hits its cap early, the space it couldn't take is not
    redistributed to the others in this pass - a real, documented
    imprecision, not silently pretended away."""
    mins = {label: min_gb for _, min_gb, _, label, _ in volumes}
    maxs = {label: max_gb for _, _, max_gb, label, _ in volumes}
    total_min_gb = sum(mins.values())

    usable_bytes = max(free_bytes - safety_margin_bytes, 0)
    usable_gb = usable_bytes // (1024 ** 3)

    if usable_gb < total_min_gb:
        return {label: 0 for label in mins}

    plan = dict(mins)
    remaining_gb = usable_gb - total_min_gb
    room = {label: maxs[label] - mins[label] for label in mins}
    total_room = sum(room.values())
    if remaining_gb <= 0 or total_room <= 0:
        return plan

    for label in plan:
        if room[label] <= 0:
            continue
        share = int(remaining_gb * room[label] / total_room)
        plan[label] = min(maxs[label], plan[label] + share)
    return plan


def ensure_baseline_volumes(runner: Runner, *, vg_name: str = DEFAULT_VG_NAME,
                             personas: tuple = DEFAULT_PERSONAS,
                             planned_sizes_gib: dict | None = None,
                             reserve_bytes: int = 0, wipe_stale_signatures: bool = False) -> dict:
    """The top-level, idempotent entry point: ensures the three shared
    volumes plus one USER_<PERSONA> volume per `personas`
    all exist on `vg_name`, sizing them adaptively to whatever real
    free space actually exists (decision record 73) rather than
    refusing outright when the fixed defaults don't fit. Additional
    opt-in personas beyond the default admin+personal pass their own
    `personas` tuple - never touches boot/EFI partitions or any
    existing logical volume, only ever creates what's missing."""
    volumes = baseline_volumes_for(personas)

    free_proc = runner.run(vg_free_bytes_argv(vg_name), timeout=15)
    if free_proc.returncode != 0:
        detail = free_proc.stderr.strip() or f"vgs exited {free_proc.returncode}"
        return {label: CommandResult(False, detail) for _, _, _, label, _ in volumes}

    free_bytes = parse_vg_free_bytes(free_proc.stdout)
    if free_bytes is None:
        return {label: CommandResult(False, f"could not determine free space in VG {vg_name!r}")
                for _, _, _, label, _ in volumes}

    if type(reserve_bytes) is not int or reserve_bytes < 0:
        return {v[3]: CommandResult(False, "reserve_bytes must be known nonnegative integer bytes") for v in volumes}
    if planned_sizes_gib is not None:
        if (not isinstance(planned_sizes_gib, dict)
                or set(planned_sizes_gib) != {v[3] for v in volumes}
                or any(type(planned_sizes_gib[v[3]]) is not int or planned_sizes_gib[v[3]] < v[1] for v in volumes)):
            return {v[3]: CommandResult(False, "single-drive sizes must cover every role at its minimum") for v in volumes}
        inventory = runner.run(list_logical_volume_sizes_argv(vg_name), timeout=15)
        if inventory.returncode != 0:
            return {v[3]: CommandResult(False, "could not inspect existing LV capacity") for v in volumes}
        rows = [row.split() for row in inventory.stdout.splitlines() if row.strip()]
        if (any(len(row) != 2 or not row[1].isdigit() for row in rows)
                or len({row[0] for row in rows}) != len(rows)):
            return {v[3]: CommandResult(False, "malformed or ambiguous LV capacity inventory") for v in volumes}
        existing = parse_logical_volume_sizes(inventory.stdout)
        undersized = [v[3] for v in volumes if v[0] in existing
                      and existing[v[0]] < planned_sizes_gib[v[3]] * 1024**3]
        if undersized:
            return {v[3]: CommandResult(False, "existing roles are smaller than the profile: " + ", ".join(undersized)) for v in volumes}
        required = sum(planned_sizes_gib[v[3]] for v in volumes if v[0] not in existing) * 1024**3 + reserve_bytes
        if required > free_bytes:
            return {v[3]: CommandResult(False, f"insufficient physical VG free space for the single-drive profile and reserve: "
                                       f"{required} needed, {free_bytes} available") for v in volumes}
        plan_gb = dict(planned_sizes_gib)
    else:
        plan_gb = compute_adaptive_plan(max(free_bytes - reserve_bytes, 0), volumes)

    results = {}
    for lv_name, _min_gb, _max_gb, label, mountpoint in volumes:
        size_gb = plan_gb[label]
        if size_gb <= 0:
            results[label] = CommandResult(
                False, f"insufficient free space in VG {vg_name!r} for {label} - "
                       f"{free_bytes} bytes free, adaptive plan gave 0G real usable space")
            continue
        results[label] = ensure_volume(runner, vg_name=vg_name, lv_name=lv_name,
                                        size=f"{size_gb}G", label=label, mountpoint=mountpoint,
                                        wipe_stale_signatures=wipe_stale_signatures)
    return results


# ---------------------------------------------------------------------------
# Per-volume telemetry (real follow-up work, decision record 71) - real
# `df` output, not a second lvs-based estimate that could drift from
# what's actually mounted. Feeds sensors_collect.py's existing 30s
# collection cycle/store rather than building a separate one.
# ---------------------------------------------------------------------------

@dataclass
class VolumeUsage:
    label: str
    mountpoint: str
    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent_used: float


def df_argv(mountpoint: str) -> list:
    return ["df", "-B1", "--output=size,used,avail,pcent", mountpoint]


def parse_findmnt_targets(text: str) -> set[str]:
    """Parse findmnt's JSON mount tree; a failed observation is never empty."""
    try:
        document = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise VolumeObservationError("findmnt returned invalid JSON") from exc
    if not isinstance(document, dict) or not isinstance(document.get("filesystems"), list):
        raise VolumeObservationError("findmnt output has no filesystems list")
    targets = set()
    pending = list(document["filesystems"])
    while pending:
        item = pending.pop()
        if not isinstance(item, dict):
            raise VolumeObservationError("findmnt returned a malformed filesystem record")
        target = item.get("target")
        if not isinstance(target, str) or not target.startswith("/"):
            raise VolumeObservationError("findmnt returned a filesystem without an absolute target")
        targets.add(target)
        children = item.get("children", [])
        if not isinstance(children, list):
            raise VolumeObservationError("findmnt returned malformed filesystem children")
        pending.extend(children)
    return targets


def parse_df_output(text: str):
    """Parses `df -B1 --output=size,used,avail,pcent`'s two-line
    output. Returns None for anything that isn't real, complete df
    output (empty, header-only, malformed) rather than guessing."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    parts = lines[1].split()
    if len(parts) < 4:
        return None
    try:
        total, used, avail = int(parts[0]), int(parts[1]), int(parts[2])
        percent = float(parts[3].rstrip("%"))
    except ValueError:
        return None
    return {"total_bytes": total, "used_bytes": used, "available_bytes": avail, "percent_used": percent}


def list_logical_volume_sizes_argv(vg_name: str = DEFAULT_VG_NAME) -> list:
    """`sudo -n` - see `list_logical_volumes_argv`'s own docstring for
    why a real-only-read LVM inspection call needs this."""
    return ["sudo", "-n", "lvs", "--noheadings", "--units", "b", "--nosuffix", "-o", "lv_name,lv_size", vg_name]


def parse_logical_volume_sizes(text: str) -> dict:
    """Maps lv_name -> real allocated size in bytes, from `lvs`'s own
    output - the real, current LV size (what was actually created),
    never the (min_gb, max_gb) plan values, which are only ever a
    request made *before* creation."""
    sizes = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2:
            raise VolumeInventoryParseError(f"malformed LVM size row: {line!r}")
        if parts[0] in sizes:
            raise VolumeInventoryParseError(f"duplicate LVM size row for {parts[0]!r}")
        try:
            size = int(parts[1])
        except ValueError as exc:
            raise VolumeInventoryParseError(f"invalid LVM size for {parts[0]!r}: {parts[1]!r}") from exc
        if size < 0:
            raise VolumeInventoryParseError(f"negative LVM size for {parts[0]!r}")
        sizes[parts[0]] = size
    return sizes


@dataclass
class VolumeDetail:
    """Real, complete per-volume identity - direct feedback: the web
    page's own volume table showed raw byte counts with no partition/
    LV name at all, "makes no sense." `lv_name`/`lv_size_bytes` are the
    real underlying LVM identity (what an operator would see running
    `lvs` themselves); `total_bytes`/`used_bytes`/`percent_used` are
    only populated when the volume is actually mounted right now (a
    real, existing-but-unmounted LV still gets a `VolumeDetail`, with
    those three left `None` rather than guessed)."""
    label: str
    mountpoint: str
    lv_name: str
    lv_exists: bool
    lv_size_bytes: int | None
    total_bytes: int | None
    used_bytes: int | None
    percent_used: float | None


class VolumeObservationError(RuntimeError):
    """LVM inventory failed; it must not be rendered as an empty volume plan."""


def _run_volume_query(runner: Runner, argv: list, *, label: str) -> str:
    try:
        proc = runner.run(argv, timeout=15)
    except Exception as exc:
        raise VolumeObservationError(f"{label} probe unavailable: {type(exc).__name__}: {exc}") from exc
    code = getattr(proc, "returncode", 1)
    if code != 0:
        detail = getattr(proc, "stderr", "") or f"exit {code}"
        raise VolumeObservationError(f"{label} probe failed: {detail.strip()}")
    output = getattr(proc, "stdout", None)
    if not isinstance(output, str):
        raise VolumeObservationError(f"{label} output unavailable")
    return output


def collect_volume_details(runner: Runner, *, vg_name: str = DEFAULT_VG_NAME,
                            personas: tuple = DEFAULT_PERSONAS) -> list:
    """One real row per volume this project would ever create for
    `personas` on `vg_name` - present whether or not it's been created
    yet (`lv_exists=False`, everything else `None`), so the web page
    can show the real, complete plan, not just whatever happens to be
    mounted right now (real gap `real_volume_state` had before this)."""
    volumes = baseline_volumes_for(personas)

    lvs_output = _run_volume_query(runner, list_logical_volumes_argv(), label="LVM volume list")
    try:
        groups = parse_logical_volumes(lvs_output)
    except VolumeInventoryParseError as exc:
        raise VolumeObservationError(f"LVM volume list is malformed: {exc}") from exc

    sizes_output = _run_volume_query(runner, list_logical_volume_sizes_argv(vg_name), label="LVM volume sizes")
    sizes = parse_logical_volume_sizes(sizes_output)

    usage_by_label = {u.label: u for u in collect_volume_usage(runner, personas=personas)}

    results = []
    for lv_name, _min_gb, _max_gb, label, mountpoint in volumes:
        exists = lv_exists(groups, vg_name=vg_name, lv_name=lv_name)
        usage = usage_by_label.get(label)
        results.append(VolumeDetail(
            label=label, mountpoint=mountpoint, lv_name=lv_name, lv_exists=exists,
            lv_size_bytes=sizes.get(lv_name) if exists else None,
            total_bytes=usage.total_bytes if usage else None,
            used_bytes=usage.used_bytes if usage else None,
            percent_used=usage.percent_used if usage else None,
        ))
    return results


def collect_volume_usage(runner: Runner, *, personas: tuple = DEFAULT_PERSONAS) -> list:
    """Real per-volume usage for every shared volume plus one
    USER_<PERSONA> per `personas`, for whichever
    mountpoints are actually mounted right now - never assumes
    ensure_baseline_volumes() has run. findmnt distinguishes a volume
    that is not mounted from df failing on a confirmed mount; the latter
    remains an observation error rather than disappearing from the page."""
    mount_output = _run_volume_query(
        runner, ["findmnt", "--json", "--output", "TARGET"], label="mount table")
    mounted_targets = parse_findmnt_targets(mount_output)
    results = []
    for _, _, _, label, mountpoint in baseline_volumes_for(personas):
        if mountpoint not in mounted_targets:
            continue
        output = _run_volume_query(runner, df_argv(mountpoint), label=f"df {mountpoint}")
        parsed = parse_df_output(output)
        if parsed is None:
            raise VolumeObservationError(f"df {mountpoint} returned incomplete usage output")
        results.append(VolumeUsage(label=label, mountpoint=mountpoint, **parsed))
    return results


# ---------------------------------------------------------------------------
# BASELINE -> INSTALLER_CACHE seeding (decision record 76) - "make
# BASELINE the first thing added into the installer_Cache": a self-
# installing drive bootstraps INSTALLER_CACHE with a real backup of
# BASELINE's own current content, established as the first artifact
# it holds. Reuses backup_restore.create_backup directly rather than
# a second tar-invocation path.
# ---------------------------------------------------------------------------

def seed_installer_cache_with_baseline(runner: Runner, *, now: float,
                                        installer_cache_mountpoint: str = "/mnt/INSTALLER_CACHE",
                                        baseline_mountpoint: str = "/mnt/BASELINE"):
    import backup_restore
    dest = f"{installer_cache_mountpoint}/seed/baseline-seed.tar.gz"
    return backup_restore.create_backup(runner, dest_path=dest, targets=[baseline_mountpoint], now=now)
