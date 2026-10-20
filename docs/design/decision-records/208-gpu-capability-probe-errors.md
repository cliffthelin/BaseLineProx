# DR208: GPU capability probe errors are not missing capability

Date: 2026-10-09  
Status: accepted

## Context

When a GPU's `sriov_totalvfs` file existed but `cat` failed, `_sriov_evidence()`
parsed the empty output as zero and reported SR-IOV unavailable. Malformed values
were also coerced to zero. `_mdev_evidence()` reported an existing but empty
`mdev_supported_types` directory as active support. The real runner's directory
listing also converted a missing or unreadable path into an empty list.

## Decision

SR-IOV read failures and malformed/negative values now raise
`GpuInventoryError`; only the observed integer zero means no VFs. An existing
mdev directory is active only when it contains type entries. Known hardware
capability remains available but is explicitly labeled inactive when no types
are exposed. `RealRunner` now distinguishes a confirmed missing path from
directory enumeration and path-resolution errors.

## Evidence

The SR-IOV command-error, malformed-value, and empty-mdev regressions failed
before implementation. All 41 GPU-admin tests pass, and the combined GPU,
hardware-inventory, and Quadlet suite passes 127 tests using scripted commands
and sysfs observations. No physical GPU capability state was read in this run.

## Remaining work

REAL-006 still requires live hardware inventory/readback coverage and audit of
other capability probes. No earlier decision record is superseded.
