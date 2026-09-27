---
title: "Ubuntu 26.04 systemd.exec(5)"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - systemd
source_url: "https://manpages.ubuntu.com/manpages/resolute/man5/systemd.exec.5.html"
source_checked: "2026-08-30"
---
# Ubuntu 26.04 systemd.exec(5)

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Execution-environment and service-hardening reference. It defines the sandbox controls used by the Guardian privilege-topology gate.

## Contract-relevant points

- Relevant controls include NoNewPrivileges, ProtectSystem, ProtectHome, CapabilityBoundingSet and explicit writable paths.
- Guardian must record why any relevant hardening control cannot be enabled.

## Refresh metadata

- Canonical URL: https://manpages.ubuntu.com/manpages/resolute/man5/systemd.exec.5.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [Privilege and Authorization](../../20_Control_Plane/Privilege_and_Authorization.md)
- [GUARDIAN PHASE 0 1 TDD CONTRACT](../../30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
