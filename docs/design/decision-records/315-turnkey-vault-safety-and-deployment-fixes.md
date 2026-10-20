# DR315 — Turnkey vault safety and deployment corrections

Date: 2026-10-20.

## Decision

Creating a turnkey guest must never imply that every stored credential should
be available to that guest. Turnkey provisions carried systems and applications
only; an administrator grants each selected secret to each selected target in
Credential Vault. Vault and turnkey operations must also stop cleanly when
USER_ADMIN is not mounted. The host AI synchronization service uses the
preinstalled launcher because its systemd sandbox makes `/opt/baseline`
read-only.

Sensitive HTTP actions remain admin-only. File uploads validate request origin
before consuming request bytes. File-manager rename and delete preserve the
target of a symlink and operate on the link itself. Build-time vault staging
locates mounted CACHE volumes without requiring a particular desktop user's
mount path.

## Evidence

TDD regressions were added for unlocked-vault deletion, explicit-only turnkey
grants, authorization, detached USER_ADMIN behavior, symlink operations,
upload origin checks, guest credential directory ownership, the read-only AI
launcher and CACHE-based staging. The focused suite passed 184 tests. The full
suite reported 5284 passed, 2 failed, 2 skipped and 3 expected failures; the two
failures exposed test-root availability handling, which was corrected and
verified by a focused rerun (6 passed).

No physical deployment, native PC601 boot or provider authentication occurred
in this pass. Prior QEMU FydeOS display/input evidence remains exactly as stated
in DR314. Queue72/78 native Proxmox/render-node, owner onboarding, retention and
application integration remain open. This record does not supersede DR310–314;
INSTALL.md and the work queue carry the current status.
