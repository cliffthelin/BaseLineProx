# DR225: QEMU process observation errors stay visible

**Status:** Accepted  
**Date:** 2026-10-09

## Context

The local QEMU host treated invalid PID 0 as an ordinary dead process because
`kill(0, 0)` checks the caller's process group before `/proc/0` was read. It
also returned `False` or an empty command line when procfs inspection failed.
VM status and stop/cleanup decisions could therefore confuse unknown process
state with a confirmed stopped VM. Its ISO inventory similarly returned an
empty list when the configured path was a regular file, hiding a bad path as
an empty catalogue.

## Decision

Process observation requires a positive integer PID. `ProcessLookupError`
remains the positive evidence for an absent process; permission to signal a
process still counts as existence. Failure to read or parse `/proc/<pid>/stat`
or failure to read `/proc/<pid>/cmdline` raises `VmError` with the PID and
cause. An actual empty command line remains an empty list. PID records return
`None` only when the file is missing; malformed, unreadable, or invalid PID
records raise `VmError`. ISO inventory returns empty only for a missing
directory, rejects a symlinked root, errors on invalid/unreadable paths, and
lists only regular `.iso` files.

## Evidence and scope

Five focused integration checks passed against real Linux state and files: a
spawned `sleep` process was observed alive with its actual command line and
then observed absent after reaping; PID 0 was confirmed to produce the old
false-dead result before the fix and now raises `VmError`; and a real regular
file supplied as the ISO directory was confirmed to produce the old empty list
and now raises `VmError`; `/proc/self`, a real symlinked directory, was confirmed
to be rejected as an ISO root. A readable procfs file supplied as the PID
record now raises `VmError` rather than appearing absent. No FakeRunner or
FakeProc was used. No QEMU guest or physical VM was started.

## Remaining work

This fixes PID and procfs error semantics for the local QEMU backend only. VM
lifecycle acceptance under queue item 75 remains open, including guest
reconciliation and physical deployment evidence.
