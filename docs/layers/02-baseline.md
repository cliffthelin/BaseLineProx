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

Baseline supports app, VM and LXC state. VMs and their installers live on
[INSTALLER_CACHE](04-installer-cache.md). Proxmox does not care where a VM is
as long as it can reach it. There is no guest user anywhere in the system:
without a Proxmox or USER credential a person can only reach the login and
recovery screens (`recovery_tiers.GUEST_ACTIONS`), and nothing else.

`appdata.py` still plans VM and LXC data as AppData overlays at Proxmox's own
paths (`/var/lib/vz/...`). Whether that is the wanted placement has not been
confirmed either way, so it is left as it is.

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
| Install-wide app, VM and LXC state | On roadmap | none | decided; VM/LXC placement in `appdata.py` not confirmed |
