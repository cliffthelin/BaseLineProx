> Imported 2026-10-11 from the parallel (Codex) effort, where this record is DR249. Numbered DR253 here so it does not collide with this branch's DR245-248. Other DR numbers inside the text refer to that effort's numbering.

# DR253 (parallel effort DR249) — Scripts inbox follows the active persistence persona

**Status:** Source repair implemented and tested with the production filesystem
runner against isolated temporary files. Not deployed to or verified on PC401.
**Date:** 2026-10-11

## Finding

DR246 recorded repeated `baseline-scripts-inbox.service` failures during a
headless PC401 QEMU boot. The guest journal was unavailable, so the precise
runtime failure was unknown. Source review found a likely cause: the service
gate and its data paths hardcoded `/mnt/USER`, but an independent-drive
installation creates separate persona volumes and mounts the active one at
paths such as `/mnt/USER_ADMIN`.

## Change

`persist_bind_mounts.active_user_mountpoint()` now resolves the active persona
only after validating the independent-drive storage policy and confirming the
persona is enrolled. Legacy installations continue to resolve to `/mnt/USER`.
The persistence setup path reuses this resolver; the scripts-inbox startup gate
checks the resolved mount, and the service derives both its auth database and
inbox directory from the same resolved mount. Policy, marker, or mount
observation errors fail closed. The systemd unit now requests active-persistence
path resolution rather than supplying stale `/mnt/USER` overrides.

Three regression tests use `RealRunner` with real files under pytest's isolated
temporary directory. They cover active admin persona selection and gate mount,
rejection of an unenrolled persona, and legacy mount compatibility. All three
passed. Test scratch is retained under
`/mnt/10TB/backup/baseline-tests/pytest-r249-green3`.

## Verification boundary

No fake runner or fake process was used for this test. This does not establish
that the observed PC401 service failure had this cause: its guest journal was
not read. The changed source has not been deployed to PC401, and no service
restart, physical disk write, network, GUI, firewall, workload, or native boot
was verified. PC601 remains outside this work. Queue row78 remains open.
