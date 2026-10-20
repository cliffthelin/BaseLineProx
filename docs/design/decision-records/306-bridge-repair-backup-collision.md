# DR306: bridge repair never overwrites an existing backup

**Date:** 2026-10-11  
**Status:** implemented and unit-tested in Codex source; not deployed to PC401

## Context and decision

The bridge-port repair named its backup with a whole-second timestamp and used
`write_text()`. A second repair in that second could replace the first backup,
removing the only copy of an earlier network configuration. Backup creation
now uses exclusive file creation and increments a numeric suffix when the
timestamped path already exists. The configuration rewrite proceeds only after
the complete original file has been written to a new backup path.

## Verification and boundary

A regression test pre-creates the timestamped backup with distinct contents;
it failed before the change and passes afterward, confirming the prior backup
is preserved and the new one contains the current configuration. The focused
bridge/network-retry suite passes **23 tests**, and the full Python unit suite
passes **3,943 tests plus 9 subtests**. This is unit evidence only;
the change is not deployed to PC401. Native network and firewall acceptance
remain open under queue72/74/75/76/78.
