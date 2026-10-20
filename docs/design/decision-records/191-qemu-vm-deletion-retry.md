# DR191: Direct QEMU VM deletion resumes after partial cleanup

Date: 2026-10-09  
Status: accepted

## Context

`VmHost.delete_vm()` stores standalone root disks separately from VM metadata.
It unlinked the root disk before removing the VM metadata directory. If
directory cleanup failed after the disk was removed, a retry found the still
present VM record and raised `FileNotFoundError` while trying to unlink the
already-removed disk. The initial failure was visible, but cleanup could not be
resumed through the same operation.

## Decision

Before deleting a standalone root disk, persist `deleting: true` in the VM
record. A retry may treat the root disk as already removed only when that
durable marker exists. Directory removal remains strict, so cleanup failures
remain visible and the VM record remains available for retry. VM names and disk
locations continue to use the existing validated `VmHost` path rules.

## Evidence

A regression test first failed because the retry attempted to unlink the root
disk again. After the change, it injects a directory-cleanup interruption after
disk removal and verifies a second delete completes. All 35
`tests/unit/test_vm_host.py` tests passed using the synthetic `FakeHost` command
runner and temporary local files. No real QEMU process, Proxmox host, or
physical drive was modified.

## Remaining work

This covers retry of local cleanup for direct QEMU VMs. It does not implement
retirement of retained VM data, which remains refused by the Proxmox lifecycle
path, or establish live-host deletion behavior. Continue under queue72 VM
lifecycle and the existing runtime verification tasks.
