# DR207: Network interface inventory preserves unavailable state

Date: 2026-10-09  
Status: accepted

## Context

`network._physical_nics()` returned an empty list when `/sys/class/net` could
not be read, and `_carrier()` returned `None` on read errors. `list_interfaces()`
converted `None` to `False`, so the TUI could describe an unreadable wired
interface as physically disconnected. The Settings page also hid its live
interface-source error and left the operator with an unlabeled text field.

## Decision

Sysfs inventory and metadata I/O failures raise `NetworkProbeError`. The
lifeline catches those failures at its observation boundary and records
unavailable NIC/carrier facts. `list_interfaces()` preserves an unknown carrier
as `None` with its error instead of coercing it to false; the TUI renders that
state as Unknown. Settings displays the interface-inventory failure as an alert.
Successful empty inventory and carrier value `0` remain distinct observations.

## Evidence

The sysfs and carrier failure regressions failed before implementation. The
combined network, firstboot, readiness, Settings web, and TUI unit suite passes
184 tests with injected sysfs/command responses. No physical network or NIC
state was changed or verified in this run.

## Remaining work

REAL-007 still requires route-attribute preservation and transaction-level
recovery proof. No earlier decision record is superseded.
