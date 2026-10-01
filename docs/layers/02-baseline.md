# 02 · BASELINE

**Status: In discovery** · [index](README.md)

Install-wide shared state. Mounted at `/mnt/BASELINE`, 5-50 GB
(`drive_installer.SHARED_VOLUMES`), `defaults,nosuid,nodev`. Not `noexec`:
app, VM and LXC state may need to run things stored here.

## What lives here

| Path | Holder | Purpose |
|---|---|---|
| `/mnt/BASELINE/registry/foundation.db` | `registry.GLOBAL_DB_PATH` | The global registry, including every allocated identifier (`naming.py`) |
| `/mnt/BASELINE/state/active_persona` | `persist_bind_mounts.ACTIVE_PERSONA_MARKER_PATH` | Which persona is active; survives a persona switch because BASELINE is never persona-scoped |

## The open question

The volume is described as holding app, VM and LXC *state*. The AppData rule
([07](07-appdata.md)) says application data belongs on a per-persona AppData
volume and nowhere else. Those two statements conflict, and which one wins is
undecided, so this page is **In discovery**. Until it is decided, nothing new
should put application data here.

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
| What else belongs here | In discovery | none | conflict with AppData rule above |
