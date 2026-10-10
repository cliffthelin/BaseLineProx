# DR196: Backup test-restore verifies temporary extraction cleanup

Date: 2026-10-09  
Status: accepted

## Context

The Operations `backup_test_restore` action extracted a sample archive into a
fresh temporary directory, verified that it contained files, and then used
`shutil.rmtree(..., ignore_errors=True)`. If cleanup failed, it returned exit
code zero and reported that the temporary folder had been removed while user
data remained on disk.

## Decision

Treat restore, content verification, and cleanup as one operation. Preserve
restore exceptions as a failure. Remove the staging directory with errors
enabled and verify it is absent before returning success. A cleanup error
returns failure and identifies the remaining path, also including the restore
error when both stages fail.

## Evidence

A regression injects a cleanup failure that emulates `ignore_errors=True`
silently leaving the directory. Before the fix, the operation returned zero;
afterward it returns one, emits a failure message, and the test confirms the
residue exists until explicit test cleanup. All 15 `tests/unit/test_operations.py`
tests pass with synthetic backup data and filesystem behavior. No real backup
archive or drive was read.

## Remaining work

This verifies cleanup in the Operations test-restore flow only. Periodic
test-restore coverage across every backup class and native recovery remain open
under queue59 and rows60/77.
