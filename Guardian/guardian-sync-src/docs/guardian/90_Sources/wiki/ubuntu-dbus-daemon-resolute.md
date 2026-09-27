---
title: "Ubuntu 26.04 dbus-daemon(1)"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - d-bus
source_url: "https://manpages.ubuntu.com/manpages/resolute/man1/dbus-daemon.1.html"
source_checked: "2026-08-30"
---
# Ubuntu 26.04 dbus-daemon(1)

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Ubuntu Resolute manpage for the system/session message bus. It defines vendor vs administrator policy locations, system-service activation directories, message-bus security policy, and systemd activation behavior.

## Contract-relevant points

- Resolute page reports dbus-daemon 1.16.2-2ubuntu4.
- Third-party package default system-bus policy belongs under /usr/share/dbus-1/system.d; /etc/dbus-1/system.d is for administrator overrides.
- Packaged system-service activation files may live under /usr/share/dbus-1/system-services.
- The system bus should use simple transport/policy controls while semantic authorization belongs in the privileged mechanism.

## Refresh metadata

- Canonical URL: https://manpages.ubuntu.com/manpages/resolute/man1/dbus-daemon.1.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [D-Bus](../../10_Platform/D-Bus.md)
- [D-Bus API Contract](../../20_Control_Plane/D-Bus_API_Contract.md)
- [Privilege and Authorization](../../20_Control_Plane/Privilege_and_Authorization.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
