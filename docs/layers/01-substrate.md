# 01 · Substrate

**Status: In progress** · [index](README.md)

Proxmox VE on its own drive (the `pve` volume group), plus Baseline's own
services that run on top of it. This is the layer the rest is built on and
the only one that is rebuilt rather than preserved.

## What lives here

- The Proxmox VE root filesystem and the `pve` LVM volume group.
- Baseline's services: the control-panel web UI, the firstboot state machine
  (`firstboot_statemachine.py`), the read-only Claude Code harness.
- Nothing personal. Credentials, state and logs are redirected off this layer
  onto a USER volume by bind mounts (`persist_bind_mounts.py`), so a rebuild
  of the substrate loses nothing the operator cares about.

## What must never live here

Anything that has to survive a rebuild. `/etc/baseline`, `/var/lib/baseline`
and `/var/log/baseline` are bind-mounted from the active persona's USER
volume; if that volume is not mounted, `ensure_redirect` refuses to touch the
path rather than write through to this disposable layer.

## Code integrity: the installed code is not writable by what runs it

An attacker (or a bug) inside a service must not be able to rewrite the code that
decides who gets privileges. Provisioning therefore makes `/opt/baseline` root-owned
and not group- or world-writable (`chown -R root:root`, `chmod -R go-w`), tightens any
existing state under `/var/lib/baseline`, and **fails the verification step** if any
installed file is not root-owned or is writable by others. Every unit that runs code
from `/opt/baseline` also mounts it read-only for the service (`ReadOnlyPaths=`) and
sets `PYTHONDONTWRITEBYTECODE=1`. New settings stores are created mode 0600 in a 0700
directory. These are checked statically in `tests/unit/test_deploy_hardening.py`;
none of it has run on a real host yet.

What this does **not** cover, and why a bare SHA comparison would not either: anyone
with root can still change everything, and a hash checked by the same code can be
rewritten along with it. The stronger controls need something below the application:
measured boot with the privileged secrets sealed to a TPM, and an integrity check on
the store (v0.2 rows 52-53). `NoNewPrivileges=` is deliberately not set because Drive
Administration needs `pkexec`.

## Service start gates (`ExecStartPre`)

These decide whether a service may *start*. They are not login checks; the
login gate is separate and lives in the web apps (`_refuse_unauthenticated`,
v0.2 row 43).

| Gate | Entry point | Service | Refuses to start until |
|---|---|---|---|
| `settings_web_gate.py` | `baseline/bin/baseline-settings-web-gate` | `baseline-web.service` (the deployed web app, `boot/baseline-web.service`; also the older standalone `baseline-settings-web.service`) | `baseline-firstboot.service` has genuinely committed, so editing network/firewall/SSH in the UI cannot race firstboot |
| `kiosk_gate.py` | `baseline-kiosk-gate` | `baseline-kiosk.service` | the same condition, so the kiosk never shows on an unconfigured machine |
| `scripts_inbox_gate.py` | `baseline-scripts-inbox-gate` | `baseline-scripts-inbox.service` | USER is actually mounted, so a pushed script cannot land on the disposable substrate |

All three fail closed: `settings_web_gate.check()` returns 0 only if
`firstboot_statemachine.already_completed()` is true, and the entry point prints
a refusal to stderr and exits non-zero otherwise. They reuse the real checks
(`already_completed`, `persist_bind_mounts.is_mounted`) rather than a second
notion of "done" that could drift. `boot/provision.sh` copies and `chmod +x`'s
them.

## First-run setup on the deployed app

`baseline_web.py` (what `baseline-web.service` runs) logs in against the system
account's password and elevates with the root password. Its `/setup` page sets the
machine passphrase that, together with the root password, unlocks recovery mode
(v0.2 row 49). It sits behind the normal login, because an open page would let
whoever reaches a fresh machine first set its recovery passphrase. It works once:
while a passphrase exists, a second attempt is refused and cannot replace it. Only a
salted one-way hash is stored. The standalone `settings_web.py` server has its own
first-run flow (`create_first_account`) that also creates the first account and the
admin elevation passphrase (rows 44-48).

## Status

| Item | Status | Verified | Evidence |
|---|---|---|---|
| Install pipeline (answer file, ISO build, firstboot) | In progress | QEMU | v0.2 work queue; real-hardware end to end still pending |
| Drive targeting by serial, refusing the boot drive | MVP completed | unit tests | `physical_device_safety.py` |
| Control-plane paths redirected onto USER via bind mounts | In progress | unit tests | `persist_bind_mounts.py` says itself it has not run on real hardware (DR 62) |
| Service start gates documented | MVP completed | unit tests | table above; v0.2 row 33 |
| Measured boot, gateway | On roadmap | none | [Hardened-appliance PRD](../design/hardened-appliance-prd.md) |

## Deeper reading

[`docs/INSTALL.md`](../INSTALL.md) · [`docs/BAREMETAL_BRINGUP_NOTES.md`](../BAREMETAL_BRINGUP_NOTES.md) · [`firstboot_statemachine.py`](../../baseline/lib/firstboot_statemachine.py)
