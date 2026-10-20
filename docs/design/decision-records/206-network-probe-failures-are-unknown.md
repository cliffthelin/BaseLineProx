# DR206: Network probe failures are unknown, not absent state

Date: 2026-10-09  
Status: accepted

## Context

`network._route_default()` treated a missing, timed-out, or failed `ip` command
as though no default route existed. `_addr_for()` similarly converted command
failure into no IPv4 address. Lifeline output therefore described failed
observations as absent network configuration. Its route parser also required
`via`, dropping valid gateway-less `default dev ...` routes before address
inspection.

## Decision

Route and address command failures now raise `NetworkProbeError` with the
available diagnostic. `check_lifeline()` catches these errors at the
observation boundary and records a failed `address_assigned` fact that says the
query was unavailable. A successful query with no route or address remains a
distinct observation. Malformed IPv4 output is an explicit probe error.
Bridge-member permission and I/O failures also raise; a missing bridge remains
an empty member list because it can indicate a stale route device. Gateway-less
default routes retain their device so address assignment is still checked;
gateway reachability then reports that the route has no gateway.

## Evidence

The new route/address failure regressions failed before the changes. The
network observation, aliases, firstboot state-machine, and installation
readiness tests pass: 59 tests with scripted command results and injected
observations. No real network configuration was changed or physically tested.

## Remaining work

REAL-007 still requires route-attribute preservation and transaction-level
recovery proof. No earlier decision record is superseded.
