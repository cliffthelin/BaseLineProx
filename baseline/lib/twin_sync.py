"""Twin sync: two Baseline drives kept the same whenever both are attached to one machine (DR272).

Either drive can be taken away and used on its own; when both are attached again each gains what the other has. What is kept the same depends on the layer:

  * data (USER_ADMIN, USER_PERSONAL, APPDATA_ADMIN, APPDATA_PERSONAL): the NEWEST copy of a file wins on both sides and the version it replaced is kept under that side's own `.baseline-twin/backup`.
    Two copies that differ but have the same age are a conflict: neither is touched and each side gets the other's as `<name>.twin-conflict`. Deletions never propagate (a deleted file comes back
    from the other side), so nothing is lost; unwanted files are removed on both drives on purpose.
  * INSTALLER_CACHE: union. Only missing files are added, both ways; an existing file is never replaced (the cache is content that does not change under a name).
  * SESSION_TEMP is disposable, SUBSTRATE is rebuilt by the code layer, BASELINE holds running VMs' disks, and an unknown role is not known to be safe: none of those are file-synced.
  * the code layer (Proxmox, Baseline's own source) is not copied file by file. `plan_code` says whether this drive's version should be pushed to the twin, and only a version that has passed a boot
    test here (`healthy`) is: the twin stays the known-good one until then, and a version is never pushed backwards.

Every volume pair carries a marker with the pair's id; a volume without a matching marker, a volume that is not a mounted filesystem, the same volume twice, and one inside the other are all refused, so a
sync can never land on the wrong disk. Transfers are `rsync`; nothing here formats, resizes or deletes a volume.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

MARKER = ".baseline-twin-pair"
STATE_DIR = ".baseline-twin"
CONFLICT_SUFFIX = ".twin-conflict"
# What each layer syncs. A role with an `include` list syncs ONLY those folders; every role skips what must never be file-synced between two hosts or while in use: live databases and their journals,
# running VMs' disk images, sockets, pid and lock files. USER_ADMIN holds each host's own identity and state next to the user's files (Proxmox's cluster database, Baseline's databases and credentials,
# host keys), so only the user's own folders are listed there.
_NEVER = ("*.sqlite", "*.sqlite3", "*.sqlite-wal", "*.sqlite-shm", "*.db", "*.db-wal", "*.db-shm", "*.qcow2", "*.raw", "*.img", "*.sock", "*.pid", "*.lock", "*.tmp")
_RULES = {
    "USER_ADMIN": {"mode": "newest", "include": ("home", "settings", "config", "dump")},
    "USER_PERSONAL": {"mode": "newest", "include": None},
    "APPDATA_ADMIN": {"mode": "newest", "include": None},
    "APPDATA_PERSONAL": {"mode": "newest", "include": None},
    "INSTALLER_CACHE": {"mode": "union", "include": None},
}


class TwinError(RuntimeError):
    pass


def mode_for(role: str):
    rule = _RULES.get(role)
    return rule["mode"] if rule else None


def filter_args(role: str | None) -> list:
    """The rsync filters for a role: never the live-state files, and for a role with an include list only those folders."""
    args = [f"--exclude={pattern}" for pattern in _NEVER]
    include = (_RULES.get(role) or {}).get("include") if role else None
    if include:
        for folder in include:
            args += [f"--include=/{folder}/***"]
        args += ["--exclude=*"]
    return args


def write_pair_marker(root, pair_id: str, *, role: str) -> None:
    if not pair_id or any(c in pair_id for c in "\n\r"):
        raise TwinError("a pair id is a plain non-empty token")
    path = Path(root) / MARKER
    path.write_text(json.dumps({"pair": pair_id, "role": role, "written": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")


def read_pair_marker(root) -> dict:
    try:
        return json.loads((Path(root) / MARKER).read_text())
    except (OSError, ValueError):
        raise TwinError(f"{root} is not marked as part of a twin pair") from None


def _check_pair(a: Path, b: Path, pair_id: str, require_mount: bool) -> None:
    ra, rb = a.resolve(), b.resolve()
    if ra == rb:
        raise TwinError("both sides are the same volume")
    if ra in rb.parents or rb in ra.parents:
        raise TwinError("one side is inside the other")
    for root in (ra, rb):
        if not root.is_dir() or root.is_symlink():
            raise TwinError(f"{root} is not a real directory")
        if require_mount and not os.path.ismount(root):
            raise TwinError(f"{root} is not a mounted filesystem (an unmounted volume would sync onto the wrong disk)")
        if read_pair_marker(root).get("pair") != pair_id:
            raise TwinError(f"{root} belongs to a different pair than {pair_id}")
    if require_mount and ra.stat().st_dev == rb.stat().st_dev:
        raise TwinError("both sides are on the same filesystem")


def rsync_argv(src, dst, *, mode: str, backup_dir, role: str | None = None) -> list:
    argv = ["rsync", "-aH", "--numeric-ids", "--itemize-changes", f"--exclude=/{STATE_DIR}/", f"--exclude=/{MARKER}", "--exclude=/lost+found/", f"--exclude=*{CONFLICT_SUFFIX}"]
    if mode == "newest":
        argv += ["--update", "--backup", f"--backup-dir={backup_dir}"]
    elif mode == "union":
        argv += ["--ignore-existing"]
    else:
        raise TwinError(f"unknown sync mode {mode!r}")
    return argv + filter_args(role) + [f"{src}/", f"{dst}/"]


def _transferred(output: str) -> int:
    return sum(1 for line in output.splitlines() if line.startswith(">f"))


def _run(runner, argv, what):
    proc = runner.run(argv, timeout=3600)
    if proc.returncode not in (0, 24):                                      # 24: a file vanished while it was being read, which a live system does
        raise TwinError(f"rsync failed while {what}: {(proc.stderr or '').strip()[-300:]}")
    return proc.stdout or ""


def _ties(runner, a: Path, b: Path, role, deep: bool) -> list:
    """Files that differ (in size, or in content on a deep run) although neither side is newer: the same age cannot say which is right, so they are conflicts, found BEFORE any copy so none is overwritten."""
    argv = ["rsync", "-rtcn" if deep else "-rtn", "--itemize-changes", f"--exclude=/{STATE_DIR}/", f"--exclude=/{MARKER}", "--exclude=/lost+found/", f"--exclude=*{CONFLICT_SUFFIX}", *filter_args(role), f"{a}/", f"{b}/"]
    found = []
    for line in _run(runner, argv, "comparing the two sides").splitlines():
        flags, _, name = line.partition(" ")
        if flags.startswith(">f") and len(flags) > 4 and (flags[2] == "c" or flags[3] == "s") and flags[4] != "t":
            found.append(name)
    return sorted(found)


RESERVE_BYTES = 256 * 1024 ** 2                                           # always left free on the receiving volume


def _bytes_to_copy(runner, argv) -> int:
    """How many bytes a pass would copy, from a dry run of the same command (`--stats` reports the size of what would be transferred)."""
    import re
    out = _run(runner, [argv[0], "-n", "--stats", *argv[1:]], "measuring what to copy")
    match = re.search(r"Total transferred file size:\s*([\d,\.]+)\s*(\w*)", out)
    if not match:
        return 0
    number = float(match.group(1).replace(",", ""))
    unit = {"": 1, "bytes": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}.get(match.group(2), 1)
    return int(number * unit)


def _require_room(runner, argv, dst: Path) -> None:
    needed = _bytes_to_copy(runner, argv)
    free = shutil.disk_usage(dst).free
    if needed + RESERVE_BYTES > free:
        raise TwinError(f"not enough room on {dst.name}: {needed // 1048576} MiB to copy, {free // 1048576} MiB free (keeping {RESERVE_BYTES // 1048576} MiB spare); nothing was copied")


def _rsync_escape(name: str) -> str:
    return "/" + "".join("\\" + c if c in "*?[]\\" else c for c in name)


def sync_volume(runner, a, b, *, mode: str, pair_id: str, stamp: str, require_mount: bool = True, role: str | None = None, deep: bool = False) -> dict:
    """Sync one volume pair in place (see the module docstring for what each mode keeps). Returns {mode, a_to_b, b_to_a, conflicts}."""
    import tempfile
    a, b = Path(a), Path(b)
    _check_pair(a, b, pair_id, require_mount)
    report = {"mode": mode}
    conflicts = _ties(runner, a, b, role, deep) if mode == "newest" else []
    leave_out = None
    if conflicts:
        leave_out = tempfile.NamedTemporaryFile("w", prefix="baseline-twin-skip-", delete=False)
        leave_out.write("".join(_rsync_escape(name) + "\n" for name in conflicts))
        leave_out.close()
    try:
        for key, src, dst in (("a_to_b", a, b), ("b_to_a", b, a)):
            backup = dst / STATE_DIR / "backup" / stamp
            argv = rsync_argv(src, dst, mode=mode, backup_dir=backup, role=role)
            if leave_out is not None:
                argv.insert(1, f"--exclude-from={leave_out.name}")
            _require_room(runner, argv, dst)
            report[key] = _transferred(_run(runner, argv, f"copying {src.name} to {dst.name}"))
    finally:
        if leave_out is not None:
            os.unlink(leave_out.name)
    report["conflicts"] = conflicts
    for name in conflicts:
        for here, there in ((a, b), (b, a)):
            target = here / (name + CONFLICT_SUFFIX)
            if not target.exists():
                shutil.copy2(there / name, target)                         # each side keeps the other's version beside its own; neither original is touched
    return report


def plan_code(mine, twin, *, healthy: bool) -> dict:
    """What to do about the code layer, from each drive's installed version {digest, installed_at}: push, hold, same, twin-newer or unknown."""
    if not isinstance(mine, dict) or not isinstance(twin, dict) or not mine.get("digest") or not twin.get("digest"):
        return {"action": "unknown", "reason": "a drive's installed version could not be read"}
    if mine["digest"] == twin["digest"]:
        return {"action": "same", "reason": "both drives run the same version"}
    if twin.get("installed_at", 0) > mine.get("installed_at", 0):
        return {"action": "twin-newer", "reason": "the twin's version is newer; it is never overwritten with an older one"}
    if not healthy:
        return {"action": "hold", "reason": "this version has not passed a boot test here yet; the twin stays the known-good one"}
    return {"action": "push", "reason": "this version is newer than the twin's and has passed a boot test"}


