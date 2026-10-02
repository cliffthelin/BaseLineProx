# 08 · Application isolation

**Status: In progress** · [index](README.md)

The intended model gives each application its own retained data. **Application
overlays and launch boundaries are planned, not applied.** Generated lower/upper
paths do not establish an immutable installed base or process confinement.
Containers have planned app-private binds; their lifecycle remains unverified.
See [the application/whole-OS audit](../design/application-layer-audit-2026-10-01.md)
and DR119 before implementing or interpreting the App Isolation preview.

## Access policy for VMs, LXCs and containers (decided, not built)

VMs, LXCs and containers are accessible by default, and so are new ones. A
User or Admin configuration can switch that to deny anything that is not both
registered and admin-approved. There is no unauthenticated access, so the policy governs
workloads, not people. Nothing in the code implements the setting, the
registration or the approval yet (v0.2 row 42).

VMs and LXCs are out of scope for per-application `appdata.py` overlays.
Proxmox owns their isolation and lifecycle. The current Ubuntu VM recipe
splits disposable OS state on [BASELINE](02-baseline.md) from protected home
state on [USER_<PERSONA>](06-user-persistence.md); standard VM disks are
protected in full. Cache is a vanilla build source, not mutable runtime
storage. Native distro LXC data preservation is proved in disposable KVM (DR118);
per-application guest and OCI adapters remain open.

## Mediums

`appdata.py` defines a contract per medium: apt package,
container, Flatpak, AppImage, Snap, Nix. `confinement_gap(kind)` states what
each medium cannot confine, rather than leaving it implied.

## Containers

[`quadlet.py`](../../baseline/lib/quadlet.py) writes declarative Quadlet
`.container` files that systemd turns into ordinary units, so lifecycle stays
`systemctl` and `journalctl`. Rootless is implemented but defaults off because
it needs a real target user. The Caddy gateway is the first container.

## Status

| Item | Status | Verified | Evidence |
|---|---|---|---|
| Overlay and bind plans per medium | MVP completed | unit tests | `appdata.plan_for` |
| Quadlet unit generation | MVP completed | unit tests | `quadlet.py`; rootless units now target `default.target` (`4012834`) |
| Overlay targets never collide between apps | MVP completed | unit tests | `appdata.target_conflicts`; the LXC collision that motivated it (`5a11c35`) is moot now that VMs and LXCs are not planned here |
| Named container networks (`.network` units) | MVP completed | unit tests | `quadlet.NetworkSpec`, v0.2 row 20; no app plan uses one yet |
| Container volumes must be persistent | MVP completed | unit tests | `quadlet.non_persistent_volumes`; `write_and_start` refuses otherwise (v0.2 row 22) |
| Deny-unless-registered-and-approved option | On roadmap | none | v0.2 row 42; open: where the setting lives, who approves, what "accessible" covers |
| Any plan applied on a host | On roadmap | none | planning only |
| Caddy image verified | In discovery | registry read | digest pinned, signature not verified |


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
