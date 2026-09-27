---
title: "Provider Arbitrator"
kind: "control-plane-feature"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - control-plane
  - architecture
---
# Provider Arbitrator

## Purpose

Determines which provider owns a mutable capability and whether Guardian may write it. Enforces the single-writer rule.

## Pointers

- [Capability Registry](Capability_Registry.md)
- [Transaction Engine](Transaction_Engine.md)
- [Power Profiles](../10_Platform/Power_Profiles.md)

## TDD anchor

See [Phase 0/1 TDD Contract](../30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md). Tests and ADRs that change this feature should link here and to the external provider source that justifies the behavior.
