"""Backup of everything on the SK hynix drives to a separate drive (v0.2 row 56).

The one deliberate write outside the SK hynix drives, and it is strictly ADD-ONLY
(direct instruction, 2026-10-01: "you can add to that folder, nothing else; no deleting or
replacement"). Baseline may create NEW files and folders inside
`<destination>/baseline-backups/`. It never deletes, overwrites, renames, replaces or
modifies anything: not its own files and certainly not yours. There is no retention,
cleanup or rollback code in this module; a test fails if a deleting, renaming or
overwriting call is ever added. What that means in practice:

- A backup set is a new, uniquely named folder (`baseline-<UTC time>`). Files inside it are
  created with exclusive creation (`O_EXCL`), so an existing name is an error, never a
  replacement; a name collision gets a new name instead.
- `INCOMPLETE.txt` is written first and `MANIFEST.json` LAST. A set with no manifest is
  incomplete (a failed run just stops; it cleans nothing up). It is safe for YOU to delete
  by hand; Baseline never will.
- The manifest records a SHA-256 for every archive, and the set is read back and verified
  before it counts.
- Nothing can be deleted to make room, so a space guard refuses a backup that would not fit
  with comfortable headroom, and a minimum interval keeps full backups from piling up.
  Removing old sets is your decision.

The destination must be a real, separate, mounted, writable LOCAL drive: never a plain
directory on the root filesystem (the failure mode that silently lands "backups" on the
wrong disk), never one of the SK hynix drives Baseline manages, never the running boot
drive, and never a drive whose identity cannot be read. Validation writes nothing.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

BACKUP_DIR_NAME = "baseline-backups"
MANIFEST_NAME = "MANIFEST.json"
INCOMPLETE_NAME = "INCOMPLETE.txt"
FAILED_VERIFY_NAME = "FAILED_VERIFY.txt"
MANIFEST_KIND = "baseline-backup-set"
SET_RE = re.compile(r"^baseline-\d{8}T\d{6}Z(-\d+)?$")

RESERVE_FRACTION = 0.03        # never leave the drive with less than 3% free
HEADROOM = 1.10                # and require 10% more than the estimated size
DEFAULT_MIN_INTERVAL_HOURS = 168
_CHUNK = 1024 * 1024
_NETWORK_FSTYPES = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "sshfs", "fuse.sshfs", "9p", "ceph", "glusterfs"}
_INCOMPLETE_TEXT = (
    "This backup set was being written by Baseline.\n"
    "If MANIFEST.json is missing from this folder, the run did not finish and the set is incomplete.\n"
    "Baseline never deletes anything. It is safe for you to delete this folder by hand.\n"
)


class BackupError(RuntimeError):
    """A backup that was refused or did not complete. Nothing is ever cleaned up."""


@dataclass(frozen=True)
class Destination:
    path: str
    backup_dir: Path
    source: str
    fstype: str
    serial: str
    disks: tuple


@dataclass(frozen=True)
class BackupSet:
    name: str
    path: Path
    manifest: dict


@dataclass(frozen=True)
class BackupResult:
    set_path: Path | None
    verified: bool
    skipped: bool
    bytes_written: int = 0
    detail: str = ""


def _default_run(argv, timeout=60):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------------------
# The destination
# ---------------------------------------------------------------------------

def _parse_pairs(line: str) -> dict:
    return dict(token.split("=", 1) for token in shlex.split(line) if "=" in token)


def resolve_destination(path: str, *, run, allowed_serials, boot_serial: str | None = None) -> Destination:
    """Check that `path` is a real, separate, safe place to add backups. Writes nothing."""
    if not isinstance(path, str) or not path.strip():
        raise BackupError("no backup destination is configured")
    if "\n" in path or "\x00" in path or not os.path.isabs(path) or os.path.normpath(path) != path:
        raise BackupError(f"backup destination {path!r} must be a clean absolute path")
    if os.path.islink(path) or os.path.realpath(path) != path:
        raise BackupError(f"backup destination {path} is or passes through a symlink; give the real path")
    if not os.path.isdir(path):
        raise BackupError(f"backup destination {path} is not an existing directory")

    proc = run(["findmnt", "-n", "-P", "-T", path, "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"], timeout=15)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise BackupError(f"could not tell what {path} is mounted from")
    mount = _parse_pairs(proc.stdout.strip().splitlines()[0])
    target, source, fstype = mount.get("TARGET", ""), mount.get("SOURCE", ""), mount.get("FSTYPE", "")
    options = set(mount.get("OPTIONS", "").split(","))
    if target == "/":
        raise BackupError(f"{path} is a plain directory on the root filesystem, not a separate mounted drive; "
                          "a backup there would land on the wrong disk")
    if not source.startswith("/dev/") or fstype in _NETWORK_FSTYPES:
        raise BackupError(f"backup destination must be on a local block device, not {source or 'unknown'} ({fstype})")
    if "ro" in options:
        raise BackupError(f"{path} is mounted read-only")

    proc = run(["lsblk", "-s", "-l", "-n", "-o", "NAME,TYPE", source], timeout=15)
    rows = [line.split() for line in proc.stdout.splitlines() if len(line.split()) >= 2] if proc.returncode == 0 else []
    disks = [name for name, kind in rows if kind == "disk"]
    if not disks:
        raise BackupError(f"cannot establish which physical drive {source} is on, so its identity is unknown")
    serials = {}
    for disk in disks:
        info = run(["udevadm", "info", "--query=property", f"--name=/dev/{disk}"], timeout=15)
        serial = ""
        for line in (info.stdout or "").splitlines():
            if line.startswith("ID_SERIAL_SHORT="):
                serial = line.split("=", 1)[1].strip()
        if not serial:
            raise BackupError(f"cannot read the drive identity of /dev/{disk}, so it cannot be shown to be separate")
        serials[disk] = serial
    for disk, serial in serials.items():
        if serial in allowed_serials:
            raise BackupError(f"destination is on /dev/{disk}, one of the SK hynix drives Baseline manages: "
                              "the destination is not separate from the data it protects")
        if boot_serial is not None and serial == boot_serial:
            raise BackupError(f"destination is on /dev/{disk}, the running boot drive")
    return Destination(path=path, backup_dir=Path(path) / BACKUP_DIR_NAME, source=source, fstype=fstype,
                       serial=next(iter(serials.values())), disks=tuple(disks))


def _free_and_total(path) -> tuple:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize


def check_space(dest: Destination, *, needed_bytes: int) -> None:
    """Nothing can be deleted to make room, so be conservative."""
    free, total = _free_and_total(dest.path)
    if free < needed_bytes * HEADROOM:
        raise BackupError(f"not enough free space on the backup drive: {free // 2**30} GiB free, "
                          f"about {int(needed_bytes * HEADROOM) // 2**30} GiB needed")
    if free - needed_bytes < total * RESERVE_FRACTION:
        raise BackupError("this backup would leave the backup drive with too little space "
                          f"(under {int(RESERVE_FRACTION * 100)}% free); free some up yourself first")


def estimate_bytes(sources: dict, *, run) -> int:
    total = 0
    for paths in sources.values():
        for path in paths:
            # Bytes actually stored, not apparent size: a sparse 100 GB disk image holding 3 GB counts as 3 GB.
            proc = run(["du", "-s", "--block-size=1", "-x", "--", path], timeout=600)
            if proc.returncode not in (0, 1):
                raise BackupError(f"could not size source {path}: {proc.stderr.strip()[:200]}")
            first = (proc.stdout or "").split()
            if first and first[0].isdigit():
                total += int(first[0])
    return total


# ---------------------------------------------------------------------------
# Add-only file creation
# ---------------------------------------------------------------------------

class _NewFile:
    """A file created with O_EXCL: it can only ever be a NEW file."""

    def __init__(self, path):
        self.name = str(path)
        self._fd = os.open(self.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)

    def write(self, data: bytes) -> int:
        view = memoryview(data)
        while view:
            view = view[os.write(self._fd, view):]
        return len(data)

    def fsync(self) -> None:
        os.fsync(self._fd)

    def close(self) -> None:
        os.close(self._fd)


def _create_new_file(path) -> _NewFile:
    """Raises FileExistsError if the path already exists; never overwrites."""
    return _NewFile(path)


def _write_new_text(path, text: str) -> None:
    f = _create_new_file(path)
    try:
        f.write(text.encode())
        f.fsync()
    finally:
        f.close()


def _sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _stream_tar(argv, out_file, timeout=None, max_bytes=None) -> tuple:
    """Run tar writing to stdout and stream it into the new file. Returns (bytes, sha256, rc, stderr tail).
    Exit status 1 ("a file changed while being read") is normal on live volumes and is recorded, not fatal.
    `max_bytes` is a hard cap: the archive can never be larger than the data it is backing up (compression
    only shrinks it), so growing past that means something is being read that is not data (for example empty
    space). Stop at once instead of running on."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    h, size = hashlib.sha256(), 0
    for chunk in iter(lambda: proc.stdout.read(_CHUNK), b""):
        out_file.write(chunk)
        h.update(chunk)
        size += len(chunk)
        if max_bytes is not None and size > max_bytes:
            proc.kill()
            proc.wait()
            raise BackupError(f"the backup is growing larger than the data it is backing up ({size} bytes against "
                              f"a limit of {max_bytes}); stopping")
    stderr = proc.stderr.read().decode(errors="replace")
    rc = proc.wait()
    if rc not in (0, 1):
        raise BackupError(f"tar failed (exit {rc}): {stderr.strip()[-300:]}")
    return size, h.hexdigest(), rc, stderr.strip()[-300:]


