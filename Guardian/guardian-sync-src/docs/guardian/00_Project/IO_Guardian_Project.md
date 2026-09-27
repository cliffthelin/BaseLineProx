---
title: "I/O Guardian"
kind: "project-module"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - guardian
  - io
  - storage
  - project
---
# I/O Guardian

I/O Guardian is the renamed successor to the original USB-freeze protection utility. It is a Guardian module and also a coherent project boundary.

## Mission

Correlate storage symptoms across:

**physical port → device → block device → partition → filesystem → mount → processes → latency → kernel errors → PSI**

## Main control-plane dependencies

- [Capability Registry](../20_Control_Plane/Capability_Registry.md)
- [Provider Arbitrator](../20_Control_Plane/Provider_Arbitrator.md)
- [Transaction Engine](../20_Control_Plane/Transaction_Engine.md)
- [Risk & Recovery Ladder](../20_Control_Plane/Risk_and_Recovery_Ladder.md)
- [Diagnostic Budget](../20_Control_Plane/Diagnostic_Budget.md)

## Platform dependencies

- [UDisks2](../10_Platform/UDisks2.md)
- [udev & Device Identity](../10_Platform/udev_and_Device_Identity.md)
- [PSI](../10_Platform/PSI.md)
- [systemd](../10_Platform/systemd.md)

## Source anchors

- [UDisks Drive API](../90_Sources/wiki/udisks-drive.md)
- [Linux PSI](../90_Sources/wiki/linux-psi.md)

## TDD

Phase 0/1 provides shared infrastructure and read-only UDisks/PSI groundwork. Destructive I/O recovery remains deferred until the later I/O Guardian phase.
