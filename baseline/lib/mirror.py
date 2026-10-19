"""The compact mirror: the files each volume of a child drive holds, kept by volume ROLE on the parent's mirror partition, updated by change and never rewritten whole.

The volumes are the ones the build defines (`drive_installer.baseline_volumes_for`): USER_ADMIN and USER_PERSONAL (the user's data), APPDATA_ADMIN and APPDATA_PERSONAL (each application's
writable data), SUBSTRATE (configuration and recovery data), BASELINE (app, VM and container state), INSTALLER_CACHE (ISOs and driver packages), plus the general OS (ROOT) and the boot partitions. A
volume is found only through that table, never by guessing at what is on the drive, and each one is checked against the drive's own storage policy (its serial and the filesystem UUID recorded for
that role) before anything is copied; a logical volume the build does not define is refused, not copied. SESSION_TEMP is scratch for running sessions and is not mirrored.

Each role keeps its own folder: `<root>/mirror/<combination>/<child uuid>/volumes/<ROLE>/`, with the partition table and volume layout beside it. A refresh walks a volume's files and updates only
what differs: a changed file is updated in place, block by block (`rsync --no-whole-file --inplace`), a new file is added, a deleted file is removed, and everything unchanged is left alone. Only files are
stored, so there is no empty space; nothing sparse or preallocated is created. Ownership, permissions, hard links, ACLs and extended attributes are kept, so a volume can be rebuilt from it: make
the filesystem as `volumes.json` describes and copy the files back. While a refresh runs the mirror is marked incomplete. The version history of the user's and applications' data is kept in the same
mirror (`mirror_history`).
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

import drive_installer as di
import drive_recovery as dr
import drive_recovery_used as du
import offdrive_backup
import physical_device_safety as pds
from write_once import write_if_changed

STATE = "mirror-state.json"
RSYNC = ["rsync", "-aHAXS", "--numeric-ids", "--delete", "--no-whole-file", "--inplace", "--modify-window=-1", "--stats", "--human-readable"]      # -1: times compared to the nanosecond, so a change made in the same second as the last refresh is not missed
READ_ONLY = {"ext2": "ro,noload", "ext3": "ro,noload", "ext4": "ro,noload", "xfs": "ro,norecovery", "btrfs": "ro", "vfat": "ro"}
NOT_MIRRORED = ("SESSION_TEMP",)


class MirrorError(RuntimeError):
    pass


def role_for_lv() -> dict:
    """logical volume name -> role, from the build's own volume table."""
    return {lv: label for lv, _, _, label, _ in di.baseline_volumes_for()}


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
    return {"files_changed": number("Number of regular files transferred"), "bytes_sent": number("Literal data")}


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


def classify(item: dict, info: dict) -> str:
    """The role of one thing on the drive, only from the build's own tables: a defined volume, the OS root, swap, or a boot partition. Anything else is refused."""
    if info["fstype"] == "swap":
        return "SWAP"
    if item["kind"] == "lv":
        if item["lv"] in role_for_lv():
            return role_for_lv()[item["lv"]]
        if item["lv"] == "root":
            return "ROOT"
        raise MirrorError(f"{item['lv']} is not a volume this build defines; refused, not copied")
    if info["fstype"] == "vfat":
        return "EFI"
    if info["fstype"] is None and item["size"] <= du.RAW_SMALL_MAX:
        return "BIOS_BOOT"
    raise MirrorError(f"{item['name']} is not a partition this build defines; refused, because copying it whole would store its empty space")


def read_policy(mount_dir):
    import storage_policy
    return storage_policy.validate_policy(json.loads((Path(mount_dir) / "storage-policy.json").read_text()))


def verify_roles(policy: dict, serial: str, role_uuids: dict) -> None:
    """Every defined role on the drive must be the filesystem the drive's own storage policy recorded for it (the same check an update makes)."""
    if policy.get("serial") != serial:
        raise MirrorError("the drive's storage policy belongs to a different drive")
    for role, uuid in role_uuids.items():
        if role in role_for_lv().values() and policy["bindings"].get(role) != {"serial": serial, "uuid": uuid}:
            raise MirrorError(f"the {role} volume is not the one the drive's storage policy recorded; nothing was copied")


