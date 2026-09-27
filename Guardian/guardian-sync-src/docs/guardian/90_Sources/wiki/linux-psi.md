---
title: "Linux kernel PSI — Pressure Stall Information"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - linux-kernel
source_url: "https://cdn.kernel.org/doc/html/latest/accounting/psi.html"
source_checked: "2026-08-30"
---
# Linux kernel PSI — Pressure Stall Information

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Kernel reference for CPU, memory and I/O pressure metrics and event-driven pressure triggers.

## Contract-relevant points

- System pressure is exported under /proc/pressure/cpu, memory and io.
- PSI distinguishes partial stalls ('some') from full workload stalls where applicable.
- Threshold triggers can be waited on with poll/select/epoll, enabling event-driven escalation rather than high-frequency polling.

## Refresh metadata

- Canonical URL: https://cdn.kernel.org/doc/html/latest/accounting/psi.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [PSI](../../10_Platform/PSI.md)
- [Diagnostic Budget](../../20_Control_Plane/Diagnostic_Budget.md)
- [IO Guardian](../../40_Modules/IO_Guardian.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
