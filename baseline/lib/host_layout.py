"""The host's own volumes expressed in the agreed role names (DR257).

Proxmox's installer creates `swap` as a volume of its own. The agreed layout has no such volume: swap space lives in SESSION_TEMP. This module
moves it: a swap file is created in SESSION_TEMP (the volume is grown first, from the volume group's free space), switched on, and only then
is the old swap volume switched off, removed and dropped from fstab, so the host never runs without swap in between and a failure before the
last step leaves the old swap in place. Every step checks the current state first, so a rerun completes what is missing.
"""
from __future__ import annotations

import os
from pathlib import Path

import volume_growth

GIB = 1024 ** 3
SWAP_FILE = "/mnt/SESSION_TEMP/swapfile"
SWAP_SIZE_GIB = 4
FSTAB = "/etc/fstab"


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
            _run(runner, ["fallocate", "-l", f"{size_gib}G", path])
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
