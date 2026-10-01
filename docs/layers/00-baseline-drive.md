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
not the running boot drive. **Restricting to specific serials is opt-in** (`expected_serial`),
not enforced. Drive Administration lists *every* non-boot disk of 50 GB or more as a candidate
(`drive_admin.list_candidate_drives`), and the two Baseline serials are only pre-selected as a
suggestion. So the media and NVMe drives on this machine are selectable targets. What stands
between a selection and a write is the login, an explicit pick in the action modal, and a
PolicyKit authentication on each privileged call (v0.2 row 55).

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

## Status

| Item | Status | Verified | Evidence |
|---|---|---|---|
| Target validation gate (block device, minimum size, not the boot drive; serial restriction is opt-in) | MVP completed | unit tests | `physical_device_safety.py`, DR 49 |
| Baseline drive laid out as partitions 1-6 | MVP completed | real hardware | `baseline_drive_layout.py`, v0.2 row 37 - kernel table re-read and mounting still need root |
| Partition numbering stable when volumes are added | MVP completed | unit tests | `test_adding_appdata_does_not_renumber_existing_partitions` - fixed after an interleaved order moved #6 → #7 |
| `agentIndex.md` written into each partition | MVP completed | unit tests | `baseline_drive_layout.agent_index` - AppData `KeyError` fixed `e629011` |
| AppData partitions 7-8 on the real Baseline drive | On roadmap | none | not created yet |
| ext4 label truncation and the persona label collision | MVP completed | real hardware | Relabeled 2026-09-30 (evening): GPT names and ext4 labels read back from the drive as `SUBSTRATE`, `USER_ADMIN`, `USER_PERSONAL`, none mounted. Applied by the operator, not by this session's code. v0.2 row 38 |
| Docs re-keyed from kernel letters to serials | MVP completed | real hardware | `INSTALL.md` re-keyed; dated serial notes atop `SESSION_HANDOFF.md`, DR46, DR48 (v0.2 rows 27-29, mapping read by serial on 2026-09-30) |
| Record of the 2026-09-30 repartition (an Omarchy ISO on that drive was erased) | MVP completed | none | Recorded in `docs/INSTALL.md` (v0.2 row 28). Whether it was authorized is unconfirmed |

## Deeper reading

- [`baseline_drive_layout.py`](../../baseline/lib/baseline_drive_layout.py) · [`drive_installer.py`](../../baseline/lib/drive_installer.py) · [`physical_device_safety.py`](../../baseline/lib/physical_device_safety.py)
- [DR 46](../design/decision-records/46-sdb-partitioned-user-persistence-installer-cache-session-temp.md) - the first real partitioning
- [DR 73](../design/decision-records/73-adaptive-volume-sizing.md) - adaptive sizing within each volume's min/max
- [DR 98](../design/decision-records/98-substrate-persistence-and-real-sizing-defaults.md) - the sizing defaults