def refresh(runner, *, serial, child, combination, root, allowed_serials, pds_runner=None, mount_base="/mnt/MIRROR-SRC", policy_reader=read_policy) -> dict:
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
    plan = du.plan_volumes(runner, target["path"])
    volumes, report, mounted, activated = [], {}, [], []
    try:
        for vg_uuid in sorted({v["vg_uuid"] for v in plan if v["kind"] == "lv"}):
            name = next(v["vg_name"] for v in plan if v.get("vg_uuid") == vg_uuid)
            cfg = directory / f".vg-{vg_uuid}.cfg"
            cfg.unlink(missing_ok=True)
            du._run(runner, ["vgcfgbackup", "-f", str(cfg), name], "saving the volume layout")
            write_if_changed_bytes(directory / f"vg-{vg_uuid}.cfg", cfg)
            du._run(runner, ["vgchange", "-ay", "--select", f"vg_uuid={vg_uuid}"], "activating the volume group to read it")
            activated.append(vg_uuid)
        found = []
        for item in plan:
            info = _fs_info(runner, item["path"])
            found.append((classify(item, info), item, info))
        by_role = {role: (item, info) for role, item, info in found}
        if "SUBSTRATE" in by_role:                                                       # the drive's own policy says which filesystem is which role: check before copying anything
            item, info = by_role["SUBSTRATE"]
            point = Path(mount_base) / "SUBSTRATE-CHECK"
            point.mkdir(parents=True, exist_ok=True)
            du._run(runner, ["mount", "-t", info["fstype"], "-o", READ_ONLY[info["fstype"]] + ",nodev,nosuid,noexec", item["path"], str(point)], "mounting SUBSTRATE to read its policy")
            try:
                verify_roles(policy_reader(point), serial, {role: i["uuid"] for role, (_, i) in by_role.items()})
            finally:
                runner.run(["umount", str(point)], timeout=120)
        else:
            raise MirrorError("the drive has no SUBSTRATE volume, so its roles cannot be verified; nothing was copied")
        for role, item, info in found:
            record = {"role": role, "name": item["name"], "kind": item["kind"], "device_bytes": item["size"], **info}
            volumes.append(record)
            if role == "SWAP" or role in NOT_MIRRORED:
                record["skipped"] = "swap" if role == "SWAP" else "scratch space"
                continue                                                                  # recorded by size; nothing is stored
            if role == "BIOS_BOOT":
                raw = Path(item["path"]).read_bytes()                                       # tiny, copied only when it differs
                write_if_changed_bytes(directory / f"{role}.raw", raw)
                record["fstype"] = None
                continue
            point = Path(mount_base) / role
            point.mkdir(parents=True, exist_ok=True)
            du._run(runner, ["mount", "-t", info["fstype"], "-o", READ_ONLY[info["fstype"]] + ",nodev,nosuid,noexec", item["path"], str(point)], f"mounting {role} to read it")
            mounted.append(point)
            report[role] = sync_volume(runner, point, directory / "volumes" / role)
    finally:
        for point in reversed(mounted):
            runner.run(["umount", str(point)], timeout=120)
        for vg_uuid in activated:
            runner.run(["vgchange", "-an", "--select", f"vg_uuid={vg_uuid}"], timeout=120)
    keep = {v["role"] for v in volumes}
    volumes_root = directory / "volumes"
    if volumes_root.is_dir():
        for old in volumes_root.iterdir():
            if old.name not in keep:
                shutil.rmtree(old)                                                     # a role the drive no longer has
    write_if_changed(directory / "volumes.json", json.dumps({"size_bytes": target["size_bytes"], "volumes": volumes}, indent=1) + "\n")
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