# --- the pair: configuration, attaching the twin's volumes, and running the whole pair -------------------------------------------------------------
TWIN_CONFIG = "/etc/baseline/twin.json"
PAIR_SCHEME = "baseline-twin-pair-v1"
_SERIAL_OK = __import__("re").compile(r"^[A-Za-z0-9_.-]{8,64}$")


def pair_id_for(serial_a: str, serial_b: str) -> str:
    """The identity of a pair of drives: their two serials, sorted and joined, then hashed. It is built only from what distinguishes the two DRIVES (never from the machine they are attached to, because a
    drive moves between machines), it is the same whichever drive computes it and in whichever order, and nothing random has to be stored or exchanged."""
    import hashlib
    if not (_SERIAL_OK.match(serial_a or "") and _SERIAL_OK.match(serial_b or "")):
        raise TwinError("a drive's serial is plain letters, digits and ._- , 8 to 64 characters")
    if serial_a == serial_b:
        raise TwinError("a drive cannot be its own twin")
    low, high = sorted((serial_a, serial_b))
    return hashlib.sha256(f"{PAIR_SCHEME}:{low}+{high}".encode()).hexdigest()[:32]


def load_twin_config(path=None):
    """{peer_serial} from this drive's own pairing data (runtime data on the persistent admin volume, never in the repository), or None when not paired or the data is not well formed."""
    try:
        data = json.loads(Path(path or TWIN_CONFIG).read_text())
        if isinstance(data.get("peer_serial"), str) and _SERIAL_OK.match(data["peer_serial"]):
            return {"peer_serial": data["peer_serial"]}
    except (OSError, ValueError, AttributeError):
        pass
    return None


