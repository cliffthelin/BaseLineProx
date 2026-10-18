"""Cardinality checks: where exactly one of something is needed and more than one (or none) is found, nothing is silently chosen.

Baseline assumes one of several things in many places: one Proxmox install on a host, one volume group called `pve`, one drive for a serial, one device for a label. Two Proxmox
drives attached to one machine (a second install, a drive moved from another host) breaks every one of those assumptions at once, and the failure is usually quiet: the first match
wins, or a bare name addresses the wrong drive. This module gives the checks one shape:

  * `exactly_one` / `at_most_one` return the item or raise `CardinalityError` that lists EVERYTHING found, never "the first";
  * `survey` reads the attached disks, volume groups and logical volumes once, read-only, and reports how many Proxmox installs and Baseline drives there are and which volume
    group names are shared;
  * `host_vg` resolves the volume group the RUNNING root lives in by its UUID (a bare `pve` can mean either drive) and can refuse when its name is shared.

Nothing here changes a system: every command is a read.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

_BASELINE_LABEL = re.compile(r"^(BASELINE|INSTALLER_CACHE|SESSION_TEMP|SUBSTRATE(_PERSISTENCE)?|USER(_[A-Z0-9_]+)?|APPDATA_[A-Z0-9_]+)$")


class CardinalityError(ValueError):
    """Raised when one was needed and none or several were found; `found` holds everything that was."""

    def __init__(self, message: str, found=()):
        super().__init__(message)
        self.found = list(found)


def exactly_one(found, what: str, *, describe=str):
    items = list(found)
    if len(items) == 1:
        return items[0]
    if not items:
        raise CardinalityError(f"no {what} was found where exactly one is needed", items)
    names = ", ".join(sorted(describe(i) for i in items))
    plural = what + ("s" if not what.endswith("s") else "")
    raise CardinalityError(f"{len(items)} {plural} were found where exactly one is needed ({names}); not choosing between them", items)


def at_most_one(found, what: str, *, describe=str):
    items = list(found)
    return exactly_one(items, what, describe=describe) if items else None


def duplicates(items, key) -> dict:
    """Every key that more than one item has, with all of those items."""
    groups: dict = {}
    for item in items:
        groups.setdefault(key(item), []).append(item)
    return {k: v for k, v in groups.items() if len(v) > 1}


@dataclass(frozen=True)
class Partition:
    path: str
    label: str | None = None
    fstype: str | None = None


@dataclass(frozen=True)
class Disk:
    path: str
    serial: str | None
    ptuuid: str | None
    size: int
    partitions: tuple = ()


@dataclass(frozen=True)
class VolumeGroup:
    name: str
    uuid: str
    pvs: tuple = ()
    lvs: tuple = ()


@dataclass
class HostSurvey:
    disks: list = field(default_factory=list)
    vgs: list = field(default_factory=list)

    def disk_for_serial(self, serial: str) -> Disk:
        return exactly_one([d for d in self.disks if d.serial == serial], "drive with serial " + serial, describe=lambda d: d.path)

    def vgs_named(self, name: str) -> list:
        return [g for g in self.vgs if g.name == name]

    def duplicate_vg_names(self) -> dict:
        return duplicates(self.vgs, key=lambda g: g.name)

    def _vg_disks(self, vg: VolumeGroup) -> list:
        return [d for d in self.disks if any(pv == p.path or pv.startswith(d.path) for pv in vg.pvs for p in d.partitions) or any(pv.startswith(d.path) for pv in vg.pvs)]

    def proxmox_installs(self) -> list:
        """Disks that carry a volume group shaped like Proxmox's (a root volume with swap or data beside it)."""
        found = []
        for vg in self.vgs:
            if "root" in vg.lvs and ({"swap", "data"} & set(vg.lvs)):
                found += [d for d in self._vg_disks(vg) if d not in found]
        return found

    def baseline_drives(self) -> list:
        """Disks that carry Baseline's own volumes, by filesystem label or by logical volume name."""
        found = [d for d in self.disks if any(p.label and _BASELINE_LABEL.match(p.label) for p in d.partitions)]
        for vg in self.vgs:
            if any(lv.startswith("baseline_") for lv in vg.lvs):
                found += [d for d in self._vg_disks(vg) if d not in found]
        return found

    def assess(self) -> dict:
        installs, baseline, dups = self.proxmox_installs(), self.baseline_drives(), self.duplicate_vg_names()
        problems = []
        if len(installs) > 1:
            problems.append(f"more than one Proxmox install is attached ({', '.join(d.path for d in installs)}); nothing may address one by a shared name")
        for name, groups in dups.items():
            problems.append(f"{len(groups)} volume groups share the name '{name}' ({', '.join(g.uuid for g in groups)}); a command that uses the name alone could act on either")
        return {"proxmox_installs": len(installs), "baseline_drives": len(baseline), "duplicate_vg_names": sorted(dups), "problems": problems, "ambiguous": bool(problems)}


