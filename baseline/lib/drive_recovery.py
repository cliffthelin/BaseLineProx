"""Add-only whole-drive recovery images for quiesced, serial-validated targets.

This helper never restores over a physical drive. A new compressed qcow2 image
is compared byte-for-byte with the offline source before a complete manifest is
published. Interrupted images remain explicitly incomplete and cannot authorize
conversion; a complete manifest and matching image are authoritative if an old
version left a stale marker behind. No existing backup is removed or replaced.
"""
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

import offdrive_backup
import physical_device_safety as pds
from single_drive_storage import _json_command, _walk


class RecoveryError(RuntimeError):
    pass


def quiesce_source(runner, *, serial, allowed_serials, pds_runner=None):
    """Unmount only an enrolled non-boot source with no active filesystem users.

    Never kills processes, forces/lazily unmounts, or disables active swap.
    The caller must be root so the process-use inspection is complete.
    """
    uid = runner.run(["id", "-u"], timeout=10)
    if uid.returncode or uid.stdout.strip() != "0":
        raise RecoveryError("quiescence requires root for complete process-use inspection")
    if serial not in allowed_serials:
        raise RecoveryError("source serial is not enrolled")
    listing = _json_command(runner, ["lsblk", "-J", "-b", "-p", "-o", "NAME,TYPE,SERIAL,SIZE,MOUNTPOINTS"])
    disks = [d for d in _walk(listing.get("blockdevices")) if d.get("type") == "disk" and d.get("serial") == serial]
    if len(disks) != 1 or type(disks[0].get("size")) is not int:
        raise RecoveryError("source disk identity or size is ambiguous")
    disk = disks[0]
    target = pds.validate_target_device(disk["name"], expected_serial=serial,
        min_size_bytes=disk["size"], max_size_bytes=disk["size"], runner=pds_runner)
    mounts = set()
    for node in _walk([disk]):
        if "mountpoints" not in node or not isinstance(node["mountpoints"], list):
            raise RecoveryError("source mount state is unknown")
        for mountpoint in node["mountpoints"]:
            if mountpoint is None:continue
            if (not isinstance(mountpoint, str) or not mountpoint.startswith("/") or mountpoint == "/"
                    or os.path.normpath(mountpoint) != mountpoint or any(c in mountpoint for c in "\x00\n")):
                raise RecoveryError("source has an unsafe mountpoint or active swap")
            mounts.add(mountpoint)
    for mountpoint in mounts:
        used = runner.run(["fuser", "-m", "--", mountpoint], timeout=30)
        if used.returncode != 1 or used.stdout.strip():
            raise RecoveryError("source filesystem has active users or process inspection failed")
    for mountpoint in sorted(mounts, key=len, reverse=True):
        checked = pds.validate_target_device(target["path"], expected_serial=serial,
            min_size_bytes=target["size_bytes"], max_size_bytes=target["size_bytes"], runner=pds_runner)
        if checked != target:raise RecoveryError("source identity changed before unmount")
        proc = runner.run(["umount", "--", mountpoint], timeout=30)
        if proc.returncode:raise RecoveryError(f"normal unmount failed for {mountpoint}: {proc.stderr.strip()}")
    _offline_disk(runner, serial)
    return sorted(mounts)


def _offline_disk(runner, serial):
    listing = _json_command(runner, ["lsblk", "-J", "-b", "-p", "-o", "NAME,TYPE,SERIAL,SIZE,FSTYPE,MOUNTPOINTS"])
    disks = [d for d in _walk(listing.get("blockdevices")) if d.get("type") == "disk" and d.get("serial") == serial]
    if len(disks) != 1 or type(disks[0].get("size")) is not int or disks[0]["size"] <= 0:
        raise RecoveryError("serial does not identify exactly one measured source disk")
    disk = disks[0]
    for node in _walk([disk]):
        if "mountpoints" not in node or not isinstance(node["mountpoints"], list):
            raise RecoveryError("source mount state is unknown")
        if any(node["mountpoints"]):
            raise RecoveryError("source has mounted descendants; quiesce and unmount before recovery imaging")
    return disk


def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
            h.update(chunk)
    return h.hexdigest()


