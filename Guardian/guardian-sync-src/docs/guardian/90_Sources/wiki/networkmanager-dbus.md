---
title: "NetworkManager D-Bus Manager API"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - networkmanager
source_url: "https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/gdbus-org.freedesktop.NetworkManager.html"
source_checked: "2026-08-30"
---
# NetworkManager D-Bus Manager API

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

NetworkManager's checkpoint API is Guardian's primary native precedent for transactional change and automatic rollback.

## Contract-relevant points

- CheckpointCreate can snapshot selected devices or all devices.
- A non-zero rollback timeout causes automatic rollback if the checkpoint is not committed/destroyed.
- CheckpointRollback returns structured per-device results.
- Guardian generalizes this lifecycle but must report when a provider lacks native rollback.

## Refresh metadata

- Canonical URL: https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/gdbus-org.freedesktop.NetworkManager.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [NetworkManager](../../10_Platform/NetworkManager.md)
- [Transaction Engine](../../20_Control_Plane/Transaction_Engine.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
