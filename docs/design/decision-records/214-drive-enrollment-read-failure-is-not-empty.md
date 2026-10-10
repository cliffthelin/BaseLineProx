# DR214: Drive enrollment read failures are not an empty allowlist

**Status:** Accepted  
**Date:** 2026-10-09

## Context

`drive_enrollment.enrolled_serials()` caught every registry exception and
returned an empty set. The drive picker and backup destination validation could
therefore mistake unavailable enrollment state for a confirmed absence of
enrolled drives.

## Decision

Enrollment lookup raises `DriveEnrollmentError` with the underlying diagnostic
when the registry cannot be read. The existing drive-action request validation
surfaces it as a refusal, drive inventory wraps it as an inventory error, and
off-drive backup validation refuses with a `BackupError`. No caller may use an
unreadable enrollment registry as an empty result.

## Evidence and scope

The focused drive-enrollment, off-drive-backup, drive-admin, and web suite
passed 394 tests against scripted runners and disposable registry files. The
failure regression injects a registry read error. No physical drive was
inspected or modified, and no real backup was created.

## Remaining work

This closes the enrollment false-empty path only. It does not establish live
drive enumeration or backup recovery. REAL-005 still tracks full storage-graph
identity and physical/disposable-Proxmox verification.
