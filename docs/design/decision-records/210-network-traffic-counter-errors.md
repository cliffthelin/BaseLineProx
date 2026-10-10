# DR210: Network traffic counter errors are not zero traffic

Date: 2026-10-09  
Status: accepted

## Context

`interface_stats()` returned `(None, None)` for unreadable or malformed
`/sys/class/net/<name>/statistics` counters. `interface_traffic_label()` turned
that into an empty label, which the TUI used for the same presentation as
confirmed zero traffic.

## Decision

Counter I/O and parse failures now raise `NetworkProbeError`. The TUI catches
that error at the display boundary and shows “traffic counters unavailable”
with the diagnostic. A successful read of two zero counters still renders as
no recorded traffic; measured counters retain their formatted totals.

## Evidence

The read-failure and malformed-counter regressions failed before the change.
The focused network, firstboot, readiness, Settings, and TUI suite passes 190
tests using injected observations and filesystem responses. No live traffic
counters or network settings were changed.

## Remaining work

REAL-007 still requires route-attribute preservation and transaction-level
recovery proof. No earlier decision record is superseded.
