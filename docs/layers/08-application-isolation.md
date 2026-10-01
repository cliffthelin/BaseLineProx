# 08 · Application isolation

**Status: In progress** · [index](README.md)

How each application is kept to its own data. Host apps get an overlay: the
installed base is the read-only `lowerdir` (never written), and the `upperdir`
is on the persona's [AppData](07-appdata.md) volume, so the app sees an
ordinary filesystem with no cooperation needed. Containers get bind mounts to
their own app home instead.

## Access policy for VMs, LXCs and containers (decided, not built)

VMs, LXCs and containers are accessible by default, and so are new ones. A
User or Admin configuration can switch that to deny anything that is not both
registered and admin-approved. There is no guest user, so the policy governs
workloads, not people. Nothing in the code implements the setting, the
registration or the approval yet (v0.2 row 42).

Guests are out of scope for this layer's overlays: VMs and LXCs live on
[INSTALLER_CACHE](04-installer-cache.md), and Proxmox's own isolation (KVM,
namespaces) is what separates them.

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
| Overlay targets never collide between apps | MVP completed | unit tests | `appdata.target_conflicts`; the LXC-guest collision that motivated it (`5a11c35`) is moot now that guests are not planned here |
| Container volumes must be persistent | MVP completed | unit tests | `quadlet.non_persistent_volumes`; `write_and_start` refuses otherwise (v0.2 row 22) |
| Deny-unless-registered-and-approved option | On roadmap | none | v0.2 row 42; open: where the setting lives, who approves, what "accessible" covers |
| Any plan applied on a host | On roadmap | none | planning only |
| Caddy image verified | In discovery | registry read | digest pinned, signature not verified |
