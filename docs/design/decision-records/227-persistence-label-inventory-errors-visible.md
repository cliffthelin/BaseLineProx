# DR227: Persistence label discovery uses a validated inventory

**Status:** Accepted  
**Date:** 2026-10-09

## Context

`blkid -L LABEL` status 2 can mean the label was not found, no device could be
identified, or device identifiers/content could not be read. The persistence
fallback treated every nonzero result as proof that no labeled volume existed,
which could authorize creating another USER volume while discovery was
incomplete.

## Decision

Persistence discovery now reads `lsblk --json --paths --output NAME,LABEL,TYPE`
and validates the complete nonempty device tree before returning an answer.
It returns a device only for one exact label match; it returns `None` only for
a valid inventory with no match. Command failures, malformed inventory, and
duplicate matching labels raise `PersistenceObservationError`. The automatic
local-volume fallback stops with that diagnostic when discovery is unknown.

## Evidence and scope

RealRunner integration checks passed against the live host inventory: the
existing `CACHE` label resolved to a real `/dev` path and an absent audit label
returned no match. A live `blkid -L USER` lookup exited 2 with no diagnostic,
demonstrating why that result cannot distinguish absence from failed device
identification. No block device was written or mounted, and no FakeRunner or
FakeProc was used.

## Remaining work

This verifies the inventory path on the current Linux host. It does not verify
USER-volume self-install or mount behavior on a native Baseline boot. Continue
under queue items 7 and 26; serial-based target selection and physical
installation acceptance remain separate requirements.
