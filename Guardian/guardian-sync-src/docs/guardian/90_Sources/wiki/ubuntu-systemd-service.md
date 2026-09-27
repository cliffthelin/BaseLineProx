---
title: "Ubuntu 26.04 systemd.service(5)"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - systemd
source_url: "https://manpages.ubuntu.com/manpages/resolute/man5/systemd.service.5.html"
source_checked: "2026-08-30"
---
# Ubuntu 26.04 systemd.service(5)

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Service-unit reference used for Guardian daemon lifecycle and Type=dbus/BusName integration.

## Contract-relevant points

- Type=dbus services require BusName.
- systemd service semantics define startup, reload, stop, and failure behavior the daemon contract must obey.

## Refresh metadata

- Canonical URL: https://manpages.ubuntu.com/manpages/resolute/man5/systemd.service.5.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [systemd](../../10_Platform/systemd.md)
- [D-Bus API Contract](../../20_Control_Plane/D-Bus_API_Contract.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
