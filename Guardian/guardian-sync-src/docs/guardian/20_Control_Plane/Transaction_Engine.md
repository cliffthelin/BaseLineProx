---
title: "Transaction Engine"
kind: "control-plane-feature"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - control-plane
  - architecture
---
# Transaction Engine

## Purpose

Every write is Snapshot → Validate → Authorize → Apply → Observe → Confirm → Commit or Rollback. Native provider checkpoints are preferred.

## Pointers

- [networkmanager-dbus](../90_Sources/wiki/networkmanager-dbus.md)
- [Risk and Recovery Ladder](Risk_and_Recovery_Ladder.md)
- [Event and Incident Model](Event_and_Incident_Model.md)

## TDD anchor

See [Phase 0/1 TDD Contract](../30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md). Tests and ADRs that change this feature should link here and to the external provider source that justifies the behavior.
