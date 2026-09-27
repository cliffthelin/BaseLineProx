---
title: "Control Plane Architecture"
kind: "control-plane-feature"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - control-plane
  - architecture
---
# Control Plane Architecture

## Purpose

Shared privileged/system daemon plus thin GUI/TUI/CLI/indicator clients. All later modules enter through common provider, transaction, authorization and incident contracts.

## Pointers

- [Guardian Control Plane](../00_Project/Guardian_Control_Plane.md)
- [Capability Registry](Capability_Registry.md)
- [Provider Arbitrator](Provider_Arbitrator.md)
- [Transaction Engine](Transaction_Engine.md)

## TDD anchor

See [Phase 0/1 TDD Contract](../30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md). Tests and ADRs that change this feature should link here and to the external provider source that justifies the behavior.
