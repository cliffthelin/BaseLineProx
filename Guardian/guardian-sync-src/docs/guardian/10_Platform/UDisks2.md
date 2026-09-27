---
title: "UDisks2"
kind: "platform-provider"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - platform
  - provider
---
# UDisks2

## Guardian role

Authoritative user-facing block/drive provider. Guardian must understand Drive/Block/Filesystem topology, CanPowerOff and sibling impact.

## Related wiki pages

- [udisks-drive](../90_Sources/wiki/udisks-drive.md)
- [IO Guardian](../40_Modules/IO_Guardian.md)

## Contract rule

Before implementing a write path, follow this page to its authoritative source snapshot and confirm the installed Ubuntu provider still exposes the expected contract.
