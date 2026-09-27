---
title: "GUI / TUI / CLI / Indicator"
kind: "control-plane-feature"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - control-plane
  - architecture
---
# GUI / TUI / CLI / Indicator

## Purpose

All clients are thin. They render daemon state and request typed operations; they do not directly modify system configuration.

## Pointers

- [StatusNotifierItem](../10_Platform/StatusNotifierItem.md)
- [Privilege and Authorization](Privilege_and_Authorization.md)
- [Recovery Plane](Recovery_Plane.md)

## TDD anchor

See [Phase 0/1 TDD Contract](../30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md). Tests and ADRs that change this feature should link here and to the external provider source that justifies the behavior.
