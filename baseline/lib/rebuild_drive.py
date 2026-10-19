"""Rebuild an installed Baseline drive in place: its data is versioned and backed up first, and nothing is formatted, partitioned or removed.

After the update, when a mirror folder is given, the drive's used contents are mirrored there (`mirror`: no empty space, unchanged volumes not rewritten).
The same histories are pushed to the mirror (mirror_history: filed by combination id) when one is given.

Steps: find the drive by its serial (and refuse a copy of another drive's identifier), activate its volume group by UUID and mount its volumes, snapshot every data volume into its git history
(data_history) and write a self-contained bundle of each onto the drive's INSTALLER_CACHE (which a paired twin carries too), unmount, and then, when a reviewed update bundle is given, hand the code
layer to `installed_drive_update` (its own guards: recovery snapshot, reserve, no data restore). Without an update bundle the report says the code layer was not changed. A rebuild never wipes: a layout this build cannot reach in place is reported and left for a separate, typed-confirmation reinstall. A failure before the
backup is complete stops the run with the drive untouched.
"""
from __future__ import annotations

import time
from pathlib import Path

import cache_sync
import data_history
import mirror
import mirror_history
import twin_sync

MOUNT_BASE = "/mnt/REBUILD"


class RebuildError(RuntimeError):
    pass


def volumes_to_add(mounted: dict) -> list:
    """The role volumes this build expects that the drive does not have yet. They are added in place from the group's free space; a missing volume is never a reason to wipe."""
    import drive_installer as di
    wanted = {label for _, _, _, label, _ in di.baseline_volumes_for() if twin_sync.mode_for(label) is not None}
    return sorted(wanted - set(mounted))


def rebuild(runner, *, serial: str, mount_base: str = MOUNT_BASE, update=None, stamp: str | None = None, peer_serials=(), mirror_root=None, allowed_serials=(), cache_sources=()) -> dict:
    stamp = stamp or time.strftime("%Y%m%dT%H%M%S")
    try:
        child = twin_sync.peer_by_serial(runner, serial)
        peers = [twin_sync.peer_by_serial(runner, p) for p in peer_serials]
        attached = twin_sync.attach_twin(runner, child, mount_base=mount_base, include=lambda label: label in data_history.DATA_ROLES or label == "INSTALLER_CACHE")
    except twin_sync.TwinError as exc:
        raise RebuildError(str(exc)) from None
    try:
        mounts = attached["mounts"]
        if "INSTALLER_CACHE" not in mounts:
            raise RebuildError("the drive's INSTALLER_CACHE is not available, so the backup has nowhere to go; nothing was changed")
        volumes = {role: mounts[role] for role in data_history.DATA_ROLES if role in mounts}
        backups = data_history.backup_all(runner, volumes, Path(mounts["INSTALLER_CACHE"]) / "backups" / f"rebuild-{stamp}", message=f"rebuild {stamp}: backup before update", tag=f"rebuild-{stamp}")
        cache = cache_sync.sync(runner, mount=mounts["INSTALLER_CACHE"], vg_uuid=attached["vg_uuid"], sources=list(cache_sources)) if cache_sources else None
        filed = []
        if mirror_root:                                          # the mirror: each volume's version history, filed under the combination of drives it belongs to
            mirror_history.migrate_legacy(mirror_root)
            for role, path in volumes.items():
                filed.append(mirror_history.push(runner, path, mirror_root, child_ids=[child, *peers], this_child=child, role=role))
    finally:
        twin_sync.detach_twin(runner, attached, mount_base=mount_base)
    report = {"drive_child_id": child, "backups": backups, "formatted": False, "volumes_to_add_in_place": volumes_to_add(mounts),
              "wipe_needed": False, "history": filed, "cache": cache}
    if update is None:
        report["code_layer"] = "not changed: no reviewed update bundle was given"
    else:
        report["code_layer"] = update()
    if mirror_root:                                         # the drive is unmounted again: refresh the compact mirror (only what changed is written)
        report["mirror"] = mirror.refresh(runner, serial=serial, child=child, combination=mirror_history.combination_for([child, *peers]), root=mirror_root,
                                          allowed_serials=set(allowed_serials) or {serial})
    return report