def save_twin_config(path, *, peer_serial: str) -> None:
    if not _SERIAL_OK.match(peer_serial or ""):
        raise TwinError("the peer's plain serial is needed")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"peer_serial": peer_serial}) + "\n")


def own_serial(runner) -> str:
    """The serial of the drive the running system lives on: the one disk that carries a physical volume of the running root's volume group."""
    import cardinality
    try:
        host = cardinality.host_vg(runner)
        if host is None:
            raise TwinError("the running system is not on LVM, so its drive cannot be identified for pairing")
        survey = cardinality.survey(runner)
        group = cardinality.exactly_one([g for g in survey.vgs if g.uuid == host["uuid"]], "volume group of the running system", describe=lambda g: g.uuid)
        disk = cardinality.exactly_one([d for d in survey.disks if any(pv.startswith(d.path) for pv in group.pvs)], "drive carrying the running system", describe=lambda d: d.path)
    except cardinality.CardinalityError as exc:
        raise TwinError(str(exc)) from None
    if not disk.serial:
        raise TwinError("the running drive reports no serial")
    return disk.serial


def _cmd(runner, argv, what, timeout=120):
    proc = runner.run(argv, timeout=timeout)
    if proc.returncode:
        raise TwinError(f"{what} failed: {(proc.stderr or proc.stdout or '').strip()[-300:]}")
    return proc.stdout or ""


