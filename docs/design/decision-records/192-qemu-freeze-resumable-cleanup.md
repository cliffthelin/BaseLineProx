# DR192: Direct QEMU base conversion reports and resumes cleanup failures

Date: 2026-10-09  
Status: accepted

## Context

`VmHost.freeze_as_base()` moved a standalone VM disk into the base-image
directory, changed it read-only, and called `shutil.rmtree(...,
ignore_errors=True)` on the VM record directory. A filesystem failure could
leave a broken VM entry pointing to a disk that had moved while the operation
returned success. Simply making `rmtree` strict would expose the failure, but
a partial removal of `vm.json` would make the operation impossible to resume
through the VM API.

## Decision

Persist a freeze-operation record in the VM store before moving the disk. The
record binds the VM name to the requested base name. On retry, validate that
record, reconcile whether the source disk or the target base exists, refuse
ambiguous states, enforce read-only mode, and strictly remove any remaining VM
directory. The operation record remains until all cleanup succeeds, including
when a failed cleanup already removed `vm.json`.

## Evidence

A regression test injects cleanup failure after `vm.json` has been removed. The
first call reports the `OSError`; the second call resumes from the durable
operation record and removes the remaining VM directory. All 36
`tests/unit/test_vm_host.py` tests pass with the synthetic `FakeHost` command
runner and temporary local files. No live QEMU process, Proxmox host, or
physical drive was modified.

## Remaining work

This is synthetic local-filesystem verification of direct QEMU VM lifecycle
behavior. It does not establish deletion or base conversion on a live host.
Retained-data retirement remains refused in the Proxmox lifecycle path; see
queue72 and REAL-013.