def _json(runner, argv, what: str):
    try:
        proc = runner.run(argv, timeout=20)
    except Exception as exc:                                              # noqa: BLE001 - an unreadable inventory is reported, never treated as empty
        raise CardinalityError(f"{argv[0]} could not be run while reading {what}: {exc}") from exc
    if proc.returncode:
        raise CardinalityError(f"{argv[0]} failed while reading {what}: {(proc.stderr or '').strip()[:200]}")
    try:
        return json.loads(proc.stdout)
    except (TypeError, ValueError) as exc:
        raise CardinalityError(f"{argv[0]} returned unreadable output while reading {what}: {exc}") from exc


def survey(runner) -> HostSurvey:
    listing = _json(runner, ["lsblk", "-J", "-b", "-p", "-o", "NAME,TYPE,SERIAL,SIZE,PTUUID,LABEL,FSTYPE"], "the attached disks")
    disks = []
    for item in listing.get("blockdevices", []) or []:
        if item.get("type") != "disk":
            continue
        parts = tuple(Partition(str(c.get("name")), c.get("label"), c.get("fstype")) for c in item.get("children", []) or [] if isinstance(c, dict))
        disks.append(Disk(str(item.get("name")), item.get("serial"), item.get("ptuuid"), int(item.get("size") or 0), parts))
    pv_rows = _json(runner, ["pvs", "--reportformat", "json", "-o", "pv_name,vg_name,vg_uuid"], "the physical volumes")["report"][0].get("pv", [])
    lv_rows = _json(runner, ["lvs", "--reportformat", "json", "-o", "lv_name,vg_name,vg_uuid"], "the logical volumes")["report"][0].get("lv", [])
    vgs: dict = {}
    for row in pv_rows:
        vg = vgs.setdefault(row["vg_uuid"], {"name": row["vg_name"], "pvs": [], "lvs": []})
        vg["pvs"].append(row["pv_name"])
    for row in lv_rows:
        vgs.setdefault(row["vg_uuid"], {"name": row["vg_name"], "pvs": [], "lvs": []})["lvs"].append(row["lv_name"])
    return HostSurvey(disks, [VolumeGroup(v["name"], uuid, tuple(v["pvs"]), tuple(v["lvs"])) for uuid, v in vgs.items()])


def _vg_name_of_mapper(source: str) -> str | None:
    base = source.rsplit("/", 1)[-1]
    if not source.startswith("/dev/mapper/") or not re.search(r"(?<!-)-(?!-)", base):
        return None
    return re.split(r"(?<!-)-(?!-)", base, maxsplit=1)[0].replace("--", "-")


def host_vg(runner, *, require_unique_name: bool = False) -> dict | None:
    """The volume group the running root filesystem lives in, as {name, uuid, name_shared}, or None when the root is not on LVM. The UUID is read from the active root volume itself, so it is
    right even when another attached drive has a group of the same name; `require_unique_name` refuses in that case for callers that can only address a group by name."""
    source = runner.run(["findmnt", "-n", "-o", "SOURCE", "--mountpoint", "/"], timeout=15)
    if source.returncode or not source.stdout.strip():
        raise CardinalityError("the running root filesystem could not be identified")
    device = source.stdout.strip().splitlines()[0]
    name = _vg_name_of_mapper(device)
    if name is None:
        return None
    s = survey(runner)
    same = s.vgs_named(name)
    if not same:
        raise CardinalityError(f"the running root is in volume group '{name}' but no such group is listed", same)
    if len(same) == 1:
        return {"name": name, "uuid": same[0].uuid, "name_shared": False}
    uuid_proc = runner.run(["lvs", "--noheadings", "-o", "vg_uuid", device], timeout=15)
    actual = (uuid_proc.stdout or "").strip() if not uuid_proc.returncode else ""
    if require_unique_name or actual not in {g.uuid for g in same}:
        raise CardinalityError(f"{len(same)} volume groups are named '{name}' ({', '.join(g.uuid for g in same)}); the name alone does not say which one is meant", same)
    return {"name": name, "uuid": actual, "name_shared": True}
