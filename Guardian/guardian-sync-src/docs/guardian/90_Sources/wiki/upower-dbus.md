---
title: "UPower D-Bus API Reference"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - upower
source_url: "https://upower.freedesktop.org/docs/ref-dbus.html"
source_checked: "2026-08-30"
---
# UPower D-Bus API Reference

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

D-Bus API index for power-device enumeration and per-device state.

## Contract-relevant points

- Guardian uses the D-Bus service instead of scraping the upower CLI.
- Phase 1 use is read-only: display device, battery/UPS/power-device telemetry where available.

## Refresh metadata

- Canonical URL: https://upower.freedesktop.org/docs/ref-dbus.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [UPower](../../10_Platform/UPower.md)
- [Thermal and Power](../../40_Modules/Thermal_and_Power.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
