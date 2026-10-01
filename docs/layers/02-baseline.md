# 02 · BASELINE

**Status: In progress** · [index](README.md)

Install-wide shared state. Mounted at `/mnt/BASELINE`, 5-50 GB
(`drive_installer.SHARED_VOLUMES`), `defaults,nosuid,nodev`. Not `noexec`:
app, VM and LXC state may need to run things stored here.

## What lives here

| Path | Holder | Purpose |
|---|---|---|
| `/mnt/BASELINE/registry/foundation.db` | `registry.GLOBAL_DB_PATH` | The global registry, including every allocated identifier (`naming.py`) |
| `/mnt/BASELINE/state/active_persona` | `persist_bind_mounts.ACTIVE_PERSONA_MARKER_PATH` | Which persona is active; survives a persona switch because BASELINE is never persona-scoped |

## Decision (2026-09-30)

Baseline supports app, VM and LXC state. VM and LXC *installers* (images and
scripts) are kept on [INSTALLER_CACHE](04-installer-cache.md). Running guests
are not put on that volume, and Proxmox does not care where a guest is as long
as it can reach it. BASELINE holds Baseline's own install-wide state about apps
and guests (registry, markers).

**Not yet reconciled in code.** `appdata.py` plans VM and LXC guest data as
overlays at Proxmox's own paths (`/var/lib/vz/images/<guest>`,
`/var/lib/vz/private/<guest>`), with the writable layer on per-persona AppData.
It is planning only and nothing is applied. Whether that placement is what is
wanted for running guests is still open.

## Known defect

On the development host `/mnt/BASELINE` is a plain directory on the root
disk, not a mount, and a `foundation.db` had already been written there by
earlier page views. Page views no longer create it. The same failure mode is
documented for the cache in [04](04-installer-cache.md).

## Status

| Item | Status | Verified | Evidence |
|---|---|---|---|
| Global registry and identifier allocation | MVP completed | unit tests | `registry.py`, `naming.py` |
| Active-persona marker | MVP completed | unit tests | `persist_bind_mounts.py` |
| Install-wide app/guest state | On roadmap | none | decided; guest placement vs `appdata.py` not yet reconciled |
