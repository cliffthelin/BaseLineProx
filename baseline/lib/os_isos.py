"""OS install images carried onto the drive's own INSTALLER_CACHE/isos.

The machine running the installer offers a folder of images to the installer VM as a read-only share (tag
`baseline-isos`) with a SHA256SUMS file computed there. The installed system copies what fits into its own
INSTALLER_CACHE/isos, verifying every byte against those sums, so the drive can open any carried OS with no other
media and no internet. Images that do not fit are skipped by name, never silently and never partially.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

SHARE_TAG = "baseline-isos"
SUMS = "SHA256SUMS"
_SUM_LINE = re.compile(r"^([0-9a-f]{64}) [ *](.+)$")
_CHUNK = 8 * 1024 ** 2


def _safe_name(name: str) -> bool:
    return bool(name) and name == Path(name).name and not name.startswith(".") and name != SUMS


def parse_sums(text: str) -> dict:
    sums = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _SUM_LINE.match(line)
        if not match or not _safe_name(match.group(2)):
            raise ValueError(f"unusable line in {SUMS}: {line[:80]!r}")
        sums[match.group(2)] = match.group(1)
    return sums


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def build_offer(source: Path, names: list, offer: Path) -> Path:
    """The folder shared with the installer VM: hard links to the chosen images (no space used) plus their sums."""
    source, offer = Path(source), Path(offer)
    for name in names:
        if not _safe_name(name) or not (source / name).is_file():
            raise ValueError(f"{name!r} is not an image in {source}")
    shutil.rmtree(offer, ignore_errors=True)
    offer.mkdir(parents=True)
    lines = []
    for name in names:
        try:
            os.link(source / name, offer / name)
        except OSError as exc:
            raise ValueError(f"cannot offer {name} without copying it (the offer must be on the same filesystem "
                             f"as {source}): {exc}") from exc
        lines.append(f"{_sha256(source / name)}  {name}")
    (offer / SUMS).write_text("\n".join(lines) + "\n")
    return offer


def carry(source: Path, dest: Path, *, reserve_bytes: int) -> dict:
    """Copy each offered image that fits (leaving `reserve_bytes` free), verified against the offered sums."""
    source, dest = Path(source), Path(dest)
    if not (source / SUMS).is_file():
        raise RuntimeError(f"the offered folder has no {SUMS}; nothing can be verified, so nothing is carried")
    sums = parse_sums((source / SUMS).read_text())
    dest.mkdir(parents=True, exist_ok=True)
    report = {"carried": [], "already": [], "skipped": []}
    for name, expected in sums.items():
        origin, target = source / name, dest / name
        if not origin.is_file():
            report["skipped"].append({"name": name, "reason": "listed in the sums but not offered"})
            continue
        size = origin.stat().st_size
        if target.is_file() and target.stat().st_size == size and _sha256(target) == expected:
            report["already"].append({"name": name, "bytes": size, "sha256": expected})
            continue
        if shutil.disk_usage(dest).free - size < reserve_bytes:
            report["skipped"].append({"name": name, "reason": f"not enough space ({size} bytes needed, "
                                      f"{reserve_bytes} kept free)"})
            continue
        partial = target.with_name(target.name + ".partial")
        digest = hashlib.sha256()
        try:
            with open(origin, "rb") as stream, open(partial, "wb") as out:
                while chunk := stream.read(_CHUNK):
                    out.write(chunk)
                    digest.update(chunk)
                out.flush()
                os.fsync(out.fileno())
            if digest.hexdigest() != expected or _sha256(partial) != expected:
                raise RuntimeError(f"{name} does not match the sum computed where it was offered; not kept")
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        report["carried"].append({"name": name, "bytes": size, "sha256": expected})
    return report
