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
mistake**: `BASELINE`/`USER_PERSISTENCE`/`INSTALLER_CACHE`/
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

from dataclasses import dataclass

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError


DEFAULT_VG_NAME = "pve"

# name, size, GPT/ext4 label, mountpoint - the four real volumes this
# session's own decision records 46-49 (USER_PERSISTENCE/INSTALLER_CACHE/
# SESSION_TEMP) and 68 (BASELINE) settled on. BASELINE holds
# application/VM/LXC state changes - separate from USER_PERSISTENCE
# (credentials/config/logs, meant to survive a reinstall) and from the
# disposable substrate itself (Proxmox's own root LV, wiped by any
# fresh install) - a real, persistent-but-app-scoped location, not
# something a fresh install would already imply.
BASELINE_VOLUMES = (
    ("baseline_app_state", "200G", "BASELINE", "/mnt/BASELINE"),
    ("baseline_user_persistence", "300G", "USER_PERSISTENCE", "/mnt/USER_PERSISTENCE"),
    ("baseline_installer_cache", "100G", "INSTALLER_CACHE", "/mnt/INSTALLER_CACHE"),
    ("baseline_session_temp", "50G", "SESSION_TEMP", "/mnt/SESSION_TEMP"),
)

# Per-role mount restrictions (real follow-up work, decision record
# 71): nosuid+nodev everywhere - none of these volumes should ever
# host a setuid binary or a device node. noexec additionally on
# SESSION_TEMP (pure ephemeral session data - never anything meant to
# run) and INSTALLER_CACHE (holds ISOs/driver packages, consumed by
# name via dpkg/mount/xorriso, never executed directly). Not on
# USER_PERSISTENCE - it holds the scripts inbox, and an operator may
# reasonably chmod +x and run a pushed script directly from there. Not
# on BASELINE - app/VM/LXC state may legitimately need to execute
# things it stores.
MOUNT_OPTIONS = {
    "BASELINE": "defaults,nosuid,nodev",
    "USER_PERSISTENCE": "defaults,nosuid,nodev",
    "INSTALLER_CACHE": "defaults,nosuid,nodev,noexec",
    "SESSION_TEMP": "defaults,nosuid,nodev,noexec",
}

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
    return ["lvs", "--noheadings", "-o", "vg_name,lv_name"]


def vg_free_bytes_argv(vg_name: str) -> list:
    return ["vgs", "--noheadings", "--units", "b", "--nosuffix", "-o", "vg_free", vg_name]


def create_logical_volume_argv(vg_name: str, lv_name: str, size: str) -> list:
    return ["lvcreate", "-n", lv_name, "-L", size, vg_name]


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


def parse_logical_volumes(text: str) -> list:
    groups = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            groups.append((parts[0], parts[1]))
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


def ensure_mounted_with_options(runner: Runner, lv_path: str, mountpoint: str, options: str) -> None:
    """Best-effort: mounts fresh with the real role options if not
    already mounted; if already mounted (the plain mount attempt fails
    for exactly that reason), remounts to apply/refresh the options on
    a pre-existing mount instead of leaving it with stale or absent
    ones. Never raises - matches this module's own existing tolerance
    for "already mounted" being a normal, expected outcome."""
    mount_proc = runner.run(mount_argv(lv_path, mountpoint, options=options), timeout=15)
    if mount_proc.returncode != 0:
        runner.run(remount_argv(mountpoint, options), timeout=15)


# ---------------------------------------------------------------------------
# Runner-executed operations
# ---------------------------------------------------------------------------

def ensure_volume(runner: Runner, *, vg_name: str, lv_name: str, size: str,
                   label: str, mountpoint: str) -> CommandResult:
    """Idempotent: creates+formats+mounts `lv_name` only if it doesn't
    already exist. An already-existing volume is never reformatted -
    only (re-)mounted if not already mounted, so this is safe to run
    repeatedly, including as the update path."""
    proc = runner.run(list_logical_volumes_argv(), timeout=15)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"lvs exited {proc.returncode}")

    groups = parse_logical_volumes(proc.stdout)
    lv_path = f"/dev/{vg_name}/{lv_name}"
    options = MOUNT_OPTIONS.get(label, "defaults")

    if lv_exists(groups, vg_name=vg_name, lv_name=lv_name):
        # A pre-existing mount may predate this fix (mounted plain, no
        # restrictive options) - ensure_mounted_with_options remounts
        # to actually apply them, not just record them for next boot.
        ensure_mounted_with_options(runner, lv_path, mountpoint, options)
        ensure_fstab_entry(runner, lv_path, mountpoint, options)
        return CommandResult(True, f"{lv_name} already existed on {vg_name} - not reformatted", created=False)

    create_proc = runner.run(create_logical_volume_argv(vg_name, lv_name, size), timeout=30)
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


