---
title: "zbus Rust D-Bus library"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - zbus
source_url: "https://docs.rs/zbus/latest/zbus/index.html"
source_checked: "2026-08-30"
---
# zbus Rust D-Bus library

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Rust D-Bus client/server library considered for Guardian's typed D-Bus API and provider proxies.

## Contract-relevant points

- zbus provides connection, messages, typed proxy/interface macros, signals and property support.
- Guardian's public and stable provider interfaces should prefer typed bindings.

## Refresh metadata

- Canonical URL: https://docs.rs/zbus/latest/zbus/index.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [zbus](../../10_Platform/zbus.md)
- [D-Bus API Contract](../../20_Control_Plane/D-Bus_API_Contract.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
