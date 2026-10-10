# DR221: Backup manifest errors stay visible

**Status:** Accepted  
**Date:** 2026-10-09

## Context

`offdrive_backup.list_sets()` treated every `BackupError` as an unfinished set
and silently omitted it. A corrupt or unreadable manifest therefore made a
backup set disappear from listing, freshness checks, and restore planning. A
symlinked `FAILED_VERIFY.txt` could likewise suppress a set without a valid
failure marker.

## Decision

Only a genuinely missing manifest denotes an incomplete write and may be
omitted. Manifest inspection, read, decoding, and JSON errors remain visible
as `BackupError`. Backup roots and markers are inspected without following
symlinks; invalid paths or markers raise an error. A regular failure marker
continues to exclude a failed set, and a set directory that vanished during
enumeration may be skipped.

## Evidence and scope

The focused off-drive backup, Operations, and audit/approval suites passed 105
tests using disposable local files and scripted command runners. Regression
tests cover a corrupt manifest and a redirected failure marker. No physical
backup destination, drive, or archive was accessed.

## Remaining work

Live backup inventory and dry-run verification on the designated backup drive
remain open under queue item 56. This change makes inventory errors visible;
it does not establish real backup-drive behavior.
