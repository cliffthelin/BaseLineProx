---
title: "Privilege & Authorization"
kind: "control-plane-feature"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - control-plane
  - architecture
---
# Privilege & Authorization

## Purpose

Least-privilege daemon topology is a Phase 0 gate. Clients never run as root; writes are polkit-authorized using actual bus caller identity.

## Pointers

- [Polkit](../10_Platform/Polkit.md)
- [systemd](../10_Platform/systemd.md)
- [Transaction Engine](Transaction_Engine.md)

## TDD anchor

See [Phase 0/1 TDD Contract](../30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md). Tests and ADRs that change this feature should link here and to the external provider source that justifies the behavior.
