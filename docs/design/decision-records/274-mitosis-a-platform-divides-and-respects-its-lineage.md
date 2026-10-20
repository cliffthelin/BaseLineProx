# 274 - Mitosis: a platform makes a mirror version of itself that splits off, can divide again, and respects its lineage (principle recorded 2026-10-19)

Operator: "Think mitosis. The platform makes a mirror version of itself that splits off and becomes its own platform that can do mitosis as well and split off making more. They do respect their lineage though and hold connections to them."

## The model

- **A platform divides.** A running platform makes a copy of itself (a daughter) that becomes a complete, independent platform on its own drive. The daughter can divide in the same way, to any depth.
- **The mirror is the material.** What divides is the platform's mirror (DR273, `mirror.py`): every volume by role, files only, no empty space. A daughter is made by restoring a mirror onto a new drive, not by installing from scratch and not by copying a whole drive.
- **Lineage is kept and respected.** Every platform records who it came from, all the way back (parent, grandparent, ...), and every parent records its daughters. The record is immutable history, not a setting.
- **Connections are held, never required.** A daughter holds a connection to its lineage (where its parent's mirror is, how to reach it) and a parent holds one to its daughters. They are used for: the daughter's backups going up into the parent's mirror, the parent's updates being offered down, and either side finding the other. A platform with no reachable parent, or in standalone mode, still runs and can still divide (operator, earlier: no user is ever required to connect to a parent).
- **Autonomy.** A daughter owns its own data and decisions; a connection never lets an ancestor read a descendant's secrets (the Vault, which holds credentials, tokens and secrets, is not mirrored upward).

## What already fits

- The child UUID (the drive's disk GUID) already carries the installer lane that made it and a hint of its own serial (DR255); the parent installer's identity is retained.
- The combination id (`parent`-independent hash of the child UUIDs) already files each child under a combination in the mirror; the version history keeps one branch per drive.
- The mirror is by role, verified against the drive's own storage policy, written by change only.
- Update-only: a built platform is changed only by `baseline-rebuild-drive`.

## What mitosis needs that does not exist yet

1. **Repair by file first; restore only as a last resort** (operator, 2026-10-19: "restore from the mirror would only be considered if updated files cannot resolve the problem; whole drive updates damage the drives"). When a platform's files are wrong or missing, the answer is to find the files that differ from the mirror and update only those (the same in-place, by-block, by-change rule the mirror itself is written with), after showing what would change. Restoring a whole volume or drive is allowed only when file repair cannot work: the filesystem is gone or unreadable, or the target is a new, empty drive (a daughter). Even then only used data is written, role by role, never empty space.
   - *Repair* (to build first): compare a volume with its mirror folder and list the differences (a dry run), then update only the differing files, never deleting files the mirror lacks (they may be newer than the mirror) unless the operator asks for that one path.
   - *Restore* (the daughter, and real loss): make the partition table and volume layout from the mirror's layout files, make each filesystem as `volumes.json` describes, copy the role folders back, verify against the storage policy. Last resort and the way a daughter is born.
2. **A lineage record** per platform, e.g. `lineage.json` on SUBSTRATE: `{self, parent, ancestors[], generation, born_from: {mirror snapshot id}, born}`, written once at division and never edited, and mirrored. A parent keeps a `children` registry (child UUIDs, when, from which snapshot).
3. **A new identity per daughter** under the existing rules: a fresh disk GUID stamped with the dividing platform's lane and the daughter's own serial hint; clone detection (`identifiers.stamped_lane`) still refuses a GUID copied from another drive. The daughter's own installer lane (so that it can divide) needs to be defined: whether a daughter is a new lane or keeps its ancestor's is an open decision.
4. **Held connections**: where the parent's mirror is (a mounted drive today, a network address later), recorded in the lineage and used by the managed-mode flows. Network transport is not built.
5. **Division as an operation**: one command or console action ("divide"), update-only toward the source (the source is not changed), erase-free toward an empty target, typed confirmation before any drive is written, and the same used-only, by-change rules.

## Rules carried over

No empty space is stored or written; an existing build is only updated, by file, and only a lost filesystem or a new empty drive is ever written whole; volumes are addressed by role through the build's own table; nothing in a mirror is the Vault's content.
