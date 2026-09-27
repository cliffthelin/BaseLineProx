---
title: "D-Bus"
kind: "platform-provider"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - platform
  - provider
---
# D-Bus

## Guardian role

Guardian's system IPC boundary. Package defaults live in vendor locations; semantic authorization belongs in Guardian/polkit.

## Related wiki pages

- [ubuntu-dbus-daemon-resolute](../90_Sources/wiki/ubuntu-dbus-daemon-resolute.md)
- [D-Bus API Contract](../20_Control_Plane/D-Bus_API_Contract.md)

## Contract rule

Before implementing a write path, follow this page to its authoritative source snapshot and confirm the installed Ubuntu provider still exposes the expected contract.
