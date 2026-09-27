---
title: "UDisks2 Drive D-Bus API"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - udisks2
source_url: "https://storaged.org/doc/udisks2-api/latest/gdbus-org.freedesktop.UDisks2.Drive.html"
source_checked: "2026-08-30"
---
# UDisks2 Drive D-Bus API

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Authoritative Drive interface reference for topology and safe drive power-off semantics.

## Contract-relevant points

- PowerOff() checks that the drive is not in use and asks for buffers/caches to be committed.
- For USB, power-off deconfigures the USB device and disables the upstream hub port.
- CanPowerOff must be true.
- SiblingId must be considered because a physical enclosure may expose multiple drives.
- The documentation says PowerOff should be called only in response to user action.

## Refresh metadata

- Canonical URL: https://storaged.org/doc/udisks2-api/latest/gdbus-org.freedesktop.UDisks2.Drive.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [UDisks2](../../10_Platform/UDisks2.md)
- [IO Guardian](../../40_Modules/IO_Guardian.md)
- [Risk and Recovery Ladder](../../20_Control_Plane/Risk_and_Recovery_Ladder.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
