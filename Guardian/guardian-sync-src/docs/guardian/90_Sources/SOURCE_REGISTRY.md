---
title: "Source Registry"
kind: "source-registry"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - source
  - registry
---
# Source Registry

This registry is the update anchor for external documentation used by Guardian.

## Rules

1. A local source snapshot is **not** the authority; its canonical URL is.
2. Before changing a TDD assertion derived from an external provider, recheck the canonical source.
3. If a D-Bus interface/polkit policy changes, update the source snapshot, provider provenance fixture, affected wiki pages, ADR/TDD contract, and tests together.
4. Preserve historical decisions in Git rather than overwriting why a contract existed.
5. `90_Sources/raw/*.url.txt` contains one-line canonical URL pointers for refresh scripts.

| Local snapshot | Provider | Last checked | Canonical URL | Update sensitivity |
|---|---|---:|---|---|
| [Ubuntu 26.04 dbus-daemon(1)](wiki/ubuntu-dbus-daemon-resolute.md) | `D-Bus` | 2026-08-30 | [canonical](https://manpages.ubuntu.com/manpages/resolute/man1/dbus-daemon.1.html) | high |
| [Ubuntu 26.04 polkit(8)](wiki/ubuntu-polkit-resolute.md) | `polkit` | 2026-08-30 | [canonical](https://manpages.ubuntu.com/manpages/resolute/man8/polkit.8.html) | high |
| [pkttyagent textual authorization helper](wiki/ubuntu-pkttyagent.md) | `polkit` | 2026-08-30 | [canonical](https://manpages.ubuntu.com/manpages/resolute/man1/pkttyagent.1.html) | high |
| [Ubuntu 26.04 systemd.resource-control(5)](wiki/ubuntu-systemd-resource-control.md) | `systemd` | 2026-08-30 | [canonical](https://manpages.ubuntu.com/manpages/resolute/man5/systemd.resource-control.5.html) | high |
| [Ubuntu 26.04 systemd.exec(5)](wiki/ubuntu-systemd-exec.md) | `systemd` | 2026-08-30 | [canonical](https://manpages.ubuntu.com/manpages/resolute/man5/systemd.exec.5.html) | high |
| [Ubuntu 26.04 systemd.service(5)](wiki/ubuntu-systemd-service.md) | `systemd` | 2026-08-30 | [canonical](https://manpages.ubuntu.com/manpages/resolute/man5/systemd.service.5.html) | high |
| [Ubuntu 26.04 journald.conf(5)](wiki/ubuntu-journald-conf.md) | `systemd-journald` | 2026-08-30 | [canonical](https://manpages.ubuntu.com/manpages/resolute/man5/journald.conf.5.html) | high |
| [Linux kernel PSI — Pressure Stall Information](wiki/linux-psi.md) | `Linux kernel` | 2026-08-30 | [canonical](https://cdn.kernel.org/doc/html/latest/accounting/psi.html) | high |
| [NetworkManager D-Bus Manager API](wiki/networkmanager-dbus.md) | `NetworkManager` | 2026-08-30 | [canonical](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/gdbus-org.freedesktop.NetworkManager.html) | high |
| [UDisks2 Drive D-Bus API](wiki/udisks-drive.md) | `UDisks2` | 2026-08-30 | [canonical](https://storaged.org/doc/udisks2-api/latest/gdbus-org.freedesktop.UDisks2.Drive.html) | high |
| [AccountsService 23.13.9 API](wiki/accountsservice-23-13-9.md) | `AccountsService` | 2026-08-30 | [canonical](https://freedocs.mi.hdm-stuttgart.de/doc/accountsservice/spec/AccountsService.html) | high |
| [UPower D-Bus API Reference](wiki/upower-dbus.md) | `UPower` | 2026-08-30 | [canonical](https://upower.freedesktop.org/docs/ref-dbus.html) | high |
| [Power Profiles daemon D-Bus API](wiki/power-profiles-dbus.md) | `power-profiles-daemon` | 2026-08-30 | [canonical](https://freedesktop-team.pages.debian.net/power-profiles-daemon/ref-dbus.html) | high |
| [zbus Rust D-Bus library](wiki/zbus-docs.md) | `zbus` | 2026-08-30 | [canonical](https://docs.rs/zbus/latest/zbus/index.html) | high |
| [ksni Rust StatusNotifierItem library](wiki/ksni-docs.md) | `ksni` | 2026-08-30 | [canonical](https://docs.rs/ksni/latest/ksni/) | high |
| [Ubuntu 26.04 libayatana-appindicator-glib2 package](wiki/ayatana-glib-resolute.md) | `Ubuntu / Ayatana` | 2026-08-30 | [canonical](https://packages.ubuntu.com/en/resolute/libayatana-appindicator-glib2) | high |
| [systemd-logind and inhibitor locks](wiki/systemd-logind.md) | `systemd-logind` | 2026-08-30 | [canonical](https://wiki.freedesktop.org/www/Software/systemd/logind/) | high |

## Future source additions

Add a source when it either:
- defines an external contract Guardian relies on;
- supplies a safety constraint;
- is the authoritative Ubuntu package/version source;
- is used to justify a TDD acceptance criterion or ADR.

Do not add generic articles merely because they mention a technology.
