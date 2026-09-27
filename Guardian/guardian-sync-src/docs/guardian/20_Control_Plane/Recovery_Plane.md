---
title: "Recovery Plane"
kind: "control-plane-feature"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - control-plane
  - architecture
---
# Recovery Plane

## Purpose

Pre-login/VT path built around a system daemon and TUI, eventually a guardian-recovery.target. It must not depend on GNOME/Xfce.

## Pointers

- [Client Surfaces](Client_Surfaces.md)
- [Risk and Recovery Ladder](Risk_and_Recovery_Ladder.md)
- [Diagnostics and Recovery](../40_Modules/Diagnostics_and_Recovery.md)

## TDD anchor

See [Phase 0/1 TDD Contract](../30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md). Tests and ADRs that change this feature should link here and to the external provider source that justifies the behavior.
