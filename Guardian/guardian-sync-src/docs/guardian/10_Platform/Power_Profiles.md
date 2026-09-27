---
title: "power-profiles-daemon"
kind: "platform-provider"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - platform
  - provider
---
# power-profiles-daemon

## Guardian role

Authoritative platform power-profile provider when present; its driver/holds/degraded state belongs in ownership arbitration.

## Related wiki pages

- [power-profiles-dbus](../90_Sources/wiki/power-profiles-dbus.md)
- [Provider Arbitrator](../20_Control_Plane/Provider_Arbitrator.md)

## Contract rule

Before implementing a write path, follow this page to its authoritative source snapshot and confirm the installed Ubuntu provider still exposes the expected contract.
