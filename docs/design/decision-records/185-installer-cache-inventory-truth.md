# DR185: Installer Cache inventory requires the mounted cache volume

Date: 2026-10-09

## Context

`installer_cache._listdir_with_sizes` returned an empty list on command failure
and skipped malformed rows. This could present an inaccessible or partially
read cache as empty. A read-only scan also showed `reconcile()` listing files
under `/mnt/INSTALLER_CACHE` even though that path was a plain directory on the
root filesystem, so the page described those files as being on the cache volume.

## Decision

The inventory parser raises `CacheScanError` on failed or malformed listings.
A missing kind subdirectory is treated as empty only when its parent exists.
Malformed listings and symlinks or other non-file entries are rejected rather
than silently omitted or counted as regular cached artifacts.
Reconciliation stops before listing anything if the configured cache root is
not an actual mount point. The page renders unknown inventory and does not
count artifacts as present, missing, or extra after an incomplete scan.

## Verification and limits

128 focused Installer Cache, web, source, and installer-input tests passed with
synthetic runners. A read-only host scan found `/mnt/INSTALLER_CACHE` is not a
mount point; earlier that scan saw files in the fallback directory. After the
change, live reconciliation reports `scanned_ok=False` with zero rows and
extras. No files were moved, deleted, or modified, and no physical cache volume
was verified.

## Follow-up

Installer source updates and the broader runtime work remain open under
REAL-010 and the existing queue, as recorded in
`docs/design/runtime-reality-tasks.md`.
