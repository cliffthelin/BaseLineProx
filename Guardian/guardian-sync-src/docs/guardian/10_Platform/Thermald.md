---
title: "thermald"
kind: "platform-provider"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - platform
  - provider
---
# thermald

## Guardian role

Candidate authoritative CPU/platform thermal-policy provider. Phase 1 discovers ownership; raw fan/control work is deferred.

## Related wiki pages

- [Thermal and Power](../40_Modules/Thermal_and_Power.md)
- [Provider Arbitrator](../20_Control_Plane/Provider_Arbitrator.md)

## Contract rule

Before implementing a write path, follow this page to its authoritative source snapshot and confirm the installed Ubuntu provider still exposes the expected contract.
