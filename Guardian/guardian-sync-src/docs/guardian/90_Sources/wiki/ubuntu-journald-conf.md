---
title: "Ubuntu 26.04 journald.conf(5)"
kind: "external-source-snapshot"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - systemd-journald
source_url: "https://manpages.ubuntu.com/manpages/resolute/man5/journald.conf.5.html"
source_checked: "2026-08-30"
---
# Ubuntu 26.04 journald.conf(5)

> Local Guardian-oriented reference snapshot. The canonical source URL above remains authoritative and should be rechecked before changing a contract.

## Why Guardian keeps this source

Journal storage and quota configuration reference used by Guardian operational logging and later Log Lens/capacity controls.

## Contract-relevant points

- Guardian operational daemon logs should use journald.
- Guardian transaction/incident state should not rely on journald as its only database.
- Journal storage limits and free-space policies should be exposed as provider-backed configuration rather than reimplemented.

## Refresh metadata

- Canonical URL: https://manpages.ubuntu.com/manpages/resolute/man5/journald.conf.5.html
- Last checked: 2026-08-30
- Refresh method: revisit the canonical URL, compare contract-relevant semantics, then update this snapshot and `SOURCE_REGISTRY.md`.
- Update sensitivity: **high** if a D-Bus signature, polkit action, package major version, or provider ownership rule changes.

## Guardian pointers

- [Journald and Logrotate](../../10_Platform/Journald_and_Logrotate.md)
- [Event and Incident Model](../../20_Control_Plane/Event_and_Incident_Model.md)
- [Logs and Incidents](../../40_Modules/Logs_and_Incidents.md)

## TDD use

When a TDD test asserts behavior derived from this provider, link the test or ADR back to this source page rather than embedding an untraceable assumption in code.
