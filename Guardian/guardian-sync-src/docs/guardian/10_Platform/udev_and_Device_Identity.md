---
title: "udev & Device Identity"
kind: "platform-provider"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - platform
  - provider
---
# udev & Device Identity

## Guardian role

Hardware discovery and hotplug layer. Persistent identity must not be conflated with volatile /dev names.

## Related wiki pages

- [UDisks2](UDisks2.md)
- [Capability Registry](../20_Control_Plane/Capability_Registry.md)

## Contract rule

Before implementing a write path, follow this page to its authoritative source snapshot and confirm the installed Ubuntu provider still exposes the expected contract.
