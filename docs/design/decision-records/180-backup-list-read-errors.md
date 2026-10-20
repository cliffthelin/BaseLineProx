# DR180: Backup listing read errors stay errors

Date: 2026-10-09

## Decision

`backup_restore.list_backup_contents()` raises `BackupReadError` when its real
`tar -tzf` command fails. The `baseline-backup list` CLI prints the error to
stderr and exits nonzero. The backup-list web route returns a refused response
with the read error. Successful empty output remains a valid empty listing.

## Reason

Returning an empty list on a failed `tar` command falsely represented an
unreadable or invalid archive as a valid empty backup. Callers must preserve the
difference between “empty” and “could not read.”

## Verification and limits

Test-first regression coverage failed before the change because
`BackupReadError` did not exist. After implementation, the focused backup,
restore, web-route, and request-validation tests passed: 114 passed. They use
`FakeRunner`; no real archive or disk was read. REAL-004 selective handoff
restore remains open. This decision does not establish physical-drive or
Proxmox verification.
