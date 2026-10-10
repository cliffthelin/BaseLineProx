# Handoff — 2026-10-05 GUI and Ubuntu overlay acceptance

## User goal

Continue until both the Baseline host GUI/browser and a configured Ubuntu GUI
work and have been tested. That virtual acceptance is complete. Do not report it
as a physical cold boot: only the physical source disk was used as read-only
backing for an isolated KVM clone.

## Verified results

- Current source provisioned and completed firstboot in a KVM clone of PC401.
- The shipped cage/Chromium kiosk displayed Proxmox, authenticated with a
  disposable test login, and started again after orderly virtual host shutdown
  and relaunch. Storage, persistence bind mounts, firstboot, web and kiosk
  services were active after restart.
- The Baseline web UI ran in real Chromium. Authenticated web workflows acquired
  Canonical's pinned Ubuntu image and created a Proxmox-managed Ubuntu Desktop.
- Ubuntu booted with the selected `en_GB.UTF-8` locale, homepage, desktop and
  separate retained home disk. GDM login and Firefox rendering/authentication
  against the Proxmox endpoint were observed on screen.
- Two actual OS-overlay rebuilds retained the generated login, a user document
  (SHA256 `37e7e1fe20de9d4138fe8012a769292d5a8d9807d85bdfdad761a4e90a9e930d`)
  and Firefox-created bookmark. The marker written only to the OS disk vanished.
  A stopped-guest read-only inspection confirmed the retained files and cleaned
  up its mount and NBD connection.
- Native configuration verification passed. It deliberately leaves GUI-rendered
  facts to screenshot/runtime evidence instead of inferring them from settings.
- Full unit suite: **3412 passed**. Production changes had regression tests that
  failed before the fixes. `git diff --check` passed.

## Fixes made during live acceptance

Firstboot now rechecks fresh network facts before declaring health. The
persistence bind-mount service publishes mounts in the host namespace. The
threaded web server serializes shared SQLite access. New installation profiles
reserve 50 GiB for BASELINE while legacy storage policies remain valid. A native
storage reconciliation command repairs an obsolete `pve` VG reference only
after validating the target serial and refuses ambiguous/foreign VGs. Ubuntu
Firefox seed policy, native verification and desktop homepage startup now
agree.

## Evidence and source records

- [Verification index](verification/165/README.md)
- [Full unit test output](verification/165/unit-tests.txt)
- Host kiosk before and after restart: `verification/165/host-kiosk.png`,
  `verification/165/host-kiosk-after-restart.png`
- Ubuntu browser after rebuild: `verification/165/ubuntu-firefox-after-rebuild.png`
- Final native configuration: `verification/165/ubuntu-configuration-after-rebuild.json`
- Two-rebuild retained-home inspection:
  `verification/165/retention-after-two-rebuilds.json`
- Physical source read-only block graph: `verification/165/block-graph.json`
- Decision record: `design/decision-records/165-live-gui-installation-continuation.md`
- Current installation status: `INSTALL.md`; narrative session history:
  `SESSION_HANDOFF.md`.

## Limits and next work

This proves the virtualized host and nested Ubuntu GUI flows, not native PC401
cold boot. Physical cold boot and broader isolation/integration acceptance stay
open under v0.2 queue items 72, 74, 75, 76 and 78. Preserve the physical source
read-only until the queued identity and boot gates authorize an operation. Do
not expose or reuse disposable test credentials.

During fixture setup, one mistimed console input displayed a generated Ubuntu
test password. It was rotated through the real login-reset job and temporary
captures were removed. No operator credential was handled. Firefox also showed
its normal retained-session recovery prompt (Start New Session was selected),
and the disposable Proxmox certificate needed normal browser acceptance.
