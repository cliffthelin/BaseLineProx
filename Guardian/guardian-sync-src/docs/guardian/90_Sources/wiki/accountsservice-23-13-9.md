---
title: "AccountsService 23.13.9 API"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - accountsservice
source_url: "https://freedocs.mi.hdm-stuttgart.de/doc/accountsservice/spec/AccountsService.html"
source_checked: "2026-08-30"
---
# AccountsService 23.13.9 API

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Session/user D-Bus API used for Guardian's next-login desktop-session provider.

## Contract-relevant points

- SetSession sets the user's Wayland or X session.
- SetXSession is deprecated because graphical sessions are not necessarily X.
- Guardian should validate requested sessions against installed session definitions before a privileged write.

## Refresh metadata

- Canonical URL: https://freedocs.mi.hdm-stuttgart.de/doc/accountsservice/spec/AccountsService.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [AccountsService](../../10_Platform/AccountsService.md)
- [Session Management](../../40_Modules/Session_Management.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