def attach_twin(runner, peer_serial: str, *, mount_base: str = "/mnt/TWIN") -> dict:
    """Activate the twin drive's volume group (selected by UUID, because both drives may carry a group of the same name) and mount its syncable volumes under `mount_base/<ROLE>`. The twin must be exactly
    one attached drive, and its group must not be the running system's own."""
    import cardinality
    import drive_installer as di
    try:
        survey = cardinality.survey(runner)
        disk = survey.disk_for_serial(peer_serial)
        group = cardinality.exactly_one([g for g in survey.vgs if any(pv.startswith(disk.path) for pv in g.pvs)], "volume group on the twin drive", describe=lambda g: g.uuid)
        host = cardinality.host_vg(runner)
    except cardinality.CardinalityError as exc:
        raise TwinError(str(exc)) from None
    if host and host["uuid"] == group.uuid:
        raise TwinError("the twin's volume group is the running system's own; the twin must be the OTHER drive")
    select = f"vg_uuid={group.uuid}"
    _cmd(runner, ["vgchange", "-ay", "--select", select], "activating the twin's volume group")
    paths = {}
    for line in _cmd(runner, ["lvs", "--noheadings", "-o", "lv_name,lv_path", "--select", select], "listing the twin's volumes").splitlines():
        words = line.split()
        if len(words) == 2:
            paths[words[0]] = words[1]
    mounts = {}
    try:
        for lv_name, _, _, label, _ in di.baseline_volumes_for():
            if mode_for(label) is None or lv_name not in paths:
                continue
            target = Path(mount_base) / label
            target.mkdir(parents=True, exist_ok=True)
            _cmd(runner, ["mount", "-o", "nodev,nosuid", paths[lv_name], str(target)], f"mounting the twin's {label}")
            mounts[label] = str(target)
    except TwinError:
        detach_twin(runner, {"vg_uuid": group.uuid, "mounts": mounts}, mount_base=mount_base)
        raise
    return {"vg_uuid": group.uuid, "mounts": mounts}


def detach_twin(runner, attached: dict, *, mount_base: str = "/mnt/TWIN") -> None:
    for label in sorted(attached.get("mounts", {}), reverse=True):
        runner.run(["umount", attached["mounts"][label]], timeout=120)
    runner.run(["vgchange", "-an", "--select", f"vg_uuid={attached['vg_uuid']}"], timeout=120)


def local_mounts(base: str = "/mnt") -> dict:
    return {label: str(Path(base) / label) for label in _RULES}


def pair_drives(runner, peer_serial: str, *, config_path=None, mount_base: str = "/mnt/TWIN", local_base: str = "/mnt") -> dict:
    """First-time pairing: mark every syncable volume on BOTH drives with the pair id (derived from the two serials) and record the pairing on both, so either drive finds the other when it is the one that
    boots. Refuses a volume already marked for a different pair."""
    pair_id = pair_id_for(own_serial(runner), peer_serial)
    mine = own_serial(runner)
    attached = attach_twin(runner, peer_serial, mount_base=mount_base)
    try:
        here = local_mounts(local_base)
        for label, twin_root in attached["mounts"].items():
            for root in (Path(here[label]), Path(twin_root)):
                try:
                    existing = read_pair_marker(root).get("pair")
                except TwinError:
                    existing = None
                if existing not in (None, pair_id):
                    raise TwinError(f"{root} is already part of a different pair")
            for root in (Path(here[label]), Path(twin_root)):
                write_pair_marker(root, pair_id, role=label)
        save_twin_config(config_path or TWIN_CONFIG, peer_serial=peer_serial)
        if "USER_ADMIN" in attached["mounts"]:                              # the twin's own copy of the pairing, where ITS /etc/baseline lives, naming this drive as its peer
            save_twin_config(Path(attached["mounts"]["USER_ADMIN"]) / "etc-baseline" / "twin.json", peer_serial=mine)
        return {"pair": pair_id, "volumes": sorted(attached["mounts"])}
    finally:
        detach_twin(runner, attached, mount_base=mount_base)