def detect_existing_baseline_install(runner: Runner, *, vg_name: str = DEFAULT_VG_NAME) -> dict:
    """Real auto-detection: does `vg_name` already have the three
    BASELINE_VOLUMES provisioned? Reuses the exact same `lvs` parsing
    ensure_volume() already uses, rather than a second detection
    mechanism that could drift out of sync with it. "Existing install"
    means ALL three are present; a target with none or only some is
    reported honestly as not-yet-fully-installed - ensure_baseline_volumes()
    already creates whatever's missing regardless of this function's
    own answer, so a partial state is never blocked, only surfaced."""
    proc = runner.run(list_logical_volumes_argv(), timeout=15)
    if proc.returncode != 0:
        all_names = [lv_name for lv_name, _, _, _ in BASELINE_VOLUMES]
        return {"has_existing_install": False, "found_volumes": [], "missing_volumes": all_names,
                "error": proc.stderr.strip() or f"lvs exited {proc.returncode}"}

    groups = parse_logical_volumes(proc.stdout)
    found = [lv_name for lv_name, _, _, _ in BASELINE_VOLUMES
             if lv_exists(groups, vg_name=vg_name, lv_name=lv_name)]
    missing = [lv_name for lv_name, _, _, _ in BASELINE_VOLUMES if lv_name not in found]
    return {"has_existing_install": len(missing) == 0, "found_volumes": found, "missing_volumes": missing}


def ensure_baseline_volumes(runner: Runner, *, vg_name: str = DEFAULT_VG_NAME) -> dict:
    """The top-level, idempotent entry point: ensures USER_PERSISTENCE/
    INSTALLER_CACHE/SESSION_TEMP all exist on `vg_name`, checking real
    free space first and refusing (not guessing, not shrinking
    anything) if there isn't enough. Never touches boot/EFI partitions
    or any existing logical volume - only ever creates what's missing."""
    total_needed_gb = sum(int(size.rstrip("G")) for _, size, _, _ in BASELINE_VOLUMES)

    free_proc = runner.run(vg_free_bytes_argv(vg_name), timeout=15)
    if free_proc.returncode != 0:
        detail = free_proc.stderr.strip() or f"vgs exited {free_proc.returncode}"
        return {label: CommandResult(False, detail) for _, _, label, _ in BASELINE_VOLUMES}

    free_bytes = parse_vg_free_bytes(free_proc.stdout)
    needed_bytes = total_needed_gb * (1024 ** 3)
    if free_bytes is None or free_bytes < needed_bytes:
        detail = (f"insufficient free space in VG {vg_name!r}: "
                  f"{free_bytes if free_bytes is not None else 'unknown'} bytes free, "
                  f"need at least {needed_bytes} bytes for all three volumes")
        return {label: CommandResult(False, detail) for _, _, label, _ in BASELINE_VOLUMES}

    results = {}
    for lv_name, size, label, mountpoint in BASELINE_VOLUMES:
        results[label] = ensure_volume(runner, vg_name=vg_name, lv_name=lv_name,
                                        size=size, label=label, mountpoint=mountpoint)
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


def collect_volume_usage(runner: Runner) -> list:
    """Real per-volume usage for every BASELINE_VOLUMES mountpoint that
    is actually mounted right now - never assumes
    ensure_baseline_volumes() has run; a volume that isn't mounted
    (df fails) is skipped, not an error, matching diagnostics.py's own
    tolerance for missing hardware/tools."""
    results = []
    for _, _, label, mountpoint in BASELINE_VOLUMES:
        proc = runner.run(df_argv(mountpoint), timeout=10)
        if proc.returncode != 0:
            continue
        parsed = parse_df_output(proc.stdout)
        if parsed is None:
            continue
        results.append(VolumeUsage(label=label, mountpoint=mountpoint, **parsed))
    return results
