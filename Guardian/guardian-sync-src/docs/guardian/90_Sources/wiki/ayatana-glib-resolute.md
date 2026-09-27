---
title: "Ubuntu 26.04 libayatana-appindicator-glib2 package"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - ubuntu---ayatana
source_url: "https://packages.ubuntu.com/en/resolute/libayatana-appindicator-glib2"
source_checked: "2026-08-30"
---
# Ubuntu 26.04 libayatana-appindicator-glib2 package

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Ubuntu package record for the GLib-only Ayatana AppIndicator implementation.

## Contract-relevant points

- Resolute packages libayatana-appindicator-glib2 2.0.1-1build1.
- Its availability alone is not sufficient to select it; actual GNOME/Xfce menu-host compatibility is a Phase 0 test gate.

## Refresh metadata

- Canonical URL: https://packages.ubuntu.com/en/resolute/libayatana-appindicator-glib2
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [StatusNotifierItem](../../10_Platform/StatusNotifierItem.md)
- [Client Surfaces](../../20_Control_Plane/Client_Surfaces.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
