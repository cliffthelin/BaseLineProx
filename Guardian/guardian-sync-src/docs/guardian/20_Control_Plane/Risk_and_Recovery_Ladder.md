---
title: "Risk & Recovery Ladder"
kind: "control-plane-feature"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - control-plane
  - architecture
---
# Risk & Recovery Ladder

## Purpose

Actions are classified OBSERVE/LOW/MODERATE/HIGH/VERY_HIGH; highest tiers are walled into Recovery/Advanced and never automated by default.

## Pointers

- [Transaction Engine](Transaction_Engine.md)
- [IO Guardian](../40_Modules/IO_Guardian.md)
- [Recovery Plane](Recovery_Plane.md)

## TDD anchor

See [Phase 0/1 TDD Contract](../30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md). Tests and ADRs that change this feature should link here and to the external provider source that justifies the behavior.
