---
title: "Flight Recorder"
kind: "control-plane-feature"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - control-plane
  - architecture
---
# Flight Recorder

## Purpose

Bounded memory-first recorder with optional bounded local spill. It must survive persistence failure and never depend on monitored removable media.

## Pointers

- [Diagnostic Budget](Diagnostic_Budget.md)
- [Event and Incident Model](Event_and_Incident_Model.md)

## TDD anchor

See [Phase 0/1 TDD Contract](../30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md). Tests and ADRs that change this feature should link here and to the external provider source that justifies the behavior.
