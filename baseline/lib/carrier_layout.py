"""Lay Baseline's own defined volumes onto a plain-GPT carrier drive.

The volume set, sizing and mount options all come from `drive_installer`
(SHARED_VOLUMES, persona volumes, compute_adaptive_plan, MOUNT_OPTIONS); this
module only turns that plan into partitions, the way decision record 46 did on
this drive: GPT partitions named for the volume, ext4 inside, no LVM, no root.
Every destructive step is gated by `physical_device_safety.validate_target_device`
(decision record 49) and goes through an injected runner, so the tests never
touch a device.

ext4 labels are at most 16 characters and three Baseline labels are longer
(USER_PERSISTENCE_ADMIN / _PERSONAL would both truncate to USER_PERSISTENCE), so
the full GPT partition name is the identity and the ext4 label is a truncation.
"""
from __future__ import annotations

import drive_installer as di
from physical_device_safety import PhysicalDeviceSafetyError, validate_target_device

__all__ = ["PhysicalDeviceSafetyError", "LayoutError", "plan_partitions", "sgdisk_argv",
           "mkfs_argv", "apply", "agent_index", "debugfs_write_argv"]

_SECTOR = 512
_ALIGN_SECTORS = 2048  # 1 MiB
_FIRST_SECTOR = 2048
_GIB_SECTORS = 1024**3 // _SECTOR
_EXT4_LABEL_MAX = 16
_GPT_LINUX_FS = "8300"
_MIN_DRIVE_BYTES = 100 * 1024**3

_ROLES = {
    "BASELINE": "Application, VM and LXC state for this Baseline install.",
    "INSTALLER_CACHE": "ISOs, driver packages and backups (ISO at isos/proxmox-ve-source.iso, backups/, encrypted_backups/, backup_manifests/). Consumed by name, never executed.",
    "SESSION_TEMP": "Ephemeral session data and quarantine for anything not yet triaged. Never anything meant to run.",
    "SUBSTRATE_PERSISTENCE": "Small, security-relevant recovery and substrate configuration, including the encrypted admin installer/recovery passphrase. Fixed 1 GB.",
}


class LayoutError(RuntimeError):
    pass


def _role(label: str) -> str:
    if di.is_persistence_label(label):
        persona = label.removeprefix("USER_PERSISTENCE_").lower()
        return f"Isolated persistence for the '{persona}' persona (scripts inbox lives here; it may hold executables)."
    return _ROLES[label]


def plan_partitions(size_bytes: int, personas: tuple = di.DEFAULT_PERSONAS) -> list[dict]:
    volumes = di.baseline_volumes_for(personas)
    sizes = di.compute_adaptive_plan(size_bytes - di.DEFAULT_SAFETY_MARGIN_BYTES, volumes)
    if not any(sizes.values()):
        raise ValueError("drive is too small for every Baseline volume's minimum size")
    plan, start = [], _FIRST_SECTOR
    for number, (_lv, _lo, _hi, label, mountpoint) in enumerate(volumes, start=1):
        gb = sizes[label]
        plan.append({
            "number": number, "label": label, "partname": label, "fs_label": label[:_EXT4_LABEL_MAX],
            "size_gb": gb, "start_sector": start, "mountpoint": mountpoint,
            "options": di.mount_options_for(label),
        })
        start += gb * _GIB_SECTORS
        assert start % _ALIGN_SECTORS == 0
    return plan


def sgdisk_argv(device: str, plan: list[dict]) -> list[str]:
    argv = ["sgdisk"]
    for p in plan:
        argv += ["-n", f"{p['number']}:{p['start_sector']}:+{p['size_gb']}G",
                 "-t", f"{p['number']}:{_GPT_LINUX_FS}", "-c", f"{p['number']}:{p['partname']}"]
    return argv + [device]


def mkfs_argv(device: str, p: dict) -> list[str]:
    """Format by byte offset into the whole-disk device: works without root,
    because the kernel re-reading the new table (partprobe) is what needs it."""
    return ["mkfs.ext4", "-F", "-q", "-L", p["fs_label"],
            "-E", f"offset={p['start_sector'] * _SECTOR}", device, f"{p['size_gb'] * 1024 * 1024}k"]


def apply(cmd, path: str, *, validate=validate_target_device, expected_serial=None,
          min_size_bytes: int = _MIN_DRIVE_BYTES, personas: tuple = di.DEFAULT_PERSONAS) -> list[dict]:
    validated = validate(path, expected_serial=expected_serial, min_size_bytes=min_size_bytes)
    plan = plan_partitions(validated["size_bytes"], personas)
    steps = [["wipefs", "-a", validated["path"]], ["sgdisk", "-Z", validated["path"]],
             sgdisk_argv(validated["path"], plan)] + [mkfs_argv(validated["path"], p) for p in plan]
    for argv in steps:
        rc, _out, err = cmd.run(argv)
        if rc != 0:
            raise LayoutError(f"{argv[0]} failed (rc={rc}): {err.strip()}")
    return plan


def agent_index(p: dict, *, serial: str) -> str:
    noexec = "noexec" in p["options"]
    return f"""# agentIndex.md - {p['label']}

Read this first. It tells an AI agent or operator what this Baseline volume is and what it may hold.

- **Volume:** `{p['label']}` (GPT partition {p['number']}, ext4 label `{p['fs_label']}`), planned {p['size_gb']} GB.
- **Role:** {_role(p['label'])}
- **Mountpoint:** `{p['mountpoint']}` with options `{p['options']}`{' (nothing on this volume is ever executed directly)' if noexec else ''}.
- **Drive:** serial `{serial}`. Find it by `/dev/disk/by-id`, never by kernel letter (letters shift between boots).
- **Defined in:** `baseline/lib/drive_installer.py` (volume set, sizing, mount options) and laid out by `baseline/lib/carrier_layout.py`.

## Rules for agents

1. Verify the drive serial before any write; stop if it does not match.
2. Never touch another drive. Identify this volume by partition name `{p['partname']}`, not by the ext4 label (labels are truncated to 16 characters).
3. Changes to the volume layout go through `drive_installer` / `carrier_layout` with tests first (decision record 49), never ad hoc commands.
"""


def debugfs_write_argv(device: str, p: dict, src: str, dest: str = "agentIndex.md") -> list[str]:
    return ["debugfs", "-w", "-R", f"write {src} {dest}", f"{device}?offset={p['start_sector'] * _SECTOR}"]
