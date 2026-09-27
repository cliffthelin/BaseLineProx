---
title: "Power Profiles daemon D-Bus API"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - power-profiles-daemon
source_url: "https://freedesktop-team.pages.debian.net/power-profiles-daemon/ref-dbus.html"
source_checked: "2026-08-30"
---
# Power Profiles daemon D-Bus API

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

D-Bus reference for platform power profiles, profile ownership/driver information, holds and degraded-performance state.

## Contract-relevant points

- Guardian should surface the active provider/driver and current profile holds.
- Profile changes should go through the authoritative provider instead of writing lower-level settings behind it.

## Refresh metadata

- Canonical URL: https://freedesktop-team.pages.debian.net/power-profiles-daemon/ref-dbus.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [Power Profiles](../../10_Platform/Power_Profiles.md)
- [Provider Arbitrator](../../20_Control_Plane/Provider_Arbitrator.md)
- [Thermal and Power](../../40_Modules/Thermal_and_Power.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
