> Imported 2026-10-11 from the parallel (Codex) effort, where this record is DR247. Numbered DR251 here so it does not collide with this branch's DR245-248. Other DR numbers inside the text refer to that effort's numbering. Not adopted on this branch: build and run output stays on CACHE, the build workspace (operator design, 2026-10-11); kept as the parallel effort's record.

# DR251 (parallel effort DR247) — Build and rehearsal output stays on the backup drive

**Status:** implemented in source; regression tests pass; active CACHE rehearsal stopped
**Date:** 2026-10-11

## Finding

In this repository, `baseline/bin/baseline-allscript-install` hardcoded `/run/media/cane/CACHE/baseline-build` for the package cache and rehearsal VM, and wrote progress/screenshots under the repository checkout on CACHE. Its rehearsal reused a fixed directory by recursively deleting it. Separately, a QEMU rehearsal was found running from `/run/media/cane/CACHE/claude-whats-left`, another checkout, against a disposable sparse raw disk under CACHE. I mistakenly stopped that other checkout’s QEMU with guest ACPI powerdown before confirming ownership; QEMU exited 0 and its script recorded that the expected firstboot checkpoint had not been reached. I did not alter its files. No physical drive was used by that rehearsal.

## Change

The installer workflow now roots build cache, workspaces, progress, and screenshots at `/mnt/10TB/backup/baseline-build`. Before creating any output it verifies that `/mnt/10TB` is mounted and that `/mnt/10TB/backup` is on the same filesystem. If the backup drive is absent, it refuses to fall back elsewhere. Each rehearsal gets a unique new workspace and refuses collisions; previous evidence is never recursively replaced. The standalone offline-cache builder now validates both workspace and output against the mounted backup drive, and its documented invocation uses that location.

New filesystem-backed tests first failed against the old hardcoded CACHE location and missing non-overwrite guard, then passed after the fix. The focused installer/build-location suites pass 11 tests. Their scratch and pytest output were placed under `/mnt/10TB/backup/baseline-tests/pytest-r247`; no FakeRunner/FakeProc or fake process was used for this change.

## Remaining scope

The separate-checkout rehearsal did not reach firstboot; its historical scratch remains on CACHE and was not moved or deleted. This repository’s corrected workflow refuses to write unless the designated backup mount is present. The other checkout was not modified. This source update has not been deployed to PC401. Physical cold boot, internet/firewall, Proxmox browser GUI and native workload/persistence checks remain open under queue row78. PC601 was not touched.
