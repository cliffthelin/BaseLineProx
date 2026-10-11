# Merging the parallel (Codex) effort into this branch

Date: 2026-10-11. Two efforts pursue the same result separately: this branch (`claude/whats-left-fixes`, in the standalone
repo `/run/media/cane/CACHE/baseline_project`) and a parallel effort working in the shared tree on the Seagate drive.
Operator direction: take what is useful from either, end with the best of both. This note records what was reviewed, what
was adopted, what was not, and where the two collide. The Seagate tree was only read.

## Adopted from the parallel effort

| What | Where | Notes |
|---|---|---|
| ISO staging omits `__pycache__`, `*.pyc`, `.pytest_cache` | `iso_builder.py`, `test_iso_builder.py` | verbatim; real-filesystem test |
| Active persona's mountpoint, validated against the drive's storage policy, failing closed (legacy `/mnt/USER` only when no independent-drive marker) | `persist_bind_mounts.active_user_mountpoint`, `scripts_inbox.py`, `scripts_inbox_gate.py`, `boot/baseline-scripts-inbox.service`, `test_scripts_inbox_persona_mount.py` | builds on this branch's earlier `active_persona_paths`; supersedes it |
| `scripts_inbox_web.resolve_paths` | implemented here to the parallel effort's test (its test was written before its code) | explicit env wins, neither env means the active volume, one alone is refused |
| Hardware tab renders inxi `Repos` lines as rows | `hardware.py`, tests | validation stays this branch's (any non-schema section may hold string lists) |
| Empty-USB-only test aligned with DR239 | `test_hardware_inventory.py` | verbatim |
| Decision records DR244-249 | imported as DR244 and DR249-253 | renumbered; real PC401 facts (below) |

## Not adopted (and why)

- Build, run and test output on `/mnt/10TB/backup` (its DR247, `AGENTS.md` line, edits to `baseline-allscript-install` and
  `baseline-build-offline-cache`, `test_build_data_location.py`): this branch keeps CACHE as the build workspace and the backup
  folder add-only (operator design).
- Removing the `REAL-012` status paragraph from the first-boot CONFIRM screen and its test change: an existing mechanism
  that was just proven as is; no strong reason to change it.
- Unique per-run rehearsal folders (`create_rehearsal_workspace`): each run is several GB; revisit if evidence from every run is wanted.
- Its living docs (`INSTALL.md`, `SESSION_HANDOFF.md`, queues): they encode the backup-drive policy. Their PC401 facts are
  kept in the imported decision records.

## Where the efforts collide

1. Decision record numbers: both used 244-249. Imported records are renumbered; the next free number on this branch is 254.
2. Output location: backup drive (parallel) versus CACHE (this branch).
3. Same files edited in both trees: `baseline-allscript-install`, `baseline-build-offline-cache`, `firstboot_statemachine.py`,
   `hardware.py`, `scripts_inbox*.py`, `persist_bind_mounts.py`, `iso_builder.py`.
4. PC401: the parallel effort completed a guarded in-place update of the physical drive (its DR245, `boot_verified: false`) and
   booted it headlessly on an overlay (its DR246); this branch's `baseline-allscript-install` wipes and reinstalls it from a
   verified recovery image. These are different strategies for the same drive; the operator chooses, and neither effort writes
   PC401 without the operator's own command.
5. Shared host resources: ports (installer UI 8101, package proxy 32165, builder SSH 22481), KVM memory, `/var/tmp/baseline-self-installer`,
   `/mnt/INSTALLER_CACHE`.
