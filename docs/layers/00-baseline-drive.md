# 00 · Baseline drive

**Status: In progress** · [index](README.md)

The drives themselves, and how Baseline's volume set is laid onto them. There
are two realizations of the same volume set, and both derive from one source,
[`drive_installer.baseline_volumes_for()`](../../baseline/lib/drive_installer.py):

- **LVM inside the Proxmox `pve` volume group** - `drive_installer.ensure_baseline_volumes`
  creates one logical volume per Baseline volume next to Proxmox's own.
- **Plain GPT on a separate drive** - [`baseline_drive_layout.py`](../../baseline/lib/baseline_drive_layout.py)
  lays each volume out as a GPT partition named for it, ext4 inside, no LVM,
  no root ([decision record 46](../design/decision-records/46-sdb-partitioned-user-persistence-installer-cache-session-temp.md) style).

## Identity is the serial, never the kernel letter

Kernel letters move. On 2026-09-30 they had shifted from what every older doc
said, so a rule written as "never touch `sdb`" now points at an unrelated
16 TB media drive.

| Serial | Model | Kernel letter today | Was | Role |
|---|---|---|---|---|
| `FD01N6557110C271B` | PC601 NVMe SK hynix 512GB | `/dev/sdc` | `sdd` | Proxmox install (`pve` VG) |
| `MD89N41071210AP4E` | PC401 NVMe SK hynix 512GB | `/dev/sdd` | `sdb` | Baseline drive (plain GPT) |

Every destructive step goes through
[`physical_device_safety.validate_target_device`](../../baseline/lib/physical_device_safety.py)
([decision record 49](../design/decision-records/49-single-drive-installer-not-ad-hoc-commands.md)):
the path is not a symlink, it is a real block device, it meets the minimum size, and it is
not the running boot drive. On top of that, **Baseline acts only on the two SK hynix drives it
is set up with** (v0.2 row 55): `drive_admin.ALLOWED_TARGET_SERIALS` is enforced, the picker
never offers any other drive, and `perform_action` refuses any other drive before running a
single command. The media and other NVMe drives on this machine cannot be selected. The one
deliberate exception, a backup destination on a separate drive, is designed but not built
(row 56).

## The Baseline drive, on disk vs. planned

The plan is now **8 partitions**; the drive has **6**. The two AppData
partitions were added to the volume set on 2026-09-30, after the drive was
laid out.

| # | Partition | On disk | Planned | ext4 label |
|---|---|---|---|---|
| 1 | BASELINE | 31 G | yes | fits |
| 2 | INSTALLER_CACHE | 136 G | yes | fits |
| 3 | SESSION_TEMP | 31 G | yes | fits |
| 4 | SUBSTRATE | 1 G | yes | fits (relabeled) |
| 5 | USER_ADMIN | 136 G | yes | fits (relabeled) |
| 6 | USER_PERSONAL | 136 G | yes | fits (relabeled) |
| 7 | APPDATA_ADMIN | - | yes | fits |
| 8 | APPDATA_PERSONAL | - | yes | fits, exactly 16 |

The old names ran past ext4's 16-character label limit and collided. Both layers now carry the short names, but the **GPT partition name remains the identity** and
the ext4 label is only a hint (stated in `baseline_drive_layout.py`'s own docstring).

## Off-drive backup (add-only)

Even the SK hynix drives could be bricked, so everything on them is backed up to a separate drive. The
destination chosen by the operator is `/mnt/10TB/backup`. This is the one deliberate write outside the SK
hynix drives, and it is **strictly add-only** (direct instruction, 2026-10-01): Baseline may add a new
`baseline-backups/` folder and new files inside it, and **never deletes, overwrites, renames, replaces or
modifies anything**, its own files included. There is no retention or cleanup code at all, and a test fails if a
deleting, renaming or overwriting call is ever added.

- **Destination checks** (`offdrive_backup.resolve_destination`, writes nothing): a real mounted local
  drive, never a plain directory on the root filesystem, never read-only, never one of the SK hynix drives
  (checked down through LVM layers), never the running boot drive, never a drive whose identity cannot be read.
- **A set** is a new `baseline-<UTC time>` folder. `INCOMPLETE.txt` is written first and `MANIFEST.json` last,
  with a SHA-256 for every archive; the set is read back and verified before it counts. A set with no manifest
  is incomplete. It is safe for **you** to delete by hand; Baseline never will.
- **Space and cadence:** nothing can be deleted to make room, so a backup is refused if it would not fit with
  10% headroom and leave at least 3% free, and a minimum interval (default one week) stops full backups piling
  up. Clearing old sets is your decision.
- **What is covered:** the mounted Baseline volumes (not the ephemeral SESSION_TEMP; a volume that is not
  actually mounted is skipped, not backed up as an empty directory) and the Proxmox configuration. VMs and LXCs
  live on INSTALLER_CACHE, so they are included.
- **First run:** `baseline-backup-offdrive --dry-run` validates the destination, sizes the data and checks space,
  and writes nothing. Set `backups.offdrive_destination` in the Admin tab first.

Not yet run against real hardware. Open items are in v0.2 rows 56-61.

## Status

| Item | Status | Verified | Evidence |
|---|---|---|---|
| Target validation gate plus an enforced allowlist of the two SK hynix drives | MVP completed | unit tests | `physical_device_safety.py`, `drive_admin.perform_action`, v0.2 row 55 |
| Baseline drive laid out as partitions 1-6 | MVP completed | real hardware | `baseline_drive_layout.py`, v0.2 row 37 - kernel table re-read and mounting still need root |
| Partition numbering stable when volumes are added | MVP completed | unit tests | `test_adding_appdata_does_not_renumber_existing_partitions` - fixed after an interleaved order moved #6 → #7 |
| `agentIndex.md` written into each partition | MVP completed | unit tests | `baseline_drive_layout.agent_index` - AppData `KeyError` fixed `e629011` |
| AppData partitions 7-8 on the real Baseline drive | On roadmap | none | not created yet |
| ext4 label truncation and the persona label collision | MVP completed | real hardware | Relabeled 2026-09-30 (evening): GPT names and ext4 labels read back from the drive as `SUBSTRATE`, `USER_ADMIN`, `USER_PERSONAL`, none mounted. Applied by the operator, not by this session's code. v0.2 row 38 |
| Add-only off-drive backup of the SK hynix drives | In progress | unit tests | `offdrive_backup.py`, 46 tests incl. mutation-checked containment; not run on a real drive (v0.2 row 56) |
| Docs re-keyed from kernel letters to serials | MVP completed | real hardware | `INSTALL.md` re-keyed; dated serial notes atop `SESSION_HANDOFF.md`, DR46, DR48 (v0.2 rows 27-29, mapping read by serial on 2026-09-30) |
| Record of the 2026-09-30 repartition (an Omarchy ISO on that drive was erased) | MVP completed | none | Recorded in `docs/INSTALL.md` (v0.2 row 28). Whether it was authorized is unconfirmed |

## Deeper reading

- [`baseline_drive_layout.py`](../../baseline/lib/baseline_drive_layout.py) · [`drive_installer.py`](../../baseline/lib/drive_installer.py) · [`physical_device_safety.py`](../../baseline/lib/physical_device_safety.py)
- [DR 46](../design/decision-records/46-sdb-partitioned-user-persistence-installer-cache-session-temp.md) - the first real partitioning
- [DR 73](../design/decision-records/73-adaptive-volume-sizing.md) - adaptive sizing within each volume's min/max
- [DR 98](../design/decision-records/98-substrate-persistence-and-real-sizing-defaults.md) - the sizing defaults
