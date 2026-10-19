"""Bring an existing build's INSTALLER_CACHE up to date with a built offline cache and OS images: add what is missing and update what changed, nothing else.

The ready-made OS bases, the Kasm base, the apps and the packages live in the cache; an update that only changes code leaves a build without them. This copies the difference only: a file already
there with the same content is not read for writing or touched, a changed file is updated in place by block, a new one is added, and nothing is deleted. It first measures what would be written (a
dry run), grows the volume out of the group's free space if that is not enough (never takes the group's last GiB), and only then copies.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import mirror

GIB = 1024 ** 3
KEEP_FREE = 1 * GIB
OVERHEAD = 1.08                       # ext4 keeps reserved blocks and metadata: growing by exactly the shortfall left copies a little short before
FLAGS = ["rsync", "-a", "--inplace", "--no-whole-file", "--modify-window=-1", "--stats", "--human-readable"]


class CacheSyncError(RuntimeError):
    pass


def measure(runner, source, destination) -> dict:
    """What a sync would write, without writing: {"files_changed", "bytes_sent"} (new data only)."""
    Path(destination).mkdir(parents=True, exist_ok=True)
    done = runner.run([*FLAGS, "--dry-run", str(source).rstrip("/") + "/", str(destination).rstrip("/") + "/"], timeout=86400)
    if done.returncode not in (0, 24):
        raise CacheSyncError(f"measuring {source} failed: {(done.stderr or '').strip()[-200:]}")
    stats = mirror.parse_stats(done.stdout or "")
    total = mirror_total(done.stdout or "")
    return {"files_changed": stats["files_changed"], "bytes_sent": max(stats["bytes_sent"], total)}


def mirror_total(text: str) -> int:
    import re
    m = re.search(r"Total transferred file size:\s+([\d,.]+)([KMGT]?)", text)
    if not m:
        return 0
    return int(float(m.group(1).replace(",", "")) * {"": 1, "K": 1024, "M": 1024 ** 2, "G": GIB, "T": 1024 ** 4}[m.group(2)])


def growth_needed(needed_bytes: int, available_bytes: int, vg_free_bytes: int) -> int:
    """GiB to add to the volume so `needed_bytes` fit, 0 when they already do. Refuses when the group cannot give it: a copy must never start that cannot finish."""
    if needed_bytes <= available_bytes:
        return 0
    add = math.ceil((needed_bytes - available_bytes) * OVERHEAD / GIB)
    free = max(vg_free_bytes - KEEP_FREE, 0) // GIB
    if add > free:
        raise CacheSyncError(f"the cache needs {add} GiB more room but the volume group has only {free} GiB unallocated; nothing was copied")
    return add


def _volume(runner, vg_uuid: str) -> tuple:
    out = runner.run(["lvs", "--noheadings", "--separator", "|", "-o", "lv_name,lv_path,vg_free", "--units", "b", "--nosuffix", "--select", f"vg_uuid={vg_uuid}"], timeout=60)
    for line in (out.stdout or "").splitlines():
        name, path, vg_free = [x.strip() for x in line.split("|")]
        if name == "baseline_installer_cache":
            return path, int(float(vg_free))
    raise CacheSyncError("the drive's INSTALLER_CACHE volume was not found")


def sync(runner, *, mount, vg_uuid, sources) -> dict:
    """`sources` is [(source folder, folder inside the mounted INSTALLER_CACHE)]. Measures all of it, makes room once, then copies the difference."""
    plan = []
    for source, relative in sources:
        if not Path(source).is_dir():
            continue
        destination = Path(mount) / relative
        plan.append((Path(source), destination, measure(runner, source, destination)))
    needed = sum(p[2]["bytes_sent"] for p in plan)
    if not needed and not sum(p[2]["files_changed"] for p in plan):
        return {"copied": [], "grown_gib": 0, "bytes_written": 0, "files_changed": 0, "note": "the cache is already up to date; nothing was written"}
    stat = os.statvfs(mount)
    path, vg_free = _volume(runner, vg_uuid)
    add = growth_needed(needed, stat.f_bavail * stat.f_frsize, vg_free)
    if add:
        done = runner.run(["lvextend", "-r", "-L", f"+{add}G", path], timeout=3600)
        if done.returncode:
            raise CacheSyncError(f"growing the cache volume failed: {(done.stderr or '').strip()[-200:]}")
    copied = []
    for source, destination, measured in plan:
        if not measured["files_changed"]:
            continue
        done = runner.run([*FLAGS, str(source).rstrip("/") + "/", str(destination).rstrip("/") + "/"], timeout=86400)
        if done.returncode not in (0, 24):
            raise CacheSyncError(f"copying {source} failed: {(done.stderr or '').strip()[-200:]}")
        copied.append({"from": str(source), "to": str(destination), **mirror.parse_stats(done.stdout or "")})
    return {"copied": copied, "grown_gib": add, "bytes_written": sum(c["bytes_sent"] for c in copied), "files_changed": sum(c["files_changed"] for c in copied)}