def sync_pair(runner, *, config_path=None, mount_base: str = "/mnt/TWIN", local_base: str = "/mnt", stamp: str | None = None, deep: bool = False) -> dict:
    """One run for a paired drive: attach the twin, sync every syncable volume, detach. Returns {volumes: {role: report}}; a volume that fails is reported without stopping the others."""
    config = load_twin_config(config_path)
    if config is None:
        raise TwinError("this drive is not paired with a twin")
    pair_id = pair_id_for(own_serial(runner), config["peer_serial"])
    stamp = stamp or time.strftime("%Y%m%dT%H%M%S")
    attached = attach_twin(runner, config["peer_serial"], mount_base=mount_base)
    results = {}
    try:
        here = local_mounts(local_base)
        for label, twin_root in sorted(attached["mounts"].items()):
            try:
                results[label] = sync_volume(runner, here[label], twin_root, mode=mode_for(label), pair_id=pair_id, stamp=stamp, role=label, deep=deep)
            except TwinError as exc:
                results[label] = {"error": str(exc)}
    finally:
        detach_twin(runner, attached, mount_base=mount_base)
    return {"pair": pair_id, "stamp": stamp, "volumes": results}


# --- the code layer's version and the boot-health gate ---------------------------------------------------------------------------------------------
INSTALLED_FILE = "opt/baseline/INSTALLED.json"
HEALTH_DIR = "var/lib/baseline/health"
HEALTH_UNITS = ("pveproxy.service", "pvedaemon.service", "baseline-web.service")


def installed_digest(root="/") -> str:
    """A digest of the installed Baseline source (everything under /opt/baseline/lib and /opt/baseline/bin), so two drives can say whether they run the same version without a version number to keep."""
    import hashlib
    base = Path(root) / "opt/baseline"
    digest = hashlib.sha256()
    for folder in ("lib", "bin"):
        for path in sorted((base / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(str(path.relative_to(base)).encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def write_installed(root="/", *, now=None) -> dict:
    info = {"digest": installed_digest(root), "installed_at": int(now if now is not None else time.time())}
    target = Path(root) / INSTALLED_FILE
    target.write_text(json.dumps(info) + "\n")
    return info


def read_installed(root="/"):
    try:
        data = json.loads((Path(root) / INSTALLED_FILE).read_text())
        return data if isinstance(data.get("digest"), str) and isinstance(data.get("installed_at"), int) else None
    except (OSError, ValueError, AttributeError):
        return None


def health_mark(runner, *, root="/") -> dict:
    """Mark the running version healthy once its core services are active after a boot. The twin is offered a version only after this has been written for it."""
    installed = read_installed(root)
    if installed is None:
        raise TwinError("no installed version is recorded on this drive")
    down = [unit for unit in HEALTH_UNITS if runner.run(["systemctl", "is-active", unit], timeout=20).returncode != 0]
    if down:
        return {"healthy": False, "digest": installed["digest"], "inactive": down}
    folder = Path(root) / HEALTH_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{installed['digest']}.ok").write_text(time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
    return {"healthy": True, "digest": installed["digest"], "inactive": []}


def is_healthy(digest: str, *, root="/") -> bool:
    return (Path(root) / HEALTH_DIR / f"{digest}.ok").is_file()


def peer_attached(runner, peer_serial: str) -> bool:
    import cardinality
    try:
        return any(d.serial == peer_serial for d in cardinality.survey(runner).disks)
    except cardinality.CardinalityError:
        return False
