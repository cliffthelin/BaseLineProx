---
title: "Self Lookup Map"
kind: "lookup-index"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - lookup
  - index
---
# Self Lookup Map

Use this as the fast semantic router for coding agents, TDD work, audits, and future documentation maintenance.

| Search terms / question | Guardian interpretation | Authoritative/source pointer |
|---|---|---|
| D-Bus, IPC, bus policy | [D-Bus API Contract](20_Control_Plane/D-Bus_API_Contract.md) | [ubuntu-dbus-daemon-resolute](90_Sources/wiki/ubuntu-dbus-daemon-resolute.md) |
| authorization, polkit, root, permissions | [Privilege and Authorization](20_Control_Plane/Privilege_and_Authorization.md) | [ubuntu-polkit-resolute](90_Sources/wiki/ubuntu-polkit-resolute.md) |
| TUI auth, VT, recovery authentication | [Privilege and Authorization](20_Control_Plane/Privilege_and_Authorization.md) | [ubuntu-pkttyagent](90_Sources/wiki/ubuntu-pkttyagent.md) |
| cgroup, MemoryHigh, IOWeight, throttle | [Diagnostic Budget](20_Control_Plane/Diagnostic_Budget.md) | [ubuntu-systemd-resource-control](90_Sources/wiki/ubuntu-systemd-resource-control.md) |
| systemd sandbox, capabilities | [Privilege and Authorization](20_Control_Plane/Privilege_and_Authorization.md) | [ubuntu-systemd-exec](90_Sources/wiki/ubuntu-systemd-exec.md) |
| transaction, rollback, checkpoint | [Transaction Engine](20_Control_Plane/Transaction_Engine.md) | [networkmanager-dbus](90_Sources/wiki/networkmanager-dbus.md) |
| USB disk, drive poweroff, sibling | [IO Guardian](40_Modules/IO_Guardian.md) | [udisks-drive](90_Sources/wiki/udisks-drive.md) |
| PSI, pressure, stall, bottleneck | [Diagnostic Budget](20_Control_Plane/Diagnostic_Budget.md) | [linux-psi](90_Sources/wiki/linux-psi.md) |
| GNOME, XFCE, session switch | [Session Management](40_Modules/Session_Management.md) | [accountsservice-23-13-9](90_Sources/wiki/accountsservice-23-13-9.md) |
| battery, UPS, power device | [Thermal and Power](40_Modules/Thermal_and_Power.md) | [upower-dbus](90_Sources/wiki/upower-dbus.md) |
| power profile, performance mode, holds | [Thermal and Power](40_Modules/Thermal_and_Power.md) | [power-profiles-dbus](90_Sources/wiki/power-profiles-dbus.md) |
| tray, indicator, StatusNotifierItem, SNI | [StatusNotifierItem](10_Platform/StatusNotifierItem.md) | [ksni-docs](90_Sources/wiki/ksni-docs.md) |
| logs, journald, quota | [Logs and Incidents](40_Modules/Logs_and_Incidents.md) | [ubuntu-journald-conf](90_Sources/wiki/ubuntu-journald-conf.md) |
| shutdown blocker, suspend blocker, inhibitor | [System Blockers](40_Modules/System_Blockers.md) | [systemd-logind](90_Sources/wiki/systemd-logind.md) |
| provider owner, conflict, single writer | [Provider Arbitrator](20_Control_Plane/Provider_Arbitrator.md) | [SOURCE REGISTRY](90_Sources/SOURCE_REGISTRY.md) |
| event, incident, evidence | [Event and Incident Model](20_Control_Plane/Event_and_Incident_Model.md) | [GUARDIAN PHASE 0 1 TDD CONTRACT](30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md) |
| flight recorder, ring buffer | [Flight Recorder](20_Control_Plane/Flight_Recorder.md) | [GUARDIAN PHASE 0 1 TDD CONTRACT](30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md) |

## Lookup discipline

When implementing:
1. Start here or `INDEX.md`.
2. Read the Guardian interpretation page.
3. Follow its external-source pointer.
4. Check the governing TDD contract/gate.
5. If behavior remains ambiguous, create/update an ADR instead of inventing provider semantics in code.
