# 04 · INSTALLER_CACHE

**Status: In progress** · [index](README.md)

What a rebuild needs, never executed. Mounted at `/mnt/INSTALLER_CACHE`,
50-200 GB, `defaults,nosuid,nodev,noexec`: ISOs and packages are consumed by
name through `dpkg`, `mount` and `xorriso`, never run from here.

## Sources for building, not a ceiling on workloads

The operator clarified the 2026-09-30 VM-placement instruction on 2026-10-01:
the cache is a starting/rebuild source, and standard VMs or Docker workloads
without overlays must also work. Nothing limits Baseline to sources or drives
on this volume. The current implementation keeps it vanilla: downloaded
installer/image bytes are hash-checked, then consumed to build templates and
OS overlays on BASELINE. Mutable VM/home/container state does not go here.

[DR117](../design/decision-records/117-real-ubuntu-proxmox-environment.md) proves
Ubuntu's split disk workflow and a full standalone disk allocation with real
Proxmox tools in a disposable clone. The original downloaded image remains
unchanged. Proxmox's enabled ISO stores are available to the ordinary ISO
workflow. General Docker/LXC data placement and Harvester integration still
need implementation and real runtime verification.

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


### Native distro-container increment (DR118, 2026-10-01)

`/containers` uses actual Proxmox templates and native LVM-thin/ZFS linked roots.
Vanilla archives use selected separate cache storage; immutable templates and
resettable roots use clone-capable OS storage; `/home`, `/root`, `/data` bind
directories use protected storage, configurable outside this drive. Eleven
families passed boot and clean rebuild/data checks in the disposable KVM
Proxmox clone, not physical named-volume deployment. openEuler 25.03 failed
setup and is disabled. Binds are excluded from vzdump: dedicated quiesced
backup/restore remains unverified. Containers share the substrate kernel and
do not supply a distro desktop/browser. The nine requested desktop/NAS/mobile
systems remain explicitly uninstalled on `/vms`; see DR118 and v0.2 row73.
