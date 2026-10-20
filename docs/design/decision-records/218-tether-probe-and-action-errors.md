# DR218: Tether probe and action errors remain visible

**Status:** Accepted  
**Date:** 2026-10-09

## Context

USB tether discovery treated inaccessible `/sys/class/net` entries and driver
links as confirmed absence. Bring-up ignored a failed `ip link set`, treated a
carrier read error as no carrier, and treated an unsuccessful IPv4 query as no
address. The regular Tether action also discarded the returned result and only
refreshed the network view. Those paths could turn a broken probe or failed
operation into an inaccurate device/hotspot diagnosis.

## Decision

Only `FileNotFoundError` for the interface inventory or driver link means that
the corresponding object is confirmed absent. Other inventory, driver, bridge,
and carrier read failures remain explicit probe errors. Bring-up and DHCP
command failures stop the flow with a command error; failed or malformed
address observations remain probe errors. A missing/unrunnable DHCP command or
an unexplained client failure is a command error; a client diagnostic that
specifically reports no lease/offer remains a DHCP outcome. Confirmed carrier
absence and a successful DHCP attempt without an address remain distinct. The
Textual Tether action displays the structured result in both notification and
console before refreshing the network table.

## Evidence and scope

The focused tether truthfulness, configuration apply, network, web, and TUI
source-contract suite passed 162 tests using injected subprocess and sysfs
failures. No USB tether, live DHCP server, or host network configuration was
exercised.

## Remaining work

REAL-007 still requires real USB phone/hotspot DHCP verification and route
preservation/rollback testing. This record does not claim live tether support
was verified.
