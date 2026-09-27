---
title: "Diagnostic Budget Manager"
kind: "control-plane-feature"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - control-plane
  - architecture
---
# Diagnostic Budget Manager

## Purpose

Each diagnostic declares resource cost; Guardian can veto escalation that would worsen the resource class already in distress.

## Pointers

- [PSI](../10_Platform/PSI.md)
- [Flight Recorder](Flight_Recorder.md)
- [Event and Incident Model](Event_and_Incident_Model.md)

## TDD anchor

See [Phase 0/1 TDD Contract](../30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md). Tests and ADRs that change this feature should link here and to the external provider source that justifies the behavior.
