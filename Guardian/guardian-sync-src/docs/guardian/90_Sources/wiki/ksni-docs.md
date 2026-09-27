---
title: "ksni Rust StatusNotifierItem library"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - ksni
source_url: "https://docs.rs/ksni/latest/ksni/"
source_checked: "2026-08-30"
---
# ksni Rust StatusNotifierItem library

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Rust StatusNotifierItem implementation and current leading candidate for Guardian's cross-desktop indicator compatibility spike.

## Contract-relevant points

- ksni implements the KDE/freedesktop StatusNotifierItem specification.
- It supports async and blocking APIs and exposes explicit offline/error state.
- Selection remains test-gated on GNOME 50/Wayland and Xfce 4.20.

## Refresh metadata

- Canonical URL: https://docs.rs/ksni/latest/ksni/
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [StatusNotifierItem](../../10_Platform/StatusNotifierItem.md)
- [Client Surfaces](../../20_Control_Plane/Client_Surfaces.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
