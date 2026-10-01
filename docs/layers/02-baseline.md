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

Baseline supports app, VM and LXC state on this volume. That is the intended
role, not a defect. It is install-wide state, shared across personas, and the
volume's size range (5-50 GB) and mount options (`nosuid,nodev`, not `noexec`)
were chosen for it.

**Follow-up this exposes.** [07](07-appdata.md) and `appdata.py` currently
plan VM and LXC guest data as an overlay on the per-persona AppData volume,
which is the opposite placement. The code has not been changed. Which kinds of
state go on BASELINE and which on AppData needs to be settled per medium
before any plan is applied.

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
| App, VM and LXC state belongs here | On roadmap | none | decided; `appdata.py` placement for VM/LXC not yet reconciled |
