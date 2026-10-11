# DR255 - Hierarchical identifiers for installs, substrate, VMs, applications and hardware 

Date: 2026-10-11. Status: approved by the operator 2026-10-11 and implemented (`identifiers.py`, `installer_identity.py`); rollout to the other registries and to component messages follows (see the end). Follows DR254 (host identity). Decided before more is built on it, because changing a
scheme later means changing every registry entry that uses it.

## Requirements

1. Stable: the same inputs always give the same identifier, across rebuilds and reinstalls.
2. Hierarchical: an identifier shows its ancestry (which drive, which install, which VM) without a lookup, and a prefix query lists a
   subtree.
3. Self-describing: layout version, level (kind) and an integrity check live in the identifier.
4. Lane-separated where it matters (host installs differ per installer lane); lane-independent below that (applications and hardware
   components are the same wherever they run).
5. A valid 128-bit UUID in text form, so it works as a GPT disk GUID, an SMBIOS/VM UUID and a filesystem UUID.
6. Mintable on the installed system with no installer present: a child is derived from its parent.
7. One registry shape for every level, so adding a level never changes the registry.

## Layout (32 hex digits, positions 0-31)

| Digits | Host (kind 0) | Substrate / VM (kinds 1, 2) | Application / hardware (kinds 3, 4) |
|---|---|---|---|
| 0-7 | installer lane: first 8 of the lane UUID | installer lane (inherited) | **lane dropped**: 4 = parent pointer (first 4 of the parent's own id), 4 = class of the thing |
| 8-11 | first 4 hex of the serial | same | same |
| 12-15 | last 4 hex of the serial | same | same |
| 16 | layout version (`1`) | same | same |
| 17 | kind (`0`) | `1` substrate, `2` VM or container | `3` application, `4` hardware |
| 18-19 | check byte | same | same |
| 20-23 | host discriminator: first 4 of the host's hash | inherited from the host | inherited from the host |
| 24-31 | rest of the host hash | own id: 8 hex, hash of (parent id, kind, name) | own id: 8 hex, hash of (parent id, kind, name) |

- The serial groups skip non-hex characters and fill with `0` when short (DR254): a recognisable hint of the drive, not the serial.
- Host hash = sha256(lane UUID : full serial), so two drives that share their serial hint still differ.
- Check byte = first byte of sha256("baseline-id-v1:" + the other 30 digits). Integrity, not authenticity.
- Class code = first 4 of sha256("class:" + the class name); codes 0000-00ff are reserved for assigned names.
- Kinds 5-7 are reserved for further layers (volumes, networks); 8-f for experiments. The version digit allows a different layout later
  without touching existing entries (both are readable).
- The lane digits are dropped at the application and hardware levels, as proposed by the operator: those 8 digits then carry the parent
  pointer and the class, so further layers fit without another UUID.

The remaining 16 digits of a host's identifier (header + discriminator) are exactly the space its substrate and VM children inherit and
extend, which is the operator's "reserved for installs of substrate or VMs".

## Minting

`child(parent, kind, name)` is pure: same parent, kind and name give the same identifier. A mint checks the registry; if a different
(parent, kind, name) already holds that identifier (a 1-in-4-billion event per sibling pair) the name is re-hashed with a counter and the
counter is recorded. The installed system mints VM, application and hardware identifiers with the same library; only the host identifier
needs the installer lane.

## Registry

One registry type for every level, keyed by the identifier:
`{kind, level, serial, parent (full parent id), name, layout}`. Ancestry is exact through `parent` and readable from the prefix;
`serial` ties every entry to its drive. The guard keeps reading host entries through its existing type until it reads this one.

## Illustrative values (prototype; lane `4af8c95a-...`, PC601)

```
host       4af8c95a-fd01-271b-10c2-bc48c28f0ace
substrate  4af8c95a-fd01-271b-110d-bc48c1c77a36      baseline
vm         4af8c95a-fd01-271b-124a-bc4812c66066      ubuntu-desktop
application 12c6f39c-fd01-271b-1336-bc48388aa637     chrome in that VM   (lane dropped: 12c6 = parent pointer, f39c = class)
hardware   c1c7f065-fd01-271b-142f-bc4892249f4b      nic ens3 under the substrate
```

## Trade-offs and limits

- The parent pointer is 16 bits and the own id 32 bits; collisions are caught at mint and exact ancestry is the registry's `parent`.
- A drive-hint collision (two serials with the same first and last four hex characters under one lane) is separated by the host
  discriminator and the full-serial hash.
- Changing the host layout once more changes PC601's disk identifier at the next build (first boot sets it; older registry entries are
  retired by the existing migration).

## Open decisions

1. Approve the layout as proposed, or change field widths.
2. Ship the identity library on the installed system so it mints VM, application and hardware identifiers locally.
3. When PC601 moves to the new host layout: stop the running build and rebuild once, or after the current build.
