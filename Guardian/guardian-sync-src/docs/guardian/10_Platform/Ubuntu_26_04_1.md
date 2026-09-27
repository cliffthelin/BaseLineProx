---
title: "Ubuntu 26.04.1 Baseline"
kind: "platform-provider"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - platform
  - provider
---
# Ubuntu 26.04.1 Baseline

## Guardian role

The development and VM-test baseline. Provider code must capability-detect and tolerate patch updates rather than hardcoding the research-day package versions.

## Related wiki pages

- [systemd](systemd.md)
- [D-Bus](D-Bus.md)
- [Polkit](Polkit.md)
- [UDisks2](UDisks2.md)
- [PSI](PSI.md)
- [StatusNotifierItem](StatusNotifierItem.md)

## Contract rule

Before implementing a write path, follow this page to its authoritative source snapshot and confirm the installed Ubuntu provider still exposes the expected contract.
