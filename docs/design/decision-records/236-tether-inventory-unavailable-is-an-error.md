# DR236 — Missing tether inventory is an observation error

**Status:** Implemented and unit verified; no network interface was changed  
**Date:** 2026-10-09

## Context

`find_tether_candidates` returned an empty candidate list when
`/sys/class/net` was missing. `auto_tether` then reported that no tether device
was connected, conflating an unavailable kernel inventory with an observed
absence of tether devices.

## Decision

Treat a missing network-interface inventory as `TetherProbeError`. The public
`auto_tether` result reports stage `probe_error`; an empty list and
`no_candidate` are reserved for a readable inventory that contains no
supported tether interface.

## Evidence and scope

The regression test failed before the fix because `auto_tether` returned
`no_candidate`. It now verifies `probe_error` and the inventory detail. All
seven tether-truthfulness tests passed. No network command was run by the
regression test, no interface was changed, and no FakeRunner/FakeProc was used.

## Remaining work

No physical tether, DHCP, internet, or firewall behavior was verified. Those
runtime checks remain outside this inventory-error correction.
