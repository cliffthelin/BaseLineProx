# DR209: Network driver lookup preserves unknown state

Date: 2026-10-09  
Status: accepted

## Context

`is_wired()` converted driver symlink resolution errors into `False`, and
lifeline driver detection used `os.path.exists()` in a way that conflated
permission/read failures with no bound driver. `list_interfaces()` also
described that state as a non-wired adapter, allowing the TUI to label a wired
link as merely available when the driver observation had failed.

## Decision

Driver links are now resolved strictly. A missing link means no driver is
bound; read/resolve failures raise `NetworkProbeError`. `list_interfaces()`
preserves failed driver lookup as `driver_bound=None`, `wired=None`, and a
diagnostic. The lifeline reports unavailable driver observations separately
from confirmed unbound interfaces. The TUI renders unclassifiable link state
as Unknown instead of inferring disconnected/available status.

## Evidence

The driver-resolution regression failed before the change because
`is_wired()` swallowed the injected `PermissionError`. The focused network,
firstboot, readiness, Settings, and TUI suite passes 187 tests with injected
sysfs/command observations. No live interface configuration was changed.

## Remaining work

REAL-007 still requires route-attribute preservation and transaction-level
recovery proof. No earlier decision record is superseded.
