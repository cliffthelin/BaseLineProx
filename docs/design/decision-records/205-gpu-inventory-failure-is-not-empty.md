# DR205: GPU inventory failure is not an empty device list

Date: 2026-10-09  
Status: accepted

## Context

`gpu_admin.detect_gpus()` returned `[]` whenever `lspci -Dmmnnk` failed. That
made a missing binary, permission error, or timed-out probe indistinguishable
from a successful scan that found no GPU-class devices. Callers could then
persist or display a false empty inventory.

## Decision

`detect_gpus()` now raises `GpuInventoryError` with the command diagnostic when
the PCI inventory command fails. A successful scan with no GPU-class rows
continues to return an empty list. `sync_detected_gpus()` naturally propagates
the failure before writing any inventory entries.

## Evidence

The regression asserting an inventory error failed before the change because
the exception type did not exist. All 37 `test_gpu_admin.py` tests pass using
scripted command and sysfs responses. No real GPU inventory was read in this
verification.

## Remaining work

REAL-006 still tracks live and malformed-output coverage for hardware
collectors. No physical hardware behavior is claimed and no earlier decision
record is superseded.
