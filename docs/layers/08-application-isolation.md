# 08 · Application isolation

**Status: In progress** · [index](README.md)

How each application is kept to its own data. Host apps get an overlay: the
installed base is the read-only `lowerdir` (never written), and the `upperdir`
is on the persona's [AppData](07-appdata.md) volume, so the app sees an
ordinary filesystem with no cooperation needed. Containers get bind mounts to
their own app home instead.

## Mediums

`appdata.py` defines a contract per medium: apt package, LXC guest, VM guest,
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
| LXC guests no longer share one overlay path | MVP completed | unit tests | fixed `5a11c35` |
| Container volumes must be persistent | MVP completed | unit tests | `quadlet.non_persistent_volumes`; `write_and_start` refuses otherwise (v0.2 row 22) |
| Any plan applied on a host | On roadmap | none | planning only |
| Caddy image verified | In discovery | registry read | digest pinned, signature not verified |