def _publish_complete_manifest(folder, manifest):
    """Durably publish completion before removing the interrupted-run marker."""
    folder = Path(folder)
    with open(folder / "MANIFEST.json", "x") as stream:
        stream.write(json.dumps(manifest, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    incomplete = folder / "INCOMPLETE.json"
    if incomplete.exists() or incomplete.is_symlink():
        incomplete.unlink()
    directory_fd = os.open(folder, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def create_snapshot(runner, *, serial, destination, allowed_serials, pds_runner=None):
    if serial not in allowed_serials:
        raise RecoveryError("source serial is not enrolled")
    disk = _offline_disk(runner, serial)
    target = pds.validate_target_device(disk["name"], expected_serial=serial,
                                       min_size_bytes=disk["size"], max_size_bytes=disk["size"], runner=pds_runner)
    dest = offdrive_backup.resolve_destination(destination, run=runner.run,
        allowed_serials=allowed_serials, boot_serial=pds.get_boot_device_serial(pds_runner or pds.Runner()))
    # A compressed qcow2 of a mostly-empty drive is a small fraction of its raw size, so charging the raw size
    # up front refused images that fit easily. Instead the write gets a budget of real free space minus the
    # destination's 3% reserve, enforced by the kernel (prlimit --fsize): if the image would outgrow it, the
    # convert fails and the folder stays INCOMPLETE - the destination is never filled either way.
    free, total = offdrive_backup.free_and_total(dest.path)
    budget = offdrive_backup.budget_from(free=free, total=total, source_bytes=target["size_bytes"])
    folder = Path(dest.path) / ("baseline-recovery-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex)
    folder.mkdir(mode=0o700)
    incomplete = folder / "INCOMPLETE.json"
    incomplete.write_text(json.dumps({"serial": serial, "size_bytes": target["size_bytes"], "complete": False,
                                      "write_budget_bytes": budget}) + "\n")
    image = folder / "drive.qcow2"
    convert = ["qemu-img", "convert", "-f", "raw", "-O", "qcow2", "-c", target["path"], str(image)]
    for argv in (offdrive_backup.capped(convert, budget),
                 ["qemu-img", "check", "-f", "qcow2", str(image)],
                 ["qemu-img", "compare", "-f", "raw", "-F", "qcow2", target["path"], str(image)]):
        current = _offline_disk(runner, serial)
        checked = pds.validate_target_device(current["name"], expected_serial=serial,
            min_size_bytes=target["size_bytes"], max_size_bytes=target["size_bytes"], runner=pds_runner)
        if checked != target:
            raise RecoveryError("source identity/path changed during recovery imaging")
        proc = runner.run(argv, timeout=14400)
        if proc.returncode:
            step = argv[argv.index("qemu-img") + 1]
            limit = (f" (write budget {budget // 2**30} GiB: at most {int(offdrive_backup.IMAGE_CAP_FRACTION * 100)}% of the "
                     f"drive's size and within the destination's 3% reserve; an image that big means the drive holds far "
                     f"more non-zero data than expected)" if step == "convert" else "")
            raise RecoveryError(f"recovery image {step} failed{limit}; incomplete output retained: "
                                f"{proc.stderr.strip()}")
    _offline_disk(runner, serial)
    with open(image, "rb") as stream:
        os.fsync(stream.fileno())
    manifest = {"format": "baseline-drive-recovery-v1", "serial": serial,
                "size_bytes": target["size_bytes"], "image": image.name,
                "sha256": _digest(image), "image_bytes": image.stat().st_size,
                "source_compared": True, "complete": True, "boot_verified": False}
    _publish_complete_manifest(folder, manifest)
    return folder


def verify_snapshot(runner, folder, *, expected_serial):
    folder = Path(folder)
    try:
        manifest = json.loads((folder / "MANIFEST.json").read_text())
    except (OSError, ValueError):
        raise RecoveryError("recovery snapshot is incomplete or unreadable") from None
    if (manifest.get("format") != "baseline-drive-recovery-v1" or manifest.get("serial") != expected_serial
            or manifest.get("image") != "drive.qcow2" or manifest.get("complete") is not True
            or manifest.get("source_compared") is not True):
        raise RecoveryError("recovery snapshot identity/completion is invalid")
    image = folder / "drive.qcow2"
    if image.is_symlink() or not image.is_file() or _digest(image) != manifest.get("sha256"):
        raise RecoveryError("recovery image integrity check failed")
    info = _json_command(runner, ["qemu-img", "info", "--output=json", "-f", "qcow2", str(image)])
    if (type(manifest.get("size_bytes")) is not int or manifest["size_bytes"] <= 0
            or info.get("virtual-size") != manifest["size_bytes"] or info.get("format") != "qcow2"
            or image.stat().st_size != manifest.get("image_bytes") or info.get("backing-filename")):
        raise RecoveryError("recovery image size/format/backing does not match a self-contained snapshot")
    proc = runner.run(["qemu-img", "check", "-f", "qcow2", str(image)], timeout=3600)
    if proc.returncode:
        raise RecoveryError("recovery image format verification failed")
    return manifest
