# DR229: VM inventory requires its configured store

**Status:** Accepted  
**Date:** 2026-10-09

## Context

The local VM backend and Proxmox adapter returned empty VM/base inventories when
their configured store directories were absent. For stores under `/mnt`, an
unmounted volume therefore looked like a successful empty catalogue. The
installer cache was also accepted as an inventory root even though it must not
hold mutable VM state.

## Decision

VM and base inventory must validate the configured VM store before checking
for directories or records. The Proxmox inventory also validates the separate
persistence store that owns its VM records. Missing required mounts and
INSTALLER_CACHE paths surface as `VmError`; only a valid, mounted store with
no records is an empty inventory.

## Evidence and scope

Four integration checks exercised the production local/Proxmox inventory
methods: reserved INSTALLER_CACHE paths and deliberately unmounted `/mnt`
paths now raise configured-store diagnostics instead of returning empty lists.
Python AST parsing and `git diff --check` passed. No FakeRunner, FakeProc,
generated fixture, Proxmox command, VM, or physical drive was used.

## Remaining work

This prevents false-empty VM inventories for invalid/unmounted stores. It does
not verify a live Proxmox inventory or prove physical mount persistence and VM
lifecycle; those remain open under queue items 7, 72, and 75.
