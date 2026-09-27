---
title: "Logging Capacity & Evidence"
kind: "control-plane-feature"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - control-plane
  - architecture
---
# Logging Capacity & Evidence

## Purpose

Operational logs use journald; transaction/incident state is structured; Log Lens collapses presentation without deleting authoritative evidence.

## Pointers

- [Journald and Logrotate](../10_Platform/Journald_and_Logrotate.md)
- [Logs and Incidents](../40_Modules/Logs_and_Incidents.md)
- [Flight Recorder](Flight_Recorder.md)

## TDD anchor

See [Phase 0/1 TDD Contract](../30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md). Tests and ADRs that change this feature should link here and to the external provider source that justifies the behavior.
