# DR226: Corrupt recovery state stays visible

**Status:** Accepted  
**Date:** 2026-10-09

## Context

`recovery_mode.read_state()` returned `None` for malformed JSON. The recovery
page then displayed recovery as inactive even though a state file existed and
could not be trusted. It also relied on `path_exists()`, which does not
distinguish every failed observation from a missing file.

## Decision

Read recovery state directly. A genuinely missing file means no recovery
state; other read errors, invalid JSON, or a document without a boolean
`active` field raise `RecoveryStateObservationError`. Recovery discovery and
exit handlers return HTTP 503 with that diagnostic. A corrupt state document
cannot be presented as inactive or overwritten by a recovery exit.

## Evidence and scope

The regression was confirmed against the real `/proc/self/mounts` file, whose
contents are readable but not valid recovery-state JSON. The recovery handler
returns 503 with a state diagnostic. Ten RealRunner integration checks
passed together for recovery state, mount table, fstab, ISO inventory and real
process observations. The checks use existing `/proc`, `/etc/fstab`, and a
real child process; they create no test fixtures and use no FakeRunner or
FakeProc. No physical storage was modified or inspected.

## Remaining work

This covers recovery-state observation and validation in the web view/exit
path. Full recovery operation on a native Baseline installation remains open
under queue items 7 and 26.
