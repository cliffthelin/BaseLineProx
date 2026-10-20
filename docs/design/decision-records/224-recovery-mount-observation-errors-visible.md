# DR224: Recovery mount observation errors stay visible

**Status:** Accepted  
**Date:** 2026-10-09

## Context

Persistence mount checks now raise `PersistenceObservationError` when the
kernel mount table cannot be read. Recovery discovery and exit previously let
that exception escape the web handler, producing an unstructured server error.
Treating an unreadable mount table as an empty result would also hide the cause
and risk confusing unknown state with a confirmed missing persona volume.

## Decision

Recovery discovery and exit handlers return HTTP 503 with the observation
diagnostic when mount state is unavailable. Recovery exit does not clear its
state unless a persona is positively confirmed mounted read-write. The HTTP
page displays the error notice. Production continues to use
`/proc/self/mounts`; the optional path argument exists to exercise the same
read path against a real temporary directory in integration checks.

## Evidence and scope

Four focused integration checks passed with `RealRunner`, including live reads
of `/proc/self/mounts` and a real temporary directory that cannot be read as a
mount table. No FakeRunner or FakeProc was used. No physical drive, volume, or
LVM metadata was modified or inspected for this change.

## Remaining work

This closes only recovery web error handling for mount-table read failures.
Native recovery behavior and physical persistence-volume operation remain open
under queue items 7 and 26 and the applicable installation/recovery work.
