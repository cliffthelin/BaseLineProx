"""Backups that store only what a filesystem is actually using, never the empty space around it.

Operator, 2026-10-01: "Back up must not back empty space"; 2026-10-19: "whole drive backups where empty space is held and written must never happen
again". A whole-device copy stores every non-zero byte of the free space too: after a reinstall that is the previous install's leftovers (PC401's
2026-10-18 image was 48 GiB). Here each volume is read through its own filesystem's allocation map (`partclone`), so free blocks are never read,
compressed with zstd, and checked with `partclone.chkimg`. A filesystem the tool does not understand is REFUSED, never copied whole.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

IMAGE_SLACK = 16 * 2 ** 20           # an image may exceed the used bytes by metadata and framing, never by more than this
FS_TOOLS = {"ext4": "partclone.ext4", "ext3": "partclone.ext3", "ext2": "partclone.ext2", "vfat": "partclone.vfat",
            "xfs": "partclone.xfs", "btrfs": "partclone.btrfs"}


class UsedBackupError(RuntimeError):
    pass


def detect_fstype(path) -> str:
    done = subprocess.run(["blkid", "-p", "-o", "value", "-s", "TYPE", str(path)], capture_output=True, text=True)
    fstype = done.stdout.strip()
    if done.returncode != 0 or fstype not in FS_TOOLS:
        raise UsedBackupError(f"{path} has no filesystem this backup understands (found {fstype or 'none'}); "
                              "it is refused, never copied whole because that would store its empty space")
    return fstype


def accept_size(*, used_bytes: int, image_bytes: int) -> bool:
    if image_bytes > used_bytes + IMAGE_SLACK:
        raise UsedBackupError(f"the image ({image_bytes // 2**20} MiB) is larger than the data it should hold ({used_bytes // 2**20} MiB): "
                              "it contains empty space, so it is not a backup")
    return True


def _info(stderr: str) -> dict:
    def mib(label):
        m = re.search(rf"{label}:\s+([\d.]+) (B|KB|MB|GB|TB)\s*=\s*(\d+) Blocks", stderr)
        return m
    block = re.search(r"Block size:\s+(\d+)", stderr)
    used, size = mib("Space in use"), mib("Device size")
    if not (block and used and size):
        raise UsedBackupError("could not read how much of the volume is in use")
    bs = int(block.group(1))
    return {"used_bytes": int(used.group(3)) * bs, "device_bytes": int(size.group(3)) * bs, "block_size": bs}


def image_volume(source, out_dir, name, *, fstype=None) -> dict:
    """Image one volume (a block device or a file holding a filesystem) into `out_dir/<name>.<fstype>.pc.zst`; returns its record."""
    source, out_dir = Path(source), Path(out_dir)
    fstype = fstype or detect_fstype(source)
    tool = FS_TOOLS.get(fstype)
    if tool is None:
        raise UsedBackupError(f"filesystem {fstype} is not supported; refused rather than copied whole")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.{fstype}.pc.zst"
    log = out_dir / f"{name}.partclone.log"
    clone = subprocess.Popen([tool, "-c", "-L", str(log), "-s", str(source), "-o", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    compress = subprocess.Popen(["zstd", "-q", "-T0", "-o", str(target)], stdin=clone.stdout)
    clone.stdout.close()
    stderr = clone.stderr.read().decode("utf8", "replace")
    compress.wait()
    clone.wait()
    if clone.returncode or compress.returncode:
        target.unlink(missing_ok=True)
        raise UsedBackupError(f"imaging {source} failed: {stderr.strip()[-200:]}")
    info = _info(stderr)
    size = target.stat().st_size
    try:
        accept_size(used_bytes=info["used_bytes"], image_bytes=size)
        if not check_image(target, fstype, log=log):
            raise UsedBackupError(f"the image of {source} did not check")
    except UsedBackupError:
        target.unlink(missing_ok=True)
        raise
    digest = hashlib.sha256()
    with open(target, "rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 2 ** 20), b""):
            digest.update(chunk)
    return {"name": name, "fstype": fstype, "device_bytes": info["device_bytes"], "used_bytes": info["used_bytes"],
            "image": target.name, "image_bytes": size, "sha256": digest.hexdigest(), "includes_unallocated_space": False}


def check_image(image, fstype, *, log=None) -> bool:
    log = log or Path(str(image) + ".check.log")
    decompress = subprocess.Popen(["zstd", "-dc", str(image)], stdout=subprocess.PIPE)
    check = subprocess.run(["partclone.chkimg", "-L", str(log), "-s", "-"], stdin=decompress.stdout, capture_output=True)
    decompress.stdout.close()
    decompress.wait()
    return check.returncode == 0 and decompress.returncode == 0


def restore_volume(image, target, fstype) -> None:
    """Restore into `target` (a file or device, which must already be the right size): only used blocks are written."""
    tool = FS_TOOLS[fstype]
    log = Path(str(target) + ".restore.log")
    decompress = subprocess.Popen(["zstd", "-dc", str(image)], stdout=subprocess.PIPE)
    output = ["-o", str(target)] if Path(target).is_block_device() else ["-O", str(target)]       # -O: a file that already exists
    done = subprocess.run([tool, "-r", "-L", str(log), "-s", "-", *output], stdin=decompress.stdout, capture_output=True)
    decompress.stdout.close()
    decompress.wait()
    if done.returncode:
        raise UsedBackupError(f"restore failed: {done.stderr.decode('utf8', 'replace').strip()[-200:]}")