def _check_readable(path) -> None:
    try:
        with tarfile.open(path, "r:gz") as tf:
            for _ in tf:
                pass
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise BackupError(f"archive {os.path.basename(str(path))} is not a readable tar.gz: {exc}") from exc


# ---------------------------------------------------------------------------
# Sets
# ---------------------------------------------------------------------------

def _read_manifest(set_path) -> dict:
    mpath = Path(set_path) / MANIFEST_NAME
    if not mpath.is_file():
        raise BackupError(f"{Path(set_path).name} has no manifest: it is incomplete")
    try:
        manifest = json.loads(mpath.read_text())
    except ValueError as exc:
        raise BackupError(f"{Path(set_path).name} has an unreadable manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("kind") != MANIFEST_KIND:
        raise BackupError(f"{Path(set_path).name} manifest is not a Baseline backup manifest")
    return manifest


def verify_set(path, run=None) -> bool:
    """Read-only. Raises BackupError unless the set is complete and every archive matches its checksum."""
    set_path = Path(path)
    if (set_path / FAILED_VERIFY_NAME).exists():
        raise BackupError(f"{set_path.name} failed verification when it was made")
    manifest = _read_manifest(set_path)
    archives = manifest.get("archives")
    if not isinstance(archives, list) or not archives:
        raise BackupError(f"{set_path.name} manifest lists no archives")
    for entry in archives:
        name = entry.get("name", "")
        if "/" in name or name in ("", ".", ".."):
            raise BackupError(f"{set_path.name} manifest names an unsafe archive {name!r}")
        archive = set_path / name
        if not archive.is_file():
            raise BackupError(f"{set_path.name} is missing archive {name}")
        if archive.stat().st_size != entry.get("bytes") or _sha256_file(archive) != entry.get("sha256"):
            raise BackupError(f"checksum mismatch for {name} in {set_path.name}")
        _check_readable(archive)
    return True


def _new_set_dir(backup_dir: Path, now: float) -> Path:
    try:
        os.mkdir(backup_dir)
    except FileExistsError:
        if not backup_dir.is_dir() or backup_dir.is_symlink():
            raise BackupError(f"{backup_dir} exists and is not a folder; refusing to touch it") from None
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    for n in range(1, 100):
        candidate = backup_dir / (f"baseline-{stamp}" if n == 1 else f"baseline-{stamp}-{n}")
        try:
            os.mkdir(candidate)
            return candidate
        except FileExistsError:
            continue
    raise BackupError("could not find a free name for the backup set")


def create_backup_set(dest: Destination, sources: dict, *, now: float, budgets: dict | None = None) -> BackupSet:
    """Add one new, verified backup set. `sources` maps an archive label to a list of absolute paths.
    `budgets` optionally maps a label to the most bytes its archive may take (see `_stream_tar`)."""
    for label, paths in sources.items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", label):
            raise BackupError(f"unsafe archive label {label!r}")
        for path in paths:
            if not os.path.isabs(path) or not os.path.exists(path):
                raise BackupError(f"source {path} does not exist; nothing was written")
    set_dir = _new_set_dir(dest.backup_dir, now)
    _write_new_text(set_dir / INCOMPLETE_NAME, _INCOMPLETE_TEXT)
    entries = []
    for label, paths in sources.items():
        archive = set_dir / f"{label}.tar.gz"
        # Files, not blocks: free space is never read. --sparse skips the holes in sparse files (VM disk images),
        # --one-file-system never wanders into another mounted drive, and -z compresses.
        argv = ["tar", "-czf", "-", "--sparse", "--one-file-system", "--numeric-owner", "-C", "/"] \
            + [p.lstrip("/") for p in paths]
        out = _create_new_file(archive)
        try:
            size, streamed_sha, rc, stderr = _stream_tar(argv, out, max_bytes=(budgets or {}).get(label))
            out.fsync()
        finally:
            out.close()
        if _sha256_file(archive) != streamed_sha:
            raise BackupError(f"checksum mismatch reading back {archive.name}: the archive did not write correctly")
        _check_readable(archive)
        entry = {"name": archive.name, "bytes": size, "sha256": streamed_sha, "sources": list(paths)}
        if rc == 1:
            entry["warning"] = "some files changed while being archived: " + stderr
        entries.append(entry)
    manifest = {
        "kind": MANIFEST_KIND, "version": 1, "tool": "offdrive_backup",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "created_epoch": now,
        "host": socket.gethostname(), "archives": entries,
    }
    _write_new_text(set_dir / MANIFEST_NAME, json.dumps(manifest, indent=2))
    try:
        verify_set(set_dir)
    except BackupError:
        _write_new_text(set_dir / FAILED_VERIFY_NAME, "This set failed read-back verification. Do not rely on it.\n")
        raise
    return BackupSet(name=set_dir.name, path=set_dir, manifest=manifest)


def list_sets(dest: Destination) -> list:
    """Complete sets (a valid manifest, no failure marker), newest first. Read-only and cheap: it
    does not re-hash the archives; `verify_set` does."""
    if not dest.backup_dir.is_dir():
        return []
    found = []
    for child in dest.backup_dir.iterdir():
        if not child.is_dir() or child.is_symlink() or not SET_RE.match(child.name):
            continue
        if (child / FAILED_VERIFY_NAME).exists():
            continue
        try:
            manifest = _read_manifest(child)
        except BackupError:
            continue
        found.append(BackupSet(name=child.name, path=child, manifest=manifest))
    found.sort(key=lambda s: (s.manifest.get("created_epoch", 0), s.name), reverse=True)
    return found


def is_due(dest: Destination, *, now: float, min_interval_hours: float = DEFAULT_MIN_INTERVAL_HOURS) -> bool:
    sets = list_sets(dest)
    if not sets:
        return True
    return now - float(sets[0].manifest.get("created_epoch", 0)) >= min_interval_hours * 3600


# ---------------------------------------------------------------------------
# The whole job
# ---------------------------------------------------------------------------

def run_backup(*, destination: str, run, sources: dict, now: float, allowed_serials,
               boot_serial: str | None = None, min_interval_hours: float = DEFAULT_MIN_INTERVAL_HOURS,
               record_success=None, force: bool = False, dry_run: bool = False) -> BackupResult:
    """Validate the destination, skip if a recent set exists, check space, add a verified set, and only
    then record freshness. Raises BackupError (leaving whatever it wrote untouched) on any failure."""
    if not destination:
        raise BackupError("no backup destination is configured")
    dest = resolve_destination(destination, run=run, allowed_serials=allowed_serials, boot_serial=boot_serial)
    if not force and not is_due(dest, now=now, min_interval_hours=min_interval_hours):
        return BackupResult(None, False, True, 0, f"skipped: a backup newer than {min_interval_hours:g}h already exists")
    estimates = {label: estimate_bytes({label: paths}, run=run) for label, paths in sources.items()}
    needed = sum(estimates.values())
    check_space(dest, needed_bytes=needed)
    if dry_run:
        return BackupResult(None, False, False, needed,
                            f"dry run: would add a backup set of at most {needed / 2**30:.1f} GiB of data, compressed, "
                            f"to {dest.backup_dir}; empty space is never copied; nothing was written")
    budgets = {label: int(est * 1.02) + 64 * 2**20 for label, est in estimates.items()}
    made = create_backup_set(dest, sources, now=now, budgets=budgets)
    if record_success is not None:
        record_success([p for paths in sources.values() for p in paths], now)
    written = sum(a["bytes"] for a in made.manifest["archives"])
    return BackupResult(made.path, True, False, written, f"backup set {made.name} written and verified")


# ---------------------------------------------------------------------------
# What is backed up, and the entry point
# ---------------------------------------------------------------------------

# Configuration that lives on the Proxmox install drive (the PC601). Only paths that exist are used.
_PROXMOX_CONFIG_PATHS = ("/etc/pve", "/etc/network/interfaces", "/etc/hosts", "/etc/hostname",
                         "/etc/baseline", "/etc/containers/systemd")
# SESSION_TEMP is ephemeral by design, so it is not worth a copy.
_NOT_BACKED_UP = ("/mnt/SESSION_TEMP",)


def build_sources(*, is_mount=os.path.ismount, exists=os.path.exists) -> dict:
    """Archive label -> absolute paths. A Baseline volume that is not actually mounted is skipped: backing
    up the empty directory that sits under a missing mount would be a false sense of safety."""
    import drive_installer
    volumes = [mp for *_rest, mp in drive_installer.BASELINE_VOLUMES if mp not in _NOT_BACKED_UP and is_mount(mp)]
    config = [p for p in _PROXMOX_CONFIG_PATHS if exists(p)]
    sources = {}
    if volumes:
        sources["baseline-volumes"] = volumes
    if config:
        sources["proxmox-config"] = config
    return sources


def _boot_serial():
    import physical_device_safety as pds
    try:
        return pds.get_boot_device_serial(pds.Runner())
    except Exception:  # noqa: BLE001 - unknown boot drive: the destination checks still apply
        return None


def _record_freshness(targets, now) -> None:
    """Record, on the SK hynix drive (never the backup drive), that these targets were just backed up, so the
    24-hour freshness gate in backup_restore can see it."""
    import backup_restore
    from repair import RealRunner
    runner = RealRunner()
    for target in targets:
        backup_restore.record_backup_manifest(runner, target=target, ts=now)


def main(*, get_setting=None, now=time.time, print_fn=print, run=_default_run, dry_run: bool = False) -> int:
    """Entry point for baseline-backup-offdrive.service. Exit 0 for a verified backup or a skip because a recent
    one exists; 1 for anything else, so a missing or refused backup shows up as a failed unit, never silently."""
    import drive_admin
    if get_setting is None:
        import settings_store
        get_setting = settings_store.get_setting
    destination = get_setting("backups", "offdrive_destination")
    if not destination:
        print_fn("[FAILED] no backup destination is configured (backups.offdrive_destination): no off-drive backup is being made")
        return 1
    sources = build_sources()
    if not sources:
        print_fn("[FAILED] nothing to back up: no Baseline volume is mounted and no configuration was found")
        return 1
    try:
        result = run_backup(destination=destination, run=run, sources=sources, now=now(),
                            allowed_serials=drive_admin.ALLOWED_TARGET_SERIALS, boot_serial=_boot_serial(),
                            min_interval_hours=get_setting("backups", "offdrive_min_interval_hours"),
                            record_success=_record_freshness, dry_run=dry_run)
    except BackupError as exc:
        print_fn(f"[FAILED] {exc}")
        return 1
    print_fn(f"[{'skipped' if result.skipped else 'ok'}] {result.detail}")
    return 0
