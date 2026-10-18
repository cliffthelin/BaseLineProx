# DR305: bridge NIC bring-up failures stay visible

**Date:** 2026-10-11  
**Status:** implemented and unit-tested in Codex source; not deployed to PC401

## Context

`bridge_port.run()` attempted to bring wired NICs up before probing their
carrier, but `_bring_up()` discarded every `ip link set <nic> up` result. A
permission failure, missing `ip` binary, or other launch error therefore
looked like an ordinary no-carrier observation. That hid an actionable setup
failure in a PC401-critical network path.

## Decision and implementation

Keep trying the remaining NICs, but collect each nonzero command result and
launch error with the NIC name. Return those details in `bring_up_failures`;
when no NIC reports carrier, include the command failure in the visible reason.
Successful NIC discovery and bridge rewrite behavior remain unchanged.

## Verification and boundary

Two regression tests first failed against the old implementation, then passed
after the change: a nonzero `ip link` result and an inability to launch `ip`.
The focused bridge and network-retry suite passes **22 tests**. This is unit
evidence only. The change has not been staged into a PC401 update or ISO and
has not been executed on PC401 hardware. Native network, internet, firewall,
and GUI acceptance remain open under queue72/74/75/76/78.

## Documentation impact

DR302's description of the prior guest network observation remains accurate;
this source change does not establish live bridge configuration or a working
physical link. DR304's disconnect preflight remains unaffected.
