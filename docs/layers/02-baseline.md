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

Baseline supports app, VM and LXC state. **VMs and LXCs live on
[INSTALLER_CACHE](04-installer-cache.md)**, and Proxmox does not care where
they are as long as it can reach them. There is no unauthenticated access anywhere in the
system (`recovery_tiers`: only the login screen is credential-free).

BASELINE holds Baseline's own install-wide records: the registry and markers.
VMs and LXCs are not per-persona AppData, and `appdata.py` no longer plans them.
The master PRD's storage table still lists "VM, LXC state" under BASELINE and
needs updating to match.

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
| Install-wide records (registry, markers) | MVP completed | unit tests | `registry.py`, `persist_bind_mounts.py` |
