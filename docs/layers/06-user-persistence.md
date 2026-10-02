# 06 · USER_<PERSONA>

**Status: MVP completed** · [index](README.md)

One volume per persona, holding that person's own settings and state. Default
personas are `admin` and `personal` (`DEFAULT_PERSONAS`); any other is
opt-in. 50-200 GB each, `defaults,nosuid,nodev`. Not `noexec`: the scripts
inbox lives here and an operator may run a pushed script.

Renamed from `USER_PERSISTENCE_<PERSONA>` because that name ran past the
16-character ext4 label limit and `_ADMIN` and `_PERSONAL` truncated to the
same label. The page keeps its old filename so links resolve; the old names
are still recognised.

## How it is used

`persist_bind_mounts.py` bind-mounts `/etc/baseline`, `/var/lib/baseline` and
`/var/log/baseline` from the active persona's volume, so existing modules keep
their absolute paths. `switch_active_persona` unmounts the current persona,
requires the caller to have already authenticated, then mounts and rebinds the
new one. If mounting fails, [recovery mode](../../baseline/lib/recovery_mode.py)
is entered.

## VM data (2026-10-01 increment)

The VM library defaults to `/mnt/USER_ADMIN/vm-data`: Ubuntu's retained home
disk and hash-only recipe/account profile, Proxmox name/VMID control records,
and full writable disks for ordinary VMs without overlays. An Ubuntu OS
rebuild keeps these files and refuses to format an existing home disk.
The current default selects USER_ADMIN explicitly; it does not automatically
migrate VM ownership or storage when the active persona changes.

Actual KVM desktop and Proxmox-clone server rebuilds preserved data
([DR117](../design/decision-records/117-real-ubuntu-proxmox-environment.md)).
Those proofs used file images in separate directories; physical named-volume
mounting, reboot and restore coverage are still open.

## Status

| Item | Status | Verified | Evidence |
|---|---|---|---|
| Per-persona volumes and bind redirects | MVP completed | unit tests | `persist_bind_mounts.py`; says itself not yet run on real hardware (DR 62) |
| Persona switch | MVP completed | unit tests | `switch_active_persona` |
| Label collision on the real Baseline drive | fixed | real hardware | partitions 5 and 6 now read back `USER_ADMIN` / `USER_PERSONAL` in both GPT name and ext4 label |
| Cross-persona access gated by a second passphrase | On roadmap | none | DR 76 describes it; not checked here |


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
