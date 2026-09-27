---
title: "Guardian Wiki Index"
kind: "index"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - guardian
  - wiki
  - index
---
# Guardian Wiki

Local, self-contained Markdown navigation layer for Guardian and I/O Guardian development.

## Projects

- [Guardian Control Plane](00_Project/Guardian_Control_Plane.md)
- [I/O Guardian](00_Project/IO_Guardian_Project.md)
- [Guardian master specification](00_Project/GUARDIAN_MASTER_SPEC.md)
- [Previous master-spec snapshot](00_Project/GUARDIAN_MASTER_SPEC_PREVIOUS.md)

## Control plane / plane features

- [Control Plane Feature Index](20_Control_Plane/INDEX.md)
- [Architecture](20_Control_Plane/Architecture.md)
- [Capability Registry](20_Control_Plane/Capability_Registry.md)
- [Provider Arbitrator](20_Control_Plane/Provider_Arbitrator.md)
- [Transaction Engine](20_Control_Plane/Transaction_Engine.md)
- [Privilege & Authorization](20_Control_Plane/Privilege_and_Authorization.md)
- [Diagnostic Budget](20_Control_Plane/Diagnostic_Budget.md)
- [Event & Incident Model](20_Control_Plane/Event_and_Incident_Model.md)
- [Flight Recorder](20_Control_Plane/Flight_Recorder.md)
- [Recovery Plane](20_Control_Plane/Recovery_Plane.md)
- [Source Contract Drift](20_Control_Plane/Source_Contract_Drift.md)

## Platform / provider features

- [Platform Index](10_Platform/INDEX.md)

## Modules

- [Module Index](40_Modules/INDEX.md)

## TDD / build navigation

- [Phase 0 contract research](30_TDD/GUARDIAN_PHASE_0_CONTRACT_RESEARCH.md)
- [Phase 0/1 TDD contract](30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md)
- [TDD Gate Index](30_TDD/TDD_Gate_Index.md)
- [Self Lookup Map](LOOKUP_MAP.md)

## External reference layer

- [Source Registry](90_Sources/SOURCE_REGISTRY.md)
- `90_Sources/wiki/` — local Guardian-oriented external-source snapshots
- `90_Sources/raw/` — canonical URL pointer files for scripted refreshing

## Maintenance

- [Source Refresh Workflow](50_Operations/Source_Refresh_Workflow.md)
- [Wiki Update Workflow](50_Operations/Wiki_Update_Workflow.md)

## Navigation principle

A TDD or coding question should normally follow:

**lookup term → Guardian feature/module page → platform/provider page → local source snapshot → canonical URL → TDD gate/test/ADR**

This makes the wiki a pointer system rather than another independent source of truth.
