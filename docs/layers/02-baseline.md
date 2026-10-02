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

Baseline manages the Proxmox substrate. The clarified storage decision
(2026-10-01, [DR117](../design/decision-records/117-real-ubuntu-proxmox-environment.md))
uses this volume for immutable prepared templates, disposable OS overlays and
runtime metadata (`/mnt/BASELINE/vm-runtime`). A clean OS rebuild may replace
these overlays; it must not discard a user's daily state.

Ubuntu `/home` disks, recipe/account profiles and VMID/name records live on
[USER_<PERSONA>](06-user-persistence.md), as do ordinary VM full writable disks.
[INSTALLER_CACHE](04-installer-cache.md) keeps unchanged public sources. An
ordinary VM needs no overlay. External storage is allowed; the current
Proxmox adapter supports directory stores, not every Proxmox backend.
VM/LXC state is separate from per-application `appdata.py` planning.
There is no unauthenticated access beyond the login screen.

The global registry and active-persona marker remain here in the current
implementation. Recovery/migration of those records is a separate open
architecture question; this increment does not silently move them.

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
