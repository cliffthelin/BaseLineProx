# 04 · INSTALLER_CACHE

**Status: In progress** · [index](README.md)

What a rebuild needs, never executed. Mounted at `/mnt/INSTALLER_CACHE`,
50-200 GB, `defaults,nosuid,nodev,noexec`: ISOs and packages are consumed by
name through `dpkg`, `mount` and `xorriso`, never run from here.

## VMs and LXCs live here

VMs and LXCs are kept on this volume (direct instruction, 2026-09-30).
Proxmox has no requirement about where a VM or LXC is, only that it can reach it,
so this volume has to be reachable by Proxmox as a storage location. They are
not per-persona AppData (`appdata.py` excludes them). VMs and LXCs are created today
on Proxmox's own `local-lvm` by default (`vm_provision.DEFAULT_VM_STORAGE`,
`pct_provision.DEFAULT_STORAGE`); pointing that at this volume is not done.
Because the volume is mounted `noexec`, a VM or LXC *disk image* is fine (it is
data, not an executable), but the mount options and the "never executed"
description should be revisited if anything else is stored here.

## Catalog versus reality

[`installer_cache.py`](../../baseline/lib/installer_cache.py) keeps two
questions apart on purpose:

1. `catalog()` - what **should** be there, derived from the modules that own
   those lists (firstboot packages, VM scripts, driver packages), so it cannot
   drift from what the code installs.
2. `scan_cache()` - what **is** there, read from the volume, never inferred.

`reconcile()` joins them. The Installer Cache tab renders only that, so a
missing artifact shows as missing rather than being absent from the page.
Artifact kinds: OS image, apt package, driver/firmware, VM/LXC script, and
container images (Caddy, pinned by digest from Project Hummingbird).

## Known defect

On the development host `/mnt/INSTALLER_CACHE` is a plain directory on the
root filesystem, not the volume, and 25 of 26 catalogued artifacts are
missing. `mount_status()` reports this explicitly. Artifacts written to a
plain directory are silently lost on rebuild.

## Status

| Item | Status | Verified | Evidence |
|---|---|---|---|
| Catalog and reconcile | MVP completed | unit tests | `installer_cache.py` |
| Installer Cache tab | MVP completed | unit tests | not re-checked in a browser after the ID rewrite |
| Caddy image signature | In discovery | registry read | observed, not verified: no cosign or podman on this host |
| Volume actually mounted and populated | On roadmap | none | nothing applied yet |
