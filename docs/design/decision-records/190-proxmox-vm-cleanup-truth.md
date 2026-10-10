# DR190: Proxmox VM deletion reports local cleanup failures

Date: 2026-10-09  
Status: accepted

## Context

`ProxmoxVmHost.delete_vm()` destroyed the native VM, called
`shutil.rmtree(..., ignore_errors=True)`, and then unlinked the retained control
record. A filesystem error could therefore leave the local VM directory behind
while the operation returned as if cleanup had completed. The record also
continued to say `registered: true` after successful `qm destroy`, making a
cleanup retry attempt to destroy an already-removed Proxmox VM.

## Decision

After successful native destruction, persist `registered: false` before local
cleanup. Remove the managed VM directory with errors enabled and verify it is
gone before unlinking the record. If cleanup fails, surface the failure and
keep the record so a retry can resume local cleanup without repeating the
native destroy. A Proxmox destroy failure leaves the registration and files
intact. VMs with retained data remain refused by the existing safety gate.

## Evidence

Regression tests inject both Proxmox destroy failure and local directory
cleanup failure. They verify that failure state remains visible, the VM
directory and record are retained as appropriate, and retry does not issue a
second `qm destroy`. All 21 `tests/unit/test_proxmox_vm_host.py` tests passed
with a synthetic Proxmox command runner. No live VM was deleted or inspected.

## Remaining work

Safe retirement of VMs with retained data is still not implemented. This change
only removes false success from deletion of VMs that have no retained data.
