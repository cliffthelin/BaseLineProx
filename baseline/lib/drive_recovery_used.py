"""Recovery snapshots that hold only what a drive is using (operator, 2026-10-01 and 2026-10-19: empty space is never held, read or written).

A snapshot is the drive's partition table and LVM layout (small files), plus one compressed image per filesystem made from the filesystem's own allocation map (`used_backup`, partclone): free blocks
are not read, so a reinstall's leftovers are not stored either. Swap is recorded by size (it holds nothing worth keeping), a tiny partition with no filesystem (the BIOS boot area) is copied raw, and
anything else is REFUSED, never copied whole. Each image is verified, and an image larger than the data it holds is a failure. The manifest (`baseline-drive-recovery-v2`) lists everything needed to
rebuild the drive: layout files, and for every volume its filesystem, used bytes, image and checksum. Nothing here writes to the source drive; volume groups are activated to be read and deactivated after.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

import drive_recovery as dr
import offdrive_backup
import physical_device_safety as pds
import used_backup as ub
from single_drive_storage import _json_command, _walk

FORMAT = "baseline-drive-recovery-v2"
RAW_SMALL_MAX = 8 * 2 ** 20            # a partition with no filesystem may be copied raw only if it is this small (the BIOS boot area)
SKIP_SEGTYPES = ("thin-pool", "cache-pool", "metadata")


def _sha(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 2 ** 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(runner, argv, what, timeout=600):
    done = runner.run(argv, timeout=timeout)
    if done.returncode:
        raise dr.RecoveryError(f"{what} failed: {(done.stderr or done.stdout or '').strip()[-200:]}")
    return done.stdout or ""


def _raw_small(source, out_dir, name, size) -> dict:
    import subprocess
    target = Path(out_dir) / f"{name}.raw.zst"
    with open(source, "rb") as src:
        done = subprocess.run(["zstd", "-q", "-T0", "-o", str(target)], stdin=src)
    if done.returncode:
        raise dr.RecoveryError(f"copying {name} failed")
    return {"name": name, "fstype": None, "kind": "raw-small", "device_bytes": size, "used_bytes": size, "image": target.name,
            "image_bytes": target.stat().st_size, "sha256": _sha(target), "includes_unallocated_space": False}


def plan_volumes(runner, disk_path) -> list:
    """What is on the disk, in the order it is imaged: [{"kind": "partition"|"lv", "name", "path", "size", "fstype", "vg_uuid"?}]. LVM physical volumes themselves are not imaged: their logical volumes are."""
    listing = _json_command(runner, ["lsblk", "-J", "-b", "-p", "-o", "NAME,TYPE,FSTYPE,SIZE", disk_path])
    out, vgs = [], []
    for node in _walk(listing.get("blockdevices")):
        if node.get("type") != "part":
            continue
        if node.get("fstype") == "LVM2_member":
            vgs.append(node["name"])
        else:
            out.append({"kind": "partition", "name": Path(node["name"]).name, "path": node["name"], "size": int(node["size"]), "fstype": node.get("fstype")})
    for pv in vgs:
        pvs = _json_command(runner, ["pvs", "--reportformat", "json", "-o", "pv_name,vg_name,vg_uuid", pv])["report"][0]["pv"]
        for row in pvs:
            lvs = _json_command(runner, ["lvs", "--reportformat", "json", "--units", "b", "--nosuffix", "-o", "lv_name,lv_path,lv_size,segtype,lv_attr", "--select", f"vg_uuid={row['vg_uuid']}"])["report"][0]["lv"]
            for lv in lvs:
                if lv["segtype"] in SKIP_SEGTYPES or lv["lv_name"].startswith("["):
                    continue
                out.append({"kind": "lv", "name": f"{row['vg_name']}.{lv['lv_name']}", "path": lv["lv_path"], "size": int(float(lv["lv_size"])), "fstype": None,
                            "vg_name": row["vg_name"], "vg_uuid": row["vg_uuid"]})
    return out


def create_snapshot_used(runner, *, serial, destination, allowed_serials, pds_runner=None, imager=ub.image_volume, detector=ub.detect_fstype, raw_copier=_raw_small, previous=None) -> Path:
    """`previous` is an earlier snapshot folder of this same drive: a volume whose used blocks have not changed is not written again (its image is linked from there)."""
    earlier = {}
    if previous:
        try:
            earlier = {v["name"]: v for v in json.loads((Path(previous) / "MANIFEST.json").read_text()).get("volumes", [])}
        except (OSError, ValueError):
            earlier = {}
    if serial not in allowed_serials:
        raise dr.RecoveryError("source serial is not enrolled")
    disk = dr._offline_disk(runner, serial)
    target = pds.validate_target_device(disk["name"], expected_serial=serial, min_size_bytes=disk["size"], max_size_bytes=disk["size"], runner=pds_runner)
    dest = offdrive_backup.resolve_destination(destination, run=runner.run, allowed_serials=allowed_serials, boot_serial=pds.get_boot_device_serial(pds_runner or pds.Runner()))
    free, total = offdrive_backup.free_and_total(dest.path)
    budget = offdrive_backup.budget_from(free=free, total=total, source_bytes=target["size_bytes"])
    folder = Path(dest.path) / ("baseline-recovery-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex)
    folder.mkdir(mode=0o700)
    (folder / "INCOMPLETE.json").write_text(json.dumps({"serial": serial, "size_bytes": target["size_bytes"], "complete": False, "format": FORMAT, "write_budget_bytes": budget}) + "\n")
    layout = {"sgdisk": "layout.sgdisk", "vgcfg": {}}
    _run(runner, ["sgdisk", f"--backup={folder / layout['sgdisk']}", target["path"]], "saving the partition table")
    volumes, activated, written = [], [], 0
    try:
        plan = plan_volumes(runner, target["path"])
        for vg_uuid in sorted({v["vg_uuid"] for v in plan if v["kind"] == "lv"}):
            name = next(v["vg_name"] for v in plan if v.get("vg_uuid") == vg_uuid)
            _run(runner, ["vgcfgbackup", "-f", str(folder / f"vg-{vg_uuid}.cfg"), name], "saving the volume layout")
            layout["vgcfg"][vg_uuid] = f"vg-{vg_uuid}.cfg"
            _run(runner, ["vgchange", "-ay", "--select", f"vg_uuid={vg_uuid}"], "activating the volume group to read it")
            activated.append(vg_uuid)
        for item in plan:
            try:
                fstype = item["fstype"] or detector(item["path"])
            except ub.UsedBackupError:
                fstype = None
            probe = runner.run(["blkid", "-p", "-o", "value", "-s", "TYPE", item["path"]], timeout=30)
            if (probe.stdout or "").strip() == "swap":
                volumes.append({"name": item["name"], "kind": "swap", "fstype": "swap", "device_bytes": item["size"], "used_bytes": 0, "image": None, "image_bytes": 0,
                                "sha256": None, "includes_unallocated_space": False})
                continue
            if fstype is None:
                if item["size"] > RAW_SMALL_MAX:
                    raise dr.RecoveryError(f"{item['name']} ({item['size'] // 2**20} MiB) has no filesystem this backup understands; refused, because copying it whole would store empty space")
                record = raw_copier(item["path"], folder, item["name"], item["size"])
            else:
                kwargs = {"previous": earlier[item["name"]], "previous_dir": previous} if item["name"] in earlier else {}
                record = imager(item["path"], folder, item["name"], fstype=fstype, **kwargs)
                record["kind"] = item["kind"]
            written += 0 if record.get("reused") else record["image_bytes"]            # a reused image is a link to data already there: nothing was written
            if written > budget:
                raise dr.RecoveryError("the snapshot would not fit on the destination; stopped")
            volumes.append(record)
    except (ub.UsedBackupError, dr.RecoveryError):
        raise
    finally:
        for vg_uuid in activated:
            runner.run(["vgchange", "-an", "--select", f"vg_uuid={vg_uuid}"], timeout=120)
    dr._offline_disk(runner, serial)
    manifest = {"format": FORMAT, "serial": serial, "size_bytes": target["size_bytes"], "layout": layout, "volumes": volumes, "image_bytes": written,
                "image_verified": True, "includes_unallocated_space": False, "complete": True, "boot_verified": False}
    dr._publish_complete_manifest(folder, manifest)
    return folder


def verify_used_snapshot(folder, *, expected_serial, checker=ub.check_image) -> dict:
    folder = Path(folder)
    try:
        manifest = json.loads((folder / "MANIFEST.json").read_text())
    except (OSError, ValueError):
        raise dr.RecoveryError("recovery snapshot is incomplete or unreadable") from None
    if manifest.get("format") != FORMAT or manifest.get("serial") != expected_serial or manifest.get("complete") is not True or manifest.get("includes_unallocated_space") is not False:
        raise dr.RecoveryError("recovery snapshot identity/completion is invalid")
    for name in [manifest["layout"]["sgdisk"], *manifest["layout"]["vgcfg"].values()]:
        if not (folder / name).is_file():
            raise dr.RecoveryError(f"recovery snapshot is missing {name}")
    for volume in manifest["volumes"]:
        if volume.get("includes_unallocated_space") is not False:
            raise dr.RecoveryError(f"{volume.get('name')} was imaged with its empty space")
        if volume["kind"] == "swap":
            continue
        image = folder / volume["image"]
        if image.is_symlink() or not image.is_file() or _sha(image) != volume["sha256"] or image.stat().st_size != volume["image_bytes"]:
            raise dr.RecoveryError(f"image of {volume['name']} failed its integrity check")
        ub.accept_size(used_bytes=volume["used_bytes"], image_bytes=volume["image_bytes"])
        if volume["kind"] != "raw-small" and not checker(image, volume["fstype"]):
            raise dr.RecoveryError(f"image of {volume['name']} did not verify")
    return manifest
