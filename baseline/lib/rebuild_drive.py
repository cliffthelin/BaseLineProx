"""Rebuild an installed Baseline drive in place: its data is versioned and backed up first, and nothing is formatted, partitioned or removed.

Steps: find the drive by its serial (and refuse a copy of another drive's identifier), activate its volume group by UUID and mount its volumes, snapshot every data volume into its git history
(data_vault) and write a self-contained bundle of each onto the drive's INSTALLER_CACHE (which a paired twin carries too), unmount, and then, when a reviewed update bundle is given, hand the code
layer to `installed_drive_update` (its own guards: recovery snapshot, reserve, no data restore). Without an update bundle the report says the code layer was not changed. A rebuild never wipes: a layout this build cannot reach in place is reported and left for a separate, typed-confirmation reinstall. A failure before the
backup is complete stops the run with the drive untouched.
"""
from __future__ import annotations

import time
from pathlib import Path

import data_vault
import twin_sync

MOUNT_BASE = "/mnt/REBUILD"


class RebuildError(RuntimeError):
    pass


def volumes_to_add(mounted: dict) -> list:
    """The role volumes this build expects that the drive does not have yet. They are added in place from the group's free space; a missing volume is never a reason to wipe."""
    import drive_installer as di
    wanted = {label for _, _, _, label, _ in di.baseline_volumes_for() if twin_sync.mode_for(label) is not None}
    return sorted(wanted - set(mounted))


def rebuild(runner, *, serial: str, mount_base: str = MOUNT_BASE, update=None, stamp: str | None = None) -> dict:
    stamp = stamp or time.strftime("%Y%m%dT%H%M%S")
    try:
        child = twin_sync.peer_by_serial(runner, serial)
        attached = twin_sync.attach_twin(runner, child, mount_base=mount_base)
    except twin_sync.TwinError as exc:
        raise RebuildError(str(exc)) from None
    try:
        mounts = attached["mounts"]
        if "INSTALLER_CACHE" not in mounts:
            raise RebuildError("the drive's INSTALLER_CACHE is not available, so the backup has nowhere to go; nothing was changed")
        volumes = {role: mounts[role] for role in data_vault.DATA_ROLES if role in mounts}
        backups = data_vault.backup_all(runner, volumes, Path(mounts["INSTALLER_CACHE"]) / "backups" / f"rebuild-{stamp}", message=f"rebuild {stamp}: backup before update", tag=f"rebuild-{stamp}")
    finally:
        twin_sync.detach_twin(runner, attached, mount_base=mount_base)
    report = {"drive_child_id": child, "backups": backups, "formatted": False, "volumes_to_add_in_place": volumes_to_add(mounts),
              "wipe_needed": False}
    if update is None:
        report["code_layer"] = "not changed: no reviewed update bundle was given"
    else:
        report["code_layer"] = update()
    return report
