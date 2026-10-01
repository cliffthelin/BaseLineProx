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
exact-serial allowlist, size range, refuses the running boot drive, refuses
anything not a block device. No destructive helper accepts a bare path.

## The Baseline drive, on disk vs. planned

The plan is now **8 partitions**; the drive has **6**. The two AppData
partitions were added to the volume set on 2026-09-30, after the drive was
laid out, and the drive is effectively full (471 of 476.9 GB allocated).

| # | Partition | On disk | Planned | ext4 label |
|---|---|---|---|---|
| 1 | BASELINE | 31 G | yes | fits |
| 2 | INSTALLER_CACHE | 136 G | yes | fits |
| 3 | SESSION_TEMP | 31 G | yes | fits |
| 4 | SUBSTRATE | 1 G | yes | **truncates** to `SUBSTRATE_PERSIS` |
| 5 | USER_ADMIN | 136 G | yes | **truncates** to `USER_PERSISTENCE` |
| 6 | USER_PERSONAL | 136 G | yes | **truncates** to `USER_PERSISTENCE` - same as #5 |
| 7 | APPDATA_ADMIN | - | yes | fits |
| 8 | APPDATA_PERSONAL | - | yes | fits, exactly 16 |

Because ext4 labels truncate, the **GPT partition name is the identity** and
the ext4 label is only a hint (stated in `baseline_drive_layout.py`'s own docstring).

## Status

| Item | Status | Verified | Evidence |
|---|---|---|---|
| Serial-allowlist safety gate | MVP completed | unit tests | `physical_device_safety.py`, DR 49 |
| Baseline drive laid out as partitions 1-6 | MVP completed | real hardware | `baseline_drive_layout.py`, v0.2 row 37 - kernel table re-read and mounting still need root |
| Partition numbering stable when volumes are added | MVP completed | unit tests | `test_adding_appdata_does_not_renumber_existing_partitions` - fixed after an interleaved order moved #6 → #7 |
| `agentIndex.md` written into each partition | MVP completed | unit tests | `baseline_drive_layout.agent_index` - AppData `KeyError` fixed `e629011` |
| AppData partitions 7-8 on the real Baseline drive | On roadmap | none | needs ~40 GB minimum; the drive has no free space. Needs re-layout or a different Baseline drive - an operator decision |
| ext4 label truncation and the persona label collision | On roadmap | - | Fix is `baseline_drive_layout.legacy_relabel_plan`: 6 metadata-only commands on partitions 4-6, no root needed (the operator is in the `disk` group and the devices are `root:disk` 0660). Not applied. v0.2 row 38. Candidate identities: GPT partname, LV name, filesystem UUID |
| Docs re-keyed from kernel letters to serials | On roadmap | - | v0.2 rows 27-29 |
| Record of the 2026-09-30 repartition (an Omarchy ISO on that drive was erased) | On roadmap | - | v0.2 rows 28, 41. Whether it was authorized is unconfirmed |

## Deeper reading

- [`baseline_drive_layout.py`](../../baseline/lib/baseline_drive_layout.py) · [`drive_installer.py`](../../baseline/lib/drive_installer.py) · [`physical_device_safety.py`](../../baseline/lib/physical_device_safety.py)
- [DR 46](../design/decision-records/46-sdb-partitioned-user-persistence-installer-cache-session-temp.md) - the first real partitioning
- [DR 73](../design/decision-records/73-adaptive-volume-sizing.md) - adaptive sizing within each volume's min/max
- [DR 98](../design/decision-records/98-substrate-persistence-and-real-sizing-defaults.md) - the sizing defaults
