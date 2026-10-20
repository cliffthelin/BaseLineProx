# DR219: QEMU VM inventory errors stay visible

**Status:** Accepted  
**Date:** 2026-10-09

## Context

The local QEMU host caught `VmError` while listing VMs and silently skipped the
affected record. The VM disappeared from the page, and operations that inspect
base-image users could make decisions without seeing that VM. `_spec()` also
reported malformed JSON as “no such VM,” which confused corrupt state with a
confirmed absence. The `/vms/status` and `/vms` routes did not convert these
errors into an operator-visible response.

## Decision

`_spec()` distinguishes a missing record, unreadable record, and malformed
record. `list_vms()` raises a contextual `VmError` when any managed VM cannot
be inspected; it does not return a partial inventory as complete. The status
route returns HTTP 503 with an unknown state. The VM page displays an explicit
inventory-unavailable message and suppresses the misleading “No VMs yet” text.

## Evidence and scope

The focused VM host, VM web, and VM page suites passed 68 tests. A malformed
managed record was injected into disposable local files; the host used a
synthetic QEMU runner and local HTTP fixture. No real QEMU process, Proxmox
host, or physical drive was accessed.

## Remaining work

This change fixes one false-empty inventory path. Live QEMU/Proxmox VM inventory
and the remaining REAL-013 lifecycle verification are still open.
