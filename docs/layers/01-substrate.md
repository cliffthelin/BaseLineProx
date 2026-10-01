# 01 · Substrate

**Status: In progress** · [index](README.md)

Proxmox VE on its own drive (the `pve` volume group), plus Baseline's own
services that run on top of it. This is the layer the rest is built on and
the only one that is rebuilt rather than preserved.

## What lives here

- The Proxmox VE root filesystem and the `pve` LVM volume group.
- Baseline's services: the control-panel web UI, the firstboot state machine
  (`firstboot_statemachine.py`), the read-only Claude Code harness.
- Nothing personal. Credentials, state and logs are redirected off this layer
  onto a USER volume by bind mounts (`persist_bind_mounts.py`), so a rebuild
  of the substrate loses nothing the operator cares about.

## What must never live here

Anything that has to survive a rebuild. `/etc/baseline`, `/var/lib/baseline`
and `/var/log/baseline` are bind-mounted from the active persona's USER
volume; if that volume is not mounted, `ensure_redirect` refuses to touch the
path rather than write through to this disposable layer.

## Status

| Item | Status | Verified | Evidence |
|---|---|---|---|
| Install pipeline (answer file, ISO build, firstboot) | In progress | QEMU | v0.2 work queue; real-hardware end to end still pending |
| Drive targeting by serial, refusing the boot drive | MVP completed | unit tests | `physical_device_safety.py` |
| Control-plane paths redirected onto USER via bind mounts | In progress | unit tests | `persist_bind_mounts.py` says itself it has not run on real hardware (DR 62) |
| Measured boot, gateway | On roadmap | none | [Hardened-appliance PRD](../design/hardened-appliance-prd.md) |

## Deeper reading

[`docs/INSTALL.md`](../INSTALL.md) · [`docs/BAREMETAL_BRINGUP_NOTES.md`](../BAREMETAL_BRINGUP_NOTES.md) · [`firstboot_statemachine.py`](../../baseline/lib/firstboot_statemachine.py)
