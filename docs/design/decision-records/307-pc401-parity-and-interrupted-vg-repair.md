# DR307 — PC401 source parity and interrupted VG boot repair

2026-10-12. Source/unit verification only; PC401 deployment and native boot remain open.

The operator requested review of Claude's work and a PC401 drive working equal
or better. A new isolated checkout in `baseline-build/codex-pc401` on
`codex/pc401-parity` merges Claude's branch through `3cb4c37`, preserving the
Codex installer UUID `5029a80d-c748-4616-aa08-99ac560f5311`. Merge commit
`259240d` retains DR305 command-failure reporting and DR306 exclusive bridge
backups alongside Claude's NIC negotiation, USB, persistence, storage, browser,
firewall and VG rename changes. Neither original checkout was changed.

Review found that successful `vgrename` followed by failed boot regeneration
could be marked complete, or skipped on retry because the VG already had its
new name. `host_layout` now durably records the original name, serial and VG
UUID before renaming. Failed initramfs or boot regeneration leaves that repair
pending; retries with the same identity rebuild boot files without renaming
again. A foreign or malformed journal is refused. Failed destination-VG
ownership observation now refuses before `vgrename`.

The installed-drive updater also used the broader enrollment allowlist,
allowing the other lane's serial into discovery/update. It now applies the
source-pinned lane exclusion before source validation or target commands.
PC601 is refused in the Codex lane even when an input bundle is invalid.

Two production-path regressions failed against the merged Claude source
before the VG fix. New journal tests use real temporary files; existing
host-layout command tests inject responses and are explicitly unit evidence.
Focused tests: 121 passed. Provision dependency closure and shell syntax passed.
The full unit run after merging, before the added fixes, recorded 3,661 passed,
262 failed, 59 errors, 3 xfailed and 9 subtests passed: 319 failures/errors were
`Operation not permitted` and two were console timeouts. This is not a green
full-suite claim. HTTP/socket and console checks need a runtime-capable session.

Read-only PC401 preflight stopped on missing `/dev/sdm`. Host sysfs/lsblk lists
PC401 serial `<PC401 drive serial>`, but this execution namespace exposes neither
that block node nor `/dev/kvm`. No drive write, format, credential operation,
VM launch or physical boot was performed. Evidence: `docs/verification/307/`.

Queue72/74/75/76/78 remain open. Next work requires host device/KVM access:
fresh serial resolution and use-state/recovery inspection, guarded deployment
or an explicitly authorized rebuild, boot with both drives attached, visible
browser/login, changed-NIC LAN and firewall checks, default environments/apps,
and persistence acceptance. PC601 installation log12 reports clean kiosk
shutdown and completed installation; that historical log is not fresh native
PC401 or PC601 acceptance. DR258's default installed applications, DR257's root
LV naming and publishability work are still gaps in the imported source.
