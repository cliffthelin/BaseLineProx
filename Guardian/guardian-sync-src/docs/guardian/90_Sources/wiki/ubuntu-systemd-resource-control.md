---
title: "Ubuntu 26.04 systemd.resource-control(5)"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - systemd
source_url: "https://manpages.ubuntu.com/manpages/resolute/man5/systemd.resource-control.5.html"
source_checked: "2026-08-30"
---
# Ubuntu 26.04 systemd.resource-control(5)

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Resource-control reference for services/scopes/slices using cgroup v2. It underpins Guardian's throttle-before-kill and temporary mitigation model.

## Contract-relevant points

- Resolute's systemd page reports 259.5.
- systemd resource controls apply to services, scopes, slices, sockets, mounts, and swap units.
- Guardian should prefer transient runtime controls for incident mitigation instead of permanent unit edits.

## Refresh metadata

- Canonical URL: https://manpages.ubuntu.com/manpages/resolute/man5/systemd.resource-control.5.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [systemd](../../10_Platform/systemd.md)
- [Diagnostic Budget](../../20_Control_Plane/Diagnostic_Budget.md)
- [IO Guardian](../../40_Modules/IO_Guardian.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
