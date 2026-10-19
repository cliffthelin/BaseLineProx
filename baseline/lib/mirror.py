"""The compact mirror: the files a child drive holds, kept on the parent's mirror partition, updated by change and never rewritten whole.

For each child there is one folder, `<root>/mirror/<combination>/<child uuid>/`, with the drive's partition table and volume layout (small files) and, for every filesystem, a copy of its FILES
(`volumes/<name>/`). A refresh walks the drive's files and updates only what differs: a changed file is updated in place, block by block (`rsync --no-whole-file --inplace`, so ten changed
files write ten files' worth of changes, a thousand write a thousand, and a change inside a big file writes only the changed blocks), a new file is added, a deleted file is removed, and everything unchanged
is left alone (not read for writing, not touched). Only files are stored, so there is no empty space in the mirror; nothing sparse or preallocated is created. Ownership, permissions, hard links, ACLs and
extended attributes are kept, so a volume can be rebuilt from it: make the filesystem as `volumes.json` describes and copy the files back. While a refresh runs the mirror is marked incomplete.
Persistence data is also versioned in git (`parent_vault`); this mirror is the whole drive's current contents.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import drive_recovery as dr
import drive_recovery_used as du
import offdrive_backup
import physical_device_safety as pds
from write_once import write_if_changed

STATE = "mirror-state.json"
RSYNC = ["rsync", "-aHAXS", "--numeric-ids", "--delete", "--no-whole-file", "--inplace", "--modify-window=-1", "--stats", "--human-readable"]      # -1: times compared to the nanosecond, so a change made in the same second as the last refresh is not missed
READ_ONLY = {"ext2": "ro,noload", "ext3": "ro,noload", "ext4": "ro,noload", "xfs": "ro,norecovery", "btrfs": "ro", "vfat": "ro"}


class MirrorError(RuntimeError):
    pass


def child_dir(root, combination: str, child: str) -> Path:
    return Path(root) / "mirror" / combination / child


def parse_stats(text: str) -> dict:
    """What rsync did, from its --stats: files updated and the bytes of new data written (not the size of the files, which may be mostly unchanged)."""
    def number(label):
        m = re.search(rf"{label}:\s+([\d,.]+)([KMGT]?)", text)
        if not m:
            return 0
        value = float(m.group(1).replace(",", ""))
        return int(value * {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}[m.group(2)])
    return {"files_changed": number("Number of regular files transferred"), "bytes_sent": number("Literal data")}       # literal data: the bytes actually written


def sync_volume(runner, source_dir, dest_dir) -> dict:
    """Make `dest_dir` hold exactly the files of `source_dir`, writing only the difference."""
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    done = runner.run([*RSYNC, str(source_dir).rstrip("/") + "/", str(dest_dir).rstrip("/") + "/"], timeout=86400)
    if done.returncode not in (0, 24):                              # 24: a source file vanished while reading (it is gone; the next run removes it)
        raise MirrorError(f"updating the mirror of {source_dir} failed: {(done.stderr or '').strip()[-300:]}")
    return parse_stats(done.stdout or "")


def _fs_info(runner, path) -> dict:
    done = runner.run(["blkid", "-p", "-o", "export", str(path)], timeout=30)
    info = dict(line.split("=", 1) for line in (done.stdout or "").splitlines() if "=" in line)
    return {"fstype": info.get("TYPE"), "uuid": info.get("UUID"), "label": info.get("LABEL")}


def refresh(runner, *, serial, child, combination, root, allowed_serials, pds_runner=None, mount_base="/mnt/MIRROR-SRC") -> dict:
    """Bring the child's mirror up to date from the (offline, unmounted) drive. Returns what changed."""
    if serial not in allowed_serials:
        raise MirrorError("source serial is not enrolled")
    disk = dr._offline_disk(runner, serial)
    target = pds.validate_target_device(disk["name"], expected_serial=serial, min_size_bytes=disk["size"], max_size_bytes=disk["size"], runner=pds_runner)
    directory = child_dir(root, combination, child)
    directory.mkdir(parents=True, exist_ok=True)
    offdrive_backup.resolve_destination(str(directory), run=runner.run, allowed_serials=allowed_serials, boot_serial=pds.get_boot_device_serial(pds_runner or pds.Runner()))
    (directory / STATE).write_text(json.dumps({"complete": False, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
    layout_tmp = directory / ".layout.sgdisk.new"
    layout_tmp.unlink(missing_ok=True)
    du._run(runner, ["sgdisk", f"--backup={layout_tmp}", target["path"]], "saving the partition table")
    write_if_changed_bytes(directory / "layout.sgdisk", layout_tmp)
    volumes, report, mounted, activated = [], {}, [], []
    plan = du.plan_volumes(runner, target["path"])
    try:
        for vg_uuid in sorted({v["vg_uuid"] for v in plan if v["kind"] == "lv"}):
            name = next(v["vg_name"] for v in plan if v.get("vg_uuid") == vg_uuid)
            cfg = directory / f".vg-{vg_uuid}.cfg"
            cfg.unlink(missing_ok=True)
            du._run(runner, ["vgcfgbackup", "-f", str(cfg), name], "saving the volume layout")
            write_if_changed_bytes(directory / f"vg-{vg_uuid}.cfg", cfg)
            du._run(runner, ["vgchange", "-ay", "--select", f"vg_uuid={vg_uuid}"], "activating the volume group to read it")
            activated.append(vg_uuid)
        for item in plan:
            info = _fs_info(runner, item["path"])
            record = {"name": item["name"], "kind": item["kind"], "device_bytes": item["size"], **info}
            volumes.append(record)
            if info["fstype"] == "swap":
                continue                                                              # swap holds nothing worth keeping: its size is recorded, nothing is stored
            if info["fstype"] not in READ_ONLY:
                if item["size"] > du.RAW_SMALL_MAX:
                    raise MirrorError(f"{item['name']} has no filesystem the mirror understands; refused, because copying it whole would store its empty space")
                raw = Path(item["path"]).read_bytes()                                  # the BIOS boot area: tiny, copied only when it differs
                write_if_changed_bytes(directory / f"{item['name']}.raw", raw)
                record["fstype"] = None
                record["kind"] = "raw-small"
                continue
            point = Path(mount_base) / item["name"]
            point.mkdir(parents=True, exist_ok=True)
            du._run(runner, ["mount", "-t", info["fstype"], "-o", READ_ONLY[info["fstype"]] + ",nodev,nosuid,noexec", item["path"], str(point)], f"mounting {item['name']} to read it")
            mounted.append(point)
            report[item["name"]] = sync_volume(runner, point, directory / "volumes" / item["name"])
    finally:
        for point in reversed(mounted):
            runner.run(["umount", str(point)], timeout=120)
        for vg_uuid in activated:
            runner.run(["vgchange", "-an", "--select", f"vg_uuid={vg_uuid}"], timeout=120)
    keep = {v["name"] for v in volumes}
    volumes_root = directory / "volumes"
    if volumes_root.is_dir():
        import shutil
        for old in volumes_root.iterdir():
            if old.name not in keep:
                shutil.rmtree(old)                                                     # a volume the drive no longer has
    write_if_changed(directory / "volumes.json", json.dumps({"serial_hint": None, "size_bytes": target["size_bytes"], "volumes": volumes}, indent=1) + "\n")
    (directory / STATE).write_text(json.dumps({"complete": True, "finished": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
    return {"folder": str(directory), "volumes": report, "files_changed": sum(v["files_changed"] for v in report.values()),
            "bytes_sent": sum(v["bytes_sent"] for v in report.values()), "includes_unallocated_space": False}


def write_if_changed_bytes(path, source) -> bool:
    """Replace `path` with `source` (a file path, or bytes) only when the content differs; a temporary `source` file is removed."""
    path = Path(path)
    data = source if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    try:
        same = path.is_file() and path.read_bytes() == data
    except OSError:
        same = False
    if not same:
        path.write_bytes(data)
    if not isinstance(source, (bytes, bytearray)):
        Path(source).unlink(missing_ok=True)
    return not same
