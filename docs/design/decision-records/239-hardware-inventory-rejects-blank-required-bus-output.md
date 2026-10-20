# DR239 — Hardware inventory rejects blank required-bus output

**Status:** Implemented and contract tested; no real hardware inventory run  
**Date:** 2026-10-09

## Context

The PCI, whole-disk, and network collectors converted a successful command
with blank output into an empty device list. Such an output can indicate a
broken or unusable probe and should not be presented as confirmed absence.
USB can legitimately have no visible peripherals, so its successful empty
output has a different meaning.

## Decision

Require nonblank output from PCI, block-device, and network probes before
parsing. A blank output raises `InventoryError`, which `collect_all` records as
an explicit failed bus observation. Keep empty USB output valid, preserving the
meaning of no visible peripherals after a successful probe.

## Evidence and scope

Four pure contract tests passed: blank PCI/block/network output raises, while
blank USB output remains allowed. The regression tests were written before the
implementation and failed because the shared validation function did not
exist. No FakeRunner/FakeProc or live hardware command was used.

## Remaining work

This validates output presence, not the correctness or completeness of a real
host's `lspci`, `lsblk`, `ip`, or `lsusb` data. No live hardware inventory was
performed.
