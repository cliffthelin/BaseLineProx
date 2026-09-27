---
title: "systemd-logind and inhibitor locks"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - systemd-logind
source_url: "https://wiki.freedesktop.org/www/Software/systemd/logind/"
source_checked: "2026-08-30"
---
# systemd-logind and inhibitor locks

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Reference for login/session state and inhibitor locks used by the read-only Guardian 'System Blockers' provider.

## Contract-relevant points

- ListInhibitors reports current inhibitors including what, who, why, mode, UID and PID.
- Guardian can explain why sleep/shutdown actions are blocked without directly changing system state.

## Refresh metadata

- Canonical URL: https://wiki.freedesktop.org/www/Software/systemd/logind/
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [systemd](../../10_Platform/systemd.md)
- [System Blockers](../../40_Modules/System_Blockers.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
