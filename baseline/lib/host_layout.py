"""The host's own volumes expressed in the agreed role names (DR257).

Proxmox's installer creates `swap` as a volume of its own. The agreed layout has no such volume: swap space lives in SESSION_TEMP. This module
moves it: a swap file is created in SESSION_TEMP (the volume is grown first, from the volume group's free space), switched on, and only then
is the old swap volume switched off, removed and dropped from fstab, so the host never runs without swap in between and a failure before the
last step leaves the old swap in place. Every step checks the current state first, so a rerun completes what is missing.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import volume_growth

GIB = 1024 ** 3
SWAP_FILE = "/mnt/SESSION_TEMP/swapfile"
SWAP_SIZE_GIB = 4
FSTAB = "/etc/fstab"
POOL_NAME = "baseline_session_temp_pool"       # Proxmox's `data` thin pool, renamed: the pool is SESSION_TEMP's (DR257)
GUEST_STORAGE = "session-temp"                 # the Proxmox storage id for VM and container disks (it was `local-lvm`)
LVM_LOCAL_CONF = "/etc/lvm/lvmlocal.conf"
AUTOEXTEND = """# Baseline (DR257): extend the SESSION_TEMP thin pool from the volume group's free space before it fills.
activation {
    thin_pool_autoextend_threshold = 80
    thin_pool_autoextend_percent = 20
}
"""


class LayoutError(RuntimeError):
    pass


def fstab_without_swap_volume(text: str, vg: str) -> str:
    """fstab with the line that mounts /dev/<vg>/swap removed (everything else, including comments, unchanged)."""
    drop = {f"/dev/{vg}/swap", f"/dev/mapper/{vg}-swap"}
    lines = [line for line in text.splitlines()
             if not (line.split() and not line.lstrip().startswith("#") and line.split()[0] in drop)]
    return "\n".join(lines) + "\n"


def fstab_with_swap_file(text: str, path: str = SWAP_FILE) -> str:
    """fstab with one `swap` line for `path` (not duplicated)."""
    for line in text.splitlines():
        fields = line.split()
        if fields and not line.lstrip().startswith("#") and fields[0] == path:
            return text if text.endswith("\n") else text + "\n"
    return (text if text.endswith("\n") else text + "\n") + f"{path} none swap sw 0 0\n"


def swap_volume_present(runner, vg: str) -> bool:
    proc = runner.run(["lvs", "--noheadings", "-o", "lv_name", f"{vg}/swap"], timeout=30)
    return proc.returncode == 0 and proc.stdout.strip() == "swap"


def swap_file_active(runner, path: str = SWAP_FILE) -> bool:
    proc = runner.run(["swapon", "--noheadings", "--show=NAME"], timeout=30)
    return proc.returncode == 0 and path in proc.stdout.split()


def _run(runner, argv, timeout=120):
    proc = runner.run(argv, timeout=timeout)
    if proc.returncode != 0:
        raise LayoutError(f"{' '.join(argv[:2])} failed: {(proc.stderr or proc.stdout or '').strip()[-160:]}")
    return proc


def move_swap_to_session_temp(runner, vg: str, *, size_gib: int = SWAP_SIZE_GIB, path: str = SWAP_FILE, fstab: str = FSTAB) -> dict:
    """Idempotent. Returns what it did: {"created_file", "removed_volume", "fstab"} booleans."""
    done = {"created_file": False, "removed_volume": False, "fstab": False}
    if not swap_file_active(runner, path):
        volume_growth.ensure_room(runner, "SESSION_TEMP", size_gib * GIB + GIB // 4)
        if not Path(path).exists():
            # Written, not fallocated: SESSION_TEMP is a thin volume, and swap must never find its blocks missing from a full pool.
            _run(runner, ["dd", "if=/dev/zero", f"of={path}", "bs=1M", f"count={size_gib * 1024}", "conv=fsync", "status=none"], timeout=1800)
            os.chmod(path, 0o600)
            _run(runner, ["mkswap", path])
        _run(runner, ["swapon", path])
        done["created_file"] = True
    if swap_volume_present(runner, vg):
        _run(runner, ["swapoff", f"/dev/{vg}/swap"])
        _run(runner, ["lvremove", "-y", f"{vg}/swap"])
        done["removed_volume"] = True
    text = Path(fstab).read_text()
    new = fstab_with_swap_file(fstab_without_swap_volume(text, vg), path)
    if new != text:
        temporary = Path(fstab + ".baseline-new")
        temporary.write_text(new)
        temporary.chmod(0o644)
        temporary.replace(fstab)
        done["fstab"] = True
    return done


def pool_present(runner, vg: str, name: str) -> bool:
    proc = runner.run(["lvs", "--noheadings", "-o", "lv_name", f"{vg}/{name}"], timeout=30)
    return proc.returncode == 0 and proc.stdout.strip() == name


def storage_ids(runner) -> set:
    proc = runner.run(["pvesm", "status"], timeout=60)
    rows = [line.split() for line in proc.stdout.splitlines()[1:] if line.split()]
    return {row[0] for row in rows} if proc.returncode == 0 else set()


def name_the_pool_for_session_temp(runner, vg: str, *, conf: str = LVM_LOCAL_CONF) -> dict:
    """Idempotent. Renames Proxmox's `data` thin pool to SESSION_TEMP's pool name, replaces the `local-lvm` storage with `session-temp` (the
    volumes in the pool are untouched; only the storage entry is replaced), and has LVM extend the pool automatically before it fills."""
    done = {"renamed_pool": False, "registered_storage": False, "autoextend": False}
    if pool_present(runner, vg, "data") and not pool_present(runner, vg, POOL_NAME):
        _run(runner, ["lvrename", vg, "data", POOL_NAME])
        done["renamed_pool"] = True
    if not pool_present(runner, vg, POOL_NAME):
        raise LayoutError(f"the thin pool {POOL_NAME} does not exist on {vg}")
    ids = storage_ids(runner)
    if "local-lvm" in ids:
        _run(runner, ["pvesm", "remove", "local-lvm"])
    if GUEST_STORAGE not in ids:
        _run(runner, ["pvesm", "add", "lvmthin", GUEST_STORAGE, "--vgname", vg, "--thinpool", POOL_NAME, "--content", "rootdir,images"])
        done["registered_storage"] = True
    path = Path(conf)
    if not path.exists() or AUTOEXTEND not in path.read_text():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(AUTOEXTEND)
        done["autoextend"] = True
    _run(runner, ["lvchange", "--monitor", "y", f"{vg}/{POOL_NAME}"])
    return done


# --- the volume group carries this drive's own name ---------------------------------------------------------------------------------------
# Proxmox's installer names every volume group `pve`. Two Baseline drives attached to one machine then collide: LVM cannot hold two groups of
# one name, the root and its volumes resolve to whichever drive answered first, and a host can mount the other drive's filesystems (seen on
# PC601 with PC401 attached, 2026-10-12: EXT-fs errors, root remounted read-only). The group is renamed by its UUID to a name derived from
# the drive's serial, and everything that names it is rewritten before the boot loader is regenerated.
NAME_FILES = ("/etc/fstab", "/etc/default/grub", "/etc/kernel/cmdline", "/etc/initramfs-tools/conf.d/resume")
GRUB_CONFIG = "/boot/grub/grub.cfg"
BOOT_TOOL_UUIDS = "/etc/kernel/proxmox-boot-uuids"


def volume_group_name_for(serial: str) -> str:
    """The same name single_drive_storage.isolate_volume_group gives the group of an offline drive."""
    if not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", serial):
        raise LayoutError("a hardware serial is required to name the volume group")
    return "baseline_" + hashlib.sha256(serial.encode()).hexdigest()[:12]


def text_with_group_renamed(text: str, old: str, new: str) -> str:
    """Every path form that names the group: /dev/<vg>/<lv> and /dev/mapper/<vg>-<lv> (nothing else is touched)."""
    return (text.replace(f"/dev/{old}/", f"/dev/{new}/").replace(f"/dev/mapper/{old}-", f"/dev/mapper/{new}-")
            .replace(f"lvm/{old}-", f"lvm/{new}-"))


def _rewrite(path: Path, old: str, new: str) -> bool:
    text = path.read_text()
    rewritten = text_with_group_renamed(text, old, new)
    if rewritten == text:
        return False
    temporary = path.with_name(path.name + ".baseline-new")
    temporary.write_text(rewritten)
    os.chmod(temporary, path.stat().st_mode & 0o777)
    temporary.replace(path)
    return True


def name_the_volume_group_for_drive(runner, *, serial: str, vg: str, vg_uuid: str, name_files=NAME_FILES, grub_config=GRUB_CONFIG) -> dict:
    """Idempotent. Renames the root's volume group (by UUID, so a second group of the same name cannot be the one renamed), rewrites the files
    that name it, then rebuilds the initramfs and the boot loader. Returns {"renamed", "files", "name"}."""
    new = volume_group_name_for(serial)
    done = {"renamed": False, "files": [], "name": new}
    if vg != new:
        others = runner.run(["vgs", "--noheadings", "-o", "vg_uuid", "--select", f"vg_name={new}"], timeout=30)
        if others.returncode == 0 and others.stdout.strip() not in ("", vg_uuid):
            raise LayoutError(f"the name {new} already belongs to another volume group")
        _run(runner, ["vgrename", vg_uuid, new])
        done["renamed"] = True
    if vg != new:
        for name in (*name_files, grub_config):
            if Path(name).is_file() and _rewrite(Path(name), vg, new):
                done["files"].append(name)
    if done["renamed"] or done["files"]:
        _run(runner, ["update-initramfs", "-u", "-k", "all"], timeout=900)
        # The kernel keeps reporting the running root under the name it was mounted with, which the live rename has just removed, so
        # grub-probe, findmnt and lsblk cannot resolve it until the next boot. The old name is given back as a link in /dev (a tmpfs: it is
        # gone at the next boot, when the root is mounted under its new name). grub-probe still writes the old name into the configuration,
        # so the file is rewritten again afterwards - which is what the next boot reads. Regeneration is best effort; the rewritten file
        # is what is required.
        link = Path(f"/dev/mapper/{vg}-root")
        if vg != new and not link.exists() and Path(f"/dev/mapper/{new}-root").exists():
            link.symlink_to(f"{new}-root")
        argv = ["proxmox-boot-tool", "refresh"] if Path(BOOT_TOOL_UUIDS).is_file() else ["update-grub"]
        done["regenerated"] = runner.run(argv, timeout=600).returncode == 0
        if vg != new and Path(grub_config).is_file():
            _rewrite(Path(grub_config), vg, new)
            if f"/dev/mapper/{vg}-" in Path(grub_config).read_text():
                raise LayoutError("the boot configuration still names the old volume group")
    return done
