# DR211: Network modal does not infer interface state

**Status:** Accepted  
**Date:** 2026-10-09

## Context

The network connection modal treated an unreadable or malformed interface
`flags` value as administrative-up. It could therefore display an enabled
switch without evidence. The same modal discarded failed `udevadm` identity
lookups, and an `ip link set` subprocess exception could escape the worker
without a completed result.

## Decision

Administrative state reads raise `NetworkProbeError` on I/O or parse failure.
The modal labels that state Unknown, disables the switch, and does not submit a
state change based on an invented initial value. Hardware detail lookup keeps
unknown values and includes probe diagnostics in the modal. The state-change
operation converts command exceptions into a failure result, then reads the
interface flag back and reports success only when it matches the requested
state.

## Evidence and scope

The focused network, firstboot, readiness, Settings, and TUI suite passed 197
tests using injected command, filesystem, and AST observations. This verifies
the error paths and UI source contract only. No live interface state or udev
database was queried, no network configuration was changed, and Textual was
not installed for an interactive render check.

## Remaining work

REAL-007 still tracks route-attribute preservation, transactional rollback, and
recovery verification without cutting off the active session. This record does
not claim physical network verification.
