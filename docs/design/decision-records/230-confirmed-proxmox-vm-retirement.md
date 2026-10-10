# DR230: Confirmed Proxmox VM retirement validates and removes owned data

**Status:** Implemented; live Proxmox verification remains open  
**Date:** 2026-10-09

## Context

The Proxmox VM page offered a Delete action, but `delete_vm` refused every VM
with a retained home disk. The UI also asked only whether to delete a disk,
without saying that retained user data would be lost. Older tests asserted the
refusal and used command fakes for lifecycle outcomes; neither demonstrated a
working native retirement.

## Decision

Confirmed retirement now checks the live cluster inventory, stopped state,
configured storage identities, VM name and lock, and every attached disk
against the durable Baseline VM record. It refuses foreign VMIDs, unexpected
disk attachments, changed storage paths, symbolic-link volumes, or unrecognized
files. Before calling `qm destroy --purge`, it persists the validated volume
IDs and exact paths. It then verifies the VM disappeared, removes only any
remaining recorded volumes through Proxmox storage commands, and cleans the
known VM metadata and generated seed/installer files. A retry can continue the
same recorded retirement after a service interruption. The delete prompt now
states that the OS and retained home data are permanently deleted.

The pure ownership/parser contract tests run without FakeRunner/FakeProc or
Proxmox. They do not prove that native Proxmox commands accept the operation or
that the physical storage is deleted correctly.

## Evidence and scope

Seven pure contract tests passed, covering managed root/home ownership, rejection
of altered or extra disks, VMID inventory ambiguity/type, and malformed `qm`
configuration. AST parsing and `git diff --check` passed. This development
host has no `qm`, `pvesh`, or `pvesm`, so no live Proxmox VM was listed,
stopped, or deleted, and no physical data was changed.

## Remaining work

Run a destructive-retirement acceptance on a disposable native Proxmox VM,
including an attached retained home disk, and verify the VMID, OS disk, home
disk, generated seed files, and associated references are gone. Until then,
this is implemented but not verified against Proxmox or physical hardware.
Continue queue item 75 and preserve DR117 as historical evidence of the prior
refusal.
