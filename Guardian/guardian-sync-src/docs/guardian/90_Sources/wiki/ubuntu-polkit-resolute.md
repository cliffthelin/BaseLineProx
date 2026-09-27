---
title: "Ubuntu 26.04 polkit(8)"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - polkit
source_url: "https://manpages.ubuntu.com/manpages/resolute/man8/polkit.8.html"
source_checked: "2026-08-30"
---
# Ubuntu 26.04 polkit(8)

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Authorization-manager architecture for untrusted subjects requesting operations from privileged mechanisms. This is the basis for Guardian's per-action authorization boundary.

## Contract-relevant points

- Resolute provides polkit 127.
- A privileged mechanism is expected to treat the requesting subject as untrusted and ask the polkit authority for an authorization decision.
- Authentication agents are separate from the mechanism, allowing GUI and text authentication surfaces.

## Refresh metadata

- Canonical URL: https://manpages.ubuntu.com/manpages/resolute/man8/polkit.8.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [Polkit](../../10_Platform/Polkit.md)
- [Privilege and Authorization](../../20_Control_Plane/Privilege_and_Authorization.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
