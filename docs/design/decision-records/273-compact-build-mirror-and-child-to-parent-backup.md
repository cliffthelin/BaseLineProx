# 273 - A compact mirror of the build on CACHE, and child-to-parent backup (requirements recorded 2026-10-19; mirror and network path not built)

## What the operator asked (2026-10-19, nearly verbatim)
- Hold a **mirror copy of the build on CACHE that contains no blank space**: if 160 GB of real data goes onto the drive, the mirror holds
  those same 160 GB, in the volumes, with their formatting, and nothing else.
- It holds the **version-controlled persistence data** for itself and for any of its child installs.
- A child install that has had work done on it can **back up to its parent install in managed mode, two ways**: over the network, or by
  attaching the drive to the parent (managed) machine and running a backup there.
- Earlier, 2026-10-01: a backup must not back up empty space; if the drive holds 30 GB the backup is at most 30 GB, and compressed.
- 2026-10-19: PC401 is on hold (not needed for now); PC601 is the working drive.

## What exists today (checked in the code, not assumed)
| Need | State |
|---|---|
| Whole-drive images without empty space | `drive_recovery`: compressed qcow2, compared byte-for-byte; stored in `/mnt/10TB/backup` (PC601's 2026-10-11 image is 6.2 GiB for a 477 GiB drive). A backup, not a mirror on CACHE. |
| A copy of the build on CACHE | `baseline-allscript-install --stage rehearse`: a **sparse file the size of the drive** (full size on paper, only written blocks on disk). It is a test drive, not a version-controlled mirror. |
| Version-controlled persistence data, per child | BUILT: `data_vault` (each data volume in git), `parent_vault` (filed by combination id, one branch per drive), `rebuild_drive` (attaches the drive, snapshots every data volume, pushes to the parent folder). |
| Back up to the parent by attaching the drive | BUILT in `rebuild_drive` (needs root; never formats). Run on this machine, not yet on a real drive. |
| Back up to the parent over the network | **NOT BUILT.** `parent_vault` and `managed_mode` have no network transport; `rebuild_authority` is a local root service for approved rebuilds and is not installed anywhere. |
| A compact, formatted mirror (volumes, filesystems, only used blocks) kept in step with the drive | **NOT BUILT.** |

## Design proposed (needs the operator's yes before it is built)
1. The mirror is a folder on CACHE per drive: one compressed, sparse-aware image per volume (only allocated filesystem blocks, read with
   the filesystem's own allocation map, so 160 GB of data is about 160 GB, less when it compresses), plus the volume group's layout
   (names, sizes, UUIDs, formatting options), so the whole drive can be rebuilt from it without any blank space being stored.
2. Persistence volumes (USER_ADMIN, USER_PERSONAL, APPDATA_*) are not stored as images but as the version-controlled history that already
   exists (git per volume); the mirror's image of those volumes is a pointer to a commit, so history is never duplicated.
3. Each update of the drive (in-place rebuild, twin sync, or a child's backup) adds a new version; old versions stay.
4. Network backup: the child pushes its histories to the parent over an authenticated connection (SSH or HTTPS, the parent's key pinned,
   managed mode on both ends); attached-drive backup uses the existing `rebuild_drive` path. Both write the same history format.

## Open questions
- Are the mirrors to live beside the parent vault on CACHE (`CACHE/baseline-build/mirror/<drive>`), or inside it?
- Network backup: push from the child on a schedule, or only when the parent asks? Which transport do you prefer (SSH key, or the web app's own login over HTTPS)?
- Should the mirror also carry the code layer volumes (root, BASELINE, INSTALLER_CACHE) as images, or only record the build identity and rebuild them from the installer cache?
