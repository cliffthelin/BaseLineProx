---
title: "pkttyagent textual authorization helper"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - polkit
source_url: "https://manpages.ubuntu.com/manpages/resolute/man1/pkttyagent.1.html"
source_checked: "2026-08-30"
---
# pkttyagent textual authorization helper

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Text authentication-agent reference used to plan Guardian TUI/VT/recovery authorization.

## Contract-relevant points

- pkttyagent can bind to a process or system-bus name.
- It provides a textual authentication path when a graphical agent is unavailable.
- Guardian recovery/VT behavior must be tested rather than assuming a desktop polkit agent exists.

## Refresh metadata

- Canonical URL: https://manpages.ubuntu.com/manpages/resolute/man1/pkttyagent.1.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [Privilege and Authorization](../../20_Control_Plane/Privilege_and_Authorization.md)
- [Recovery Plane](../../20_Control_Plane/Recovery_Plane.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
