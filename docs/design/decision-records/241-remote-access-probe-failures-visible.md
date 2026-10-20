# DR241 — Remote-access probe failures stay visible

**Status:** Implemented; pure renderer test plus read-only live collection  
**Date:** 2026-10-09

## Context

Remote Access discarded command failures. In particular, when `ss -ltn`
failed or returned malformed successful output, the page rendered an empty
listener list as “none found,” confusing a failed observation with a
successful observation of no listeners.

## Decision

Retain a human-readable error for each failed remote-access command. Report
whether the listener probe succeeded, and render its state as unavailable when
it did not. Validate the `ss` table header and listener rows before treating
the inventory as complete. `systemctl is-active` exit code 3 with status text
is accepted as a valid inactive-state observation.

## Evidence and scope

A pure renderer regression test failed before the change and passes afterward;
four additional parser cases reject malformed data and accept a valid empty
table.
A read-only collection through the production `RealRunner` enumerated the
current host's listening sockets and surfaced the `sshd -T` error that no
host keys were available. No FakeRunner/FakeProc was used, and no setting or
service was changed.

## Remaining work

This is a read-only observation on the current development host. It does not
establish firewall enforcement, internet reachability, or behavior on a
Proxmox target drive. The older fake-backed tests were updated for the new
error fields but were not run.
