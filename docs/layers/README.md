# Baseline layers, volumes and partitions

One page per layer of the system, from the physical drive up to the
applications running on it. Each page says what lives on that layer, what
must never live there, how the workflow touches it, and the status of every
notable package, application and decision on it.

Written 2026-09-30 against commit `e629011`. Statuses are only as current as
that; the code and the [v0.2 work queue](../design/v0.2-work-queue.md) are the
live source of truth.

## Status legend

Every item carries exactly one status. They mean specific things, because a
loose "done" is how this project previously ended up with claims nothing
backed ([decision record 47](../design/decision-records/47-audit-found-contradicted-real-hardware-claims.md)).

| Status | Means |
|---|---|
| **MVP completed** | Built, tested, and works end to end for its minimal scope. The *Verified* column says how far that proof reaches. |
| **In progress** | Partly built. Some layer of it exists and is tested; a named piece is still missing. |
| **On roadmap** | Decided and wanted, not yet built. The design is settled enough to start. |
| **In discovery** | An open question. What to build, or whether to, is not decided yet. |

**Verified** is separate from status, because something can be complete and
still only proven in a test harness:

| Verified | Means |
|---|---|
| real hardware | Exercised on a physical machine, with evidence recorded |
| QEMU | Exercised in a disposable VM, with evidence recorded |
| unit tests | Proven only by the test suite (`tests/unit/`, injected runners) |
| registry read | A fact read from an external system, not exercised here |
| none | Not yet proven at all |

## The stack

```
  applications     apt packages · VM/LXC guests · containers (Caddy) · Flatpak/Snap/AppImage
       |           each one isolated: own data, own registry.db, own owner, mode 0700
       v
  isolation layer  overlays (host apps) and bind mounts (containers) - 08
       |           immutable base below, personal writable layer above
       v
  per-persona      USER_<PERSONA>  - the person's own settings/state   06
  volumes          APPDATA_<PERSONA>           - every app's writable layer        07
       |
  shared volumes   BASELINE                - install-wide state, global registry   02
                   SUBSTRATE   - recovery/substrate config             03
                   INSTALLER_CACHE         - what a rebuild needs, never executed  04
                   SESSION_TEMP            - ephemeral, quarantine                 05
       |
  substrate        Proxmox VE root (pve VG) + Baseline's own services              01
       |
  physical         drives, identified by serial - never by kernel letter           00
```

## Pages

> All nine pages are written. Pages 01-08 were drafted 2026-09-30 from a read of the relevant modules; claims marked *unit tests* are not proven on hardware, and no page has been checked against a running system.

| # | Layer | Status | One line |
|---|---|---|---|
| 00 | [Baseline drive](00-baseline-drive.md) | In progress | Drives by serial; the Baseline drive's on-disk layout is now 2 partitions behind the plan |
| 01 | [Substrate](01-substrate.md) | In progress | Proxmox install pipeline proven in QEMU; real-hardware end to end still pending |
| 02 | [BASELINE](02-baseline.md) | In progress | Install-wide state incl. app/VM/LXC (decided); VM/LXC placement in `appdata.py` still to reconcile |
| 03 | [SUBSTRATE](03-substrate-persistence.md) | In progress | Volume exists and mounts; nothing writes to it yet |
| 04 | [INSTALLER_CACHE](04-installer-cache.md) | In progress | Catalog and tab built; on this machine it is not mounted and 25 of 26 artifacts are missing |
| 05 | [SESSION_TEMP](05-session-temp.md) | MVP completed | Ephemeral state and recovery-mode working state |
| 06 | [USER_PERSISTENCE](06-user-persistence.md) | MVP completed | Per-persona settings/state via bind redirects |
| 07 | [APPDATA](07-appdata.md) | In progress | Per-persona app data volume; planned and in the layout, not yet on any disk |
| 08 | [Application isolation](08-application-isolation.md) | In progress | Overlays, formats, containers, the Caddy gateway |

## Access rule

There is no guest user. Nothing is reachable beyond the login screen without a
credential, and recovery mode needs a validated login like everything else.
No setting and no admin can change that; the only way past is the credential or
the passphrase. This is enforced deny-by-default in `baseline_web.py` and
`settings_web.py` (v0.2 row 43). Recovery mode needs this machine's root password (or
its passphrase) on top of a login (row 45), and a new account can only be
created while there is no user data (row 44). Passwords and passphrases are
stored only as one-way hashes, never encrypted. There are no seeded credentials any more (row 46): the first account and the
machine passphrase come only from first-run setup (row 47), and recovery accepts
either the root password or that passphrase. Open: the admin elevation
passphrase has no way to be set yet (row 48).

## Cross-cutting findings from writing these pages

Documenting the volumes against the code turned up real defects. They are
fixed and tested unless marked otherwise, and listed here because each one
was invisible until something looked at the whole layout at once:

| Finding | Status | Where |
|---|---|---|
| AppData mounted with bare `defaults` (no `nosuid,nodev`) | fixed, `86f86fc` | [07](07-appdata.md) |
| AppData interleaved per persona, renumbering existing Baseline drive partitions (`USER_PERSONAL` 6 → 7) | fixed, `e629011` | [00](00-baseline-drive.md) |
| `baseline_drive_layout._role()` raised `KeyError` for AppData | fixed, `e629011` | [00](00-baseline-drive.md) |
| Rootless Quadlet units targeted `multi-user.target`, so they never started at boot | fixed, `4012834` | [08](08-application-isolation.md) |
| Four LXC guests overlaid one path, silently sharing data | fixed, `5a11c35` | [08](08-application-isolation.md) |
| Web UI served hardware serials, Drive Administration, recovery and the installer/app pages to anyone, and accepted state-changing POSTs without a session | fixed 2026-09-30, v0.2 row 43 | [01](01-substrate.md) |
| ext4 16-char labels: `SUBSTRATE` and the persona volumes truncated or collided on the real drive | fixed, relabeled 2026-09-30 | [03](03-substrate-persistence.md), [06](06-user-persistence.md) |
| `/mnt/INSTALLER_CACHE` is a plain directory on the root filesystem, not the volume | **open** | [04](04-installer-cache.md) |
| SUBSTRATE should hold only a one-way hash of the machine passphrase (v0.2 row 47); no code writes it | **open** | [03](03-substrate-persistence.md) |

## Deeper reading

- [Master PRD](../design/baseline-master-prd.md) - purpose, recipe-driven self-replication
- [Hardened-appliance PRD](../design/hardened-appliance-prd.md) - gateway, measured boot, dual GPU
- [v0.2 work queue](../design/v0.2-work-queue.md) - the live roadmap
- [Decision records](../design/decision-records/) - why each piece is the way it is
- [Docs-vs-code audit, 2026-09-30](../design/docs-vs-code-audit-2026-09-30.md)
