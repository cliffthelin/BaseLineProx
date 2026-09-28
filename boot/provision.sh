#!/bin/bash
# Baseline V0.1 provisioning - turns a fresh Proxmox VE install into a
# Baseline host. Run as root on the target machine.
#
# Captures what we learned standing this up manually: Proxmox's enterprise
# repos need a paid subscription and will break `apt update` with a 401
# until disabled; Claude Code needs Node >=22 or it busy-loops on CPUs
# missing modern instruction set extensions (a QEMU testing artifact, not
# expected on real hardware, but Node 22 is required regardless).
set -euo pipefail

echo "=== Disabling Proxmox enterprise repos (no subscription assumed) ==="
for f in pve-enterprise.sources ceph.sources; do
    if [ -f "/etc/apt/sources.list.d/$f" ]; then
        mv "/etc/apt/sources.list.d/$f" "/etc/apt/sources.list.d/$f.disabled"
    fi
done
apt-get update

echo "=== Installing base packages ==="
apt-get install -y inxi python3-rich python3-textual tmux gnupg

echo "=== Installing kiosk GUI packages (Track A3 - cage + stock Chromium) ==="
apt-get install -y cage chromium

echo "=== Installing Podman (Track B4 - Quadlet service management) ==="
apt-get install -y podman
mkdir -p /etc/containers/systemd

echo "=== Installing Node.js 22 (NodeSource - Debian's own package is too old) ==="
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs

echo "=== Installing Claude Code ==="
npm install -g @anthropic-ai/claude-code

echo "=== Deploying Baseline app ==="
mkdir -p /opt/baseline/bin /opt/baseline/lib /etc/baseline /var/lib/baseline
SRC="$(dirname "$0")/.."
cp "$SRC/baseline/bin/baseline" /opt/baseline/bin/baseline
cp "$SRC/baseline/bin/baseline-auth-setup.sh" /opt/baseline/bin/baseline-auth-setup.sh
cp "$SRC/baseline/lib/hardware.py" /opt/baseline/lib/hardware.py
cp "$SRC/baseline/lib/network.py" /opt/baseline/lib/network.py
cp "$SRC/baseline/lib/harness.py" /opt/baseline/lib/harness.py
# harness.py's own real dependency, missed by every prior audit pass
# because harness.py is staged via this direct cp line, never reached
# through baseline/bin/baseline's own import graph - the checker only
# caught it once its scan was widened to also walk directly-cp'd lib
# modules' own imports (decision record 66/67). harness.py imports
# this unconditionally (event-stream parsing) - without it,
# baseline.service would crash with ModuleNotFoundError the first time
# it actually processes a streamed event.
cp "$SRC/baseline/lib/stream_json.py" /opt/baseline/lib/stream_json.py
# harness.py/bin/baseline's own real transitive dependencies - found
# missing entirely from this deployment list by a real import-graph
# audit (every bin script provision.sh installs, resolved against what
# it and its dependencies actually `import`, cross-checked against
# this file's own copy list). Without these, `baseline.service` would
# have crashed with ModuleNotFoundError on its very first real start.
cp "$SRC/baseline/lib/harness_adapter.py" /opt/baseline/lib/harness_adapter.py
cp "$SRC/baseline/lib/harness_registry.py" /opt/baseline/lib/harness_registry.py
cp "$SRC/baseline/lib/harness_events.py" /opt/baseline/lib/harness_events.py
cp "$SRC/baseline/lib/clipboard_osc52.py" /opt/baseline/lib/clipboard_osc52.py
cp "$SRC/baseline/lib/status_bar.py" /opt/baseline/lib/status_bar.py
cp "$SRC/baseline/lib/netpref.py" /opt/baseline/lib/netpref.py
cp "$SRC/baseline/lib/providers.py" /opt/baseline/lib/providers.py
cp "$SRC/baseline/lib/tether.py" /opt/baseline/lib/tether.py
cp "$SRC/baseline/lib/handoff.py" /opt/baseline/lib/handoff.py
cp "$SRC/baseline/bin/baseline-setup-wizard" /opt/baseline/bin/baseline-setup-wizard
# Host-network repair (docs/design/reset-interface-to-dhcp-plan.md,
# docs/design/decision-records/11-repair-branch-comparison.md) - the
# same-boot rollback path only. The permanent boot-time recovery service
# for the reboot-during-window case is NOT installed here yet; see
# baseline/lib/repair_rollback.py's module docstring for why.
cp "$SRC/baseline/lib/ifnet_config.py" /opt/baseline/lib/ifnet_config.py
cp "$SRC/baseline/lib/topology.py" /opt/baseline/lib/topology.py
cp "$SRC/baseline/lib/repair.py" /opt/baseline/lib/repair.py
cp "$SRC/baseline/lib/repair_additive.py" /opt/baseline/lib/repair_additive.py
cp "$SRC/baseline/lib/repair_additive_persist.py" /opt/baseline/lib/repair_additive_persist.py
cp "$SRC/baseline/lib/repair_rollback.py" /opt/baseline/lib/repair_rollback.py
cp "$SRC/baseline/lib/firstboot_network_repair.py" /opt/baseline/lib/firstboot_network_repair.py
cp "$SRC/baseline/bin/baseline-repair-rollback" /opt/baseline/bin/baseline-repair-rollback
cp "$SRC/baseline/bin/baseline-additive-dhcp-reapply" /opt/baseline/bin/baseline-additive-dhcp-reapply
# Gate E: the real, integrated first-boot authorization state machine
# (docs/design/decision-records/25) - connects proxmox_detect.py
# (informational), firstboot_network_repair.py's already-real Gate A
# repair pipeline, and package install/verification for the five
# diagnostic tools behind one durable completion marker + one CONFIRM
# gate. See baseline/lib/firstboot_statemachine.py's module docstring.
cp "$SRC/baseline/lib/proxmox_detect.py" /opt/baseline/lib/proxmox_detect.py
cp "$SRC/baseline/lib/diagnostics.py" /opt/baseline/lib/diagnostics.py
cp "$SRC/baseline/lib/setup_intent.py" /opt/baseline/lib/setup_intent.py
# config_apply.py/config_pipeline.py: firstboot_statemachine.py imports
# config_pipeline at module scope (decision record 51) - also found
# missing entirely from this deployment list by the same real
# import-graph audit. Without these, baseline-firstboot.service would
# have crashed on import before Gate E ever ran at all.
cp "$SRC/baseline/lib/config_apply.py" /opt/baseline/lib/config_apply.py
cp "$SRC/baseline/lib/config_pipeline.py" /opt/baseline/lib/config_pipeline.py
cp "$SRC/baseline/lib/firstboot_statemachine.py" /opt/baseline/lib/firstboot_statemachine.py
cp "$SRC/baseline/bin/baseline-firstboot" /opt/baseline/bin/baseline-firstboot
# Redirects Baseline's own control-plane paths (/etc/baseline,
# /var/lib/baseline, /var/log/baseline) onto the USER_PERSISTENCE
# partition via bind mounts, per direct instruction ("All user data
# including credentials and config and logs should go to the User
# Persistence partition") - decision record 62. Must run, and succeed,
# before baseline-firstboot.service or baseline.service ever touch
# those paths; see boot/baseline-persist-bind-mounts.service's own
# ordering. Not yet run against real hardware.
cp "$SRC/baseline/lib/persist_bind_mounts.py" /opt/baseline/lib/persist_bind_mounts.py
cp "$SRC/baseline/bin/baseline-persist-bind-mounts" /opt/baseline/bin/baseline-persist-bind-mounts
# Physical Phase P0: read-only current-drive inventory collector, ported
# from cliffthelin/baseline's inventory/current-drive-manifest branch
# (docs/design/current-drive-inventory-plan.md) - never invoked by
# provision.sh or any other automated path; deployed so it is present
# for an operator to run by hand (`baseline-drive-inventory collect`)
# on demand. Collects only; never repairs, reconfigures, or restarts
# anything.
cp -r "$SRC/baseline/lib/inventory" /opt/baseline/lib/inventory
cp "$SRC/baseline/bin/baseline-drive-inventory" /opt/baseline/bin/baseline-drive-inventory
# Track A5: unified sensors + per-VM dashboard. proxmox_vm_metrics.py
# queries Proxmox's own pvesh for live/historical per-VM stats (no
# storage of our own); sensors_history.py + sensors_collect.py are the
# host-sensor half's small periodic store, since diagnostics.py's
# collectors have no equivalent existing history source to reuse. See
# baseline/lib/sensors_collect.py's module docstring.
cp "$SRC/baseline/lib/proxmox_vm_metrics.py" /opt/baseline/lib/proxmox_vm_metrics.py
cp "$SRC/baseline/lib/sensors_history.py" /opt/baseline/lib/sensors_history.py
cp "$SRC/baseline/lib/sensors_collect.py" /opt/baseline/lib/sensors_collect.py
cp "$SRC/baseline/bin/baseline-sensors-collect" /opt/baseline/bin/baseline-sensors-collect
# Per-source collection cadence, live-adjustable (decision record 72):
# checking one specific source (e.g. nvme) as often as every second
# during a time of high concern, without restarting anything and
# without changing any other source's own cadence. Per-source gating
# lives in sensors_history.py's own tables; sensors_interval_control.py
# is the one thing that can't be scoped per-source - the outer systemd
# timer tick baseline-sensors-collect.timer itself, applied via a
# drop-in override, never by editing the shipped .timer unit.
cp "$SRC/baseline/lib/sensors_interval_control.py" /opt/baseline/lib/sensors_interval_control.py
cp "$SRC/baseline/bin/baseline-sensors-set-interval" /opt/baseline/bin/baseline-sensors-set-interval
# Track A3: kiosk GUI (cage + stock Chromium) onto Proxmox's own web UI.
# kiosk_gate.py reuses firstboot_statemachine.already_completed() unchanged
# so the kiosk can never appear before the machine is actually configured.
cp "$SRC/baseline/lib/kiosk_gate.py" /opt/baseline/lib/kiosk_gate.py
cp "$SRC/baseline/bin/baseline-kiosk-gate" /opt/baseline/bin/baseline-kiosk-gate
# Browser settings UI (PRD SS5.16): settings_web.py already existed,
# tested, and was never wired to a systemd unit - this stages it for
# real, gated on firstboot the same way the kiosk GUI is, so it can't
# appear before the machine is actually configured. Data store moved
# from settings_web.py's own /tmp default to /var/lib/baseline so it
# survives a reboot, matching every other persistent-state location
# this project uses.
mkdir -p /var/lib/baseline/settings-web
cp "$SRC/baseline/lib/settings_web.py" /opt/baseline/lib/settings_web.py
cp "$SRC/baseline/lib/settings_web_gate.py" /opt/baseline/lib/settings_web_gate.py
cp "$SRC/baseline/bin/baseline-settings-web" /opt/baseline/bin/baseline-settings-web
cp "$SRC/baseline/bin/baseline-settings-web-gate" /opt/baseline/bin/baseline-settings-web-gate
# settings_store.py + admin_elevation.py (decision record 76) - real
# modules settings_web.py's own Admin tab now imports for real
# (decision record 80); found genuinely missing from this file
# entirely by tools/check_provision_deploys_all_imports.py while
# wiring that tab in - never staged before now.
cp "$SRC/baseline/lib/settings_store.py" /opt/baseline/lib/settings_store.py
cp "$SRC/baseline/lib/admin_elevation.py" /opt/baseline/lib/admin_elevation.py
# Recovery mode itself (work-queue item 26, decision record 81) -
# settings_web.py's guest-tier /recovery route reaches this directly;
# persist_bind_mounts.py's own main() also calls it on a real cascade
# failure (both already staged).
cp "$SRC/baseline/lib/recovery_mode.py" /opt/baseline/lib/recovery_mode.py
cp "$SRC/baseline/bin/baseline-recovery-mode" /opt/baseline/bin/baseline-recovery-mode
# Scripts inbox (decision record 70): "it's just files with server and
# folder access to CRUD" - a login-gated CRUD server so a script
# pushed from any client lands in a real folder an operator later runs
# by hand from a terminal. Never executes anything itself. Reuses
# settings_web.py's own auth machinery directly rather than
# duplicating it. Gated on USER_PERSISTENCE actually being mounted
# (scripts_inbox_gate.py, reusing persist_bind_mounts.is_mounted
# unchanged) so a script pushed too early can't silently land on the
# disposable substrate instead.
cp "$SRC/baseline/lib/scripts_inbox.py" /opt/baseline/lib/scripts_inbox.py
cp "$SRC/baseline/lib/scripts_inbox_web.py" /opt/baseline/lib/scripts_inbox_web.py
cp "$SRC/baseline/lib/scripts_inbox_gate.py" /opt/baseline/lib/scripts_inbox_gate.py
cp "$SRC/baseline/bin/baseline-scripts-inbox" /opt/baseline/bin/baseline-scripts-inbox
cp "$SRC/baseline/bin/baseline-scripts-inbox-gate" /opt/baseline/bin/baseline-scripts-inbox-gate
# App-specific LXC/VM provisioning via pinned + sha256-verified
# community-scripts/ProxmoxVE Helper-Scripts - resolves decision record
# 35's deferred "LXC app-installer vendoring" item; see vm_scripts.py's
# module docstring for the verification model, its disclosed
# limitation, and its relationship to pct_provision.py/vm_provision.py.
# Track B4: Podman + Quadlet service management - see quadlet.py.
# Neither is wired to any systemd unit or automatic trigger; both are
# operator-invoked-only libraries for now (docs/design/decision-records/
# 57, 58).
cp "$SRC/baseline/lib/vm_scripts.py" /opt/baseline/lib/vm_scripts.py
cp "$SRC/baseline/lib/quadlet.py" /opt/baseline/lib/quadlet.py
# vm_scripts.py's own adoption-bridge functions (start/stop/destroy)
# import these two as an optional, try/except-guarded dependency - real
# code, tested (test_vm_provision.py/test_pct_provision.py), but never
# staged before now (decision record 65's audit), silently degrading
# the bridge to a stub CommandResult on any real deployed machine
# rather than crashing. Staged for the same reason vm_scripts.py itself
# is: operator-invoked-only, no systemd unit.
cp "$SRC/baseline/lib/vm_provision.py" /opt/baseline/lib/vm_provision.py
cp "$SRC/baseline/lib/pct_provision.py" /opt/baseline/lib/pct_provision.py
# The real "Master Config" control-plane: target-drive validation,
# config diffing, selective update, and encrypted backup/restore
# (decision record 64) - built and tested but never staged by this
# script until now (decision record 65). Direct correction, decision
# record 83: control_panel_web.py's routes are no longer standalone
# and unauthenticated - baseline-web.service (staged below) merges
# them behind settings_web.py's own real login, so
# backup/restore/update/encrypt-decrypt now sit behind the same
# auth every other tab on that app requires. baseline-control-panel
# itself (staged below too) remains available as a separate,
# standalone, operator-invoked tool for direct local use, same as
# vm_scripts.py/quadlet.py - it is simply no longer the only way to
# reach this functionality. baseline-diff/-update/-backup/-config-crypto
# are plain one-shot CLI tools with no service to wire at all.
cp "$SRC/baseline/lib/physical_device_safety.py" /opt/baseline/lib/physical_device_safety.py
cp "$SRC/baseline/lib/drive_installer.py" /opt/baseline/lib/drive_installer.py
cp "$SRC/baseline/lib/config_diff.py" /opt/baseline/lib/config_diff.py
cp "$SRC/baseline/lib/update_pipeline.py" /opt/baseline/lib/update_pipeline.py
cp "$SRC/baseline/lib/backup_restore.py" /opt/baseline/lib/backup_restore.py
cp "$SRC/baseline/lib/config_crypto.py" /opt/baseline/lib/config_crypto.py
cp "$SRC/baseline/lib/control_panel_web.py" /opt/baseline/lib/control_panel_web.py
# Automated recurring encrypted backup (work-queue item 27, decision
# record 79) - orchestrates backup_restore.py + config_crypto.py on a
# timer, one attempt per real persona.
cp "$SRC/baseline/lib/backup_recurring.py" /opt/baseline/lib/backup_recurring.py
cp "$SRC/baseline/bin/baseline-backup-recurring" /opt/baseline/bin/baseline-backup-recurring
# The merged Baseline web app (decision record 83) - direct
# instruction: "merge those two together and add a Drive
# administration tab... this application will never get off the
# ground if your solution is terminal commands." One real,
# already-root systemd service (baseline-web.service, staged below)
# serving Settings/Admin/Recovery/Drive Administration/Master Config
# behind one real login, with drive_admin.py's privileged actions
# gated on a real /etc/shadow password check
# (settings_web.SystemElevationVerifier), never a script handed back
# to the operator to run themselves.
cp "$SRC/baseline/lib/drive_admin.py" /opt/baseline/lib/drive_admin.py
cp "$SRC/baseline/lib/baseline_web.py" /opt/baseline/lib/baseline_web.py
cp "$SRC/baseline/bin/baseline-web" /opt/baseline/bin/baseline-web
# Remasters the already-verified Proxmox auto-install ISO to also
# carry this repo's own boot/provision.sh + baseline/ tree, so a
# future fresh install needs no separate git-clone/copy step - see
# iso_builder.py's module docstring. A one-shot build command, not a
# service - no systemd unit.
cp "$SRC/baseline/lib/iso_builder.py" /opt/baseline/lib/iso_builder.py
cp "$SRC/baseline/bin/baseline-build-iso" /opt/baseline/bin/baseline-build-iso
cp "$SRC/baseline/bin/baseline-diff" /opt/baseline/bin/baseline-diff
cp "$SRC/baseline/bin/baseline-update" /opt/baseline/bin/baseline-update
cp "$SRC/baseline/bin/baseline-backup" /opt/baseline/bin/baseline-backup
cp "$SRC/baseline/bin/baseline-config-crypto" /opt/baseline/bin/baseline-config-crypto
cp "$SRC/baseline/bin/baseline-control-panel" /opt/baseline/bin/baseline-control-panel
chmod +x /opt/baseline/bin/baseline /opt/baseline/bin/baseline-auth-setup.sh /opt/baseline/bin/baseline-setup-wizard /opt/baseline/bin/baseline-repair-rollback /opt/baseline/bin/baseline-additive-dhcp-reapply /opt/baseline/bin/baseline-firstboot /opt/baseline/bin/baseline-drive-inventory /opt/baseline/bin/baseline-sensors-collect /opt/baseline/bin/baseline-kiosk-gate /opt/baseline/bin/baseline-settings-web /opt/baseline/bin/baseline-settings-web-gate /opt/baseline/bin/baseline-persist-bind-mounts /opt/baseline/bin/baseline-diff /opt/baseline/bin/baseline-update /opt/baseline/bin/baseline-backup /opt/baseline/bin/baseline-config-crypto /opt/baseline/bin/baseline-control-panel /opt/baseline/bin/baseline-build-iso /opt/baseline/bin/baseline-scripts-inbox /opt/baseline/bin/baseline-scripts-inbox-gate /opt/baseline/bin/baseline-sensors-set-interval /opt/baseline/bin/baseline-backup-recurring /opt/baseline/bin/baseline-recovery-mode /opt/baseline/bin/baseline-web

echo "=== Staging systemd units (not yet activated - see verification/activation below) ==="
cp "$SRC/boot/baseline.service" /etc/systemd/system/baseline.service
cp "$SRC/boot/baseline-additive-dhcp-reapply.service" /etc/systemd/system/baseline-additive-dhcp-reapply.service
cp "$SRC/boot/baseline-persist-bind-mounts.service" /etc/systemd/system/baseline-persist-bind-mounts.service
cp "$SRC/boot/baseline-firstboot.service" /etc/systemd/system/baseline-firstboot.service
cp "$SRC/boot/baseline-sensors-collect.service" /etc/systemd/system/baseline-sensors-collect.service
cp "$SRC/boot/baseline-sensors-collect.timer" /etc/systemd/system/baseline-sensors-collect.timer
cp "$SRC/boot/baseline-kiosk.service" /etc/systemd/system/baseline-kiosk.service
# baseline-web.service supersedes baseline-settings-web.service
# (decision record 83) - the merged app is a strict superset, so the
# old unit file is no longer staged/enabled; baseline-settings-web
# the bin script itself remains staged above for standalone use.
cp "$SRC/boot/baseline-web.service" /etc/systemd/system/baseline-web.service
cp "$SRC/boot/baseline-scripts-inbox.service" /etc/systemd/system/baseline-scripts-inbox.service
cp "$SRC/boot/baseline-backup-recurring.service" /etc/systemd/system/baseline-backup-recurring.service
cp "$SRC/boot/baseline-backup-recurring.timer" /etc/systemd/system/baseline-backup-recurring.timer

echo "=== Installing the Proxmox<->BaselineOS return command ==="
# The (p) key inside Baseline switches tty1 -> tty2 (a real Proxmox
# login console); this installs the 'baseline' shell command that
# switches back, so the round trip works both directions.
cp "$SRC/boot/baseline-return.sh" /etc/profile.d/baseline-return.sh

echo "=== Verifying tty1 console font (read-only check, does not touch tty1 ownership) ==="
bash "$SRC/tests/console_font_check.sh"

# --- Atomic verification before any tty1/getty state changes --------------
#
# Milestone 1.1 correction (docs/design/decision-records/26 found the
# defect this fixes): provisioning must NEVER disable or disrupt the
# tty/session it is running from. The previous revision called
# `systemctl disable --now getty@tty1.service` here, which stopped the
# getty backing the very shell executing this script - a real
# self-inflicted interruption, confirmed directly in that record.
#
# The fix: verify every staged file and unit is genuinely present and
# correctly enabled BEFORE touching anything tty1-related, then only
# `systemctl enable` (never `--now`, never touching getty@tty1
# directly) - `baseline-firstboot.service`'s own `Conflicts=
# getty@tty1.service` / `Before=baseline.service` ordering already
# takes over tty1 automatically and safely at the NEXT boot, which is
# systemd's job, not this script's. Activation is deferred to that
# next boot; this script's own execution context is never touched.
echo "=== Verifying staged deployment (fails closed - aborts before any activation step) ==="
verify_fail() { echo "VERIFY FAILED: $1" >&2; exit 1; }

for f in /opt/baseline/bin/baseline /opt/baseline/bin/baseline-firstboot \
         /opt/baseline/bin/baseline-repair-rollback /opt/baseline/bin/baseline-additive-dhcp-reapply \
         /opt/baseline/bin/baseline-sensors-collect \
         /opt/baseline/lib/firstboot_statemachine.py /opt/baseline/lib/firstboot_network_repair.py \
         /opt/baseline/lib/proxmox_detect.py /opt/baseline/lib/diagnostics.py /opt/baseline/lib/setup_intent.py \
         /opt/baseline/lib/repair.py /opt/baseline/lib/repair_additive.py /opt/baseline/lib/network.py \
         /opt/baseline/lib/proxmox_vm_metrics.py /opt/baseline/lib/sensors_history.py /opt/baseline/lib/sensors_collect.py \
         /opt/baseline/lib/kiosk_gate.py /opt/baseline/bin/baseline-kiosk-gate \
         /opt/baseline/lib/settings_web.py /opt/baseline/lib/settings_web_gate.py \
         /opt/baseline/lib/settings_store.py /opt/baseline/lib/admin_elevation.py \
         /opt/baseline/lib/recovery_mode.py \
         /opt/baseline/bin/baseline-settings-web /opt/baseline/bin/baseline-settings-web-gate \
         /opt/baseline/lib/vm_scripts.py /opt/baseline/lib/quadlet.py \
         /opt/baseline/lib/vm_provision.py /opt/baseline/lib/pct_provision.py \
         /opt/baseline/lib/harness.py /opt/baseline/lib/stream_json.py \
         /opt/baseline/lib/harness_adapter.py /opt/baseline/lib/harness_registry.py /opt/baseline/lib/harness_events.py \
         /opt/baseline/lib/clipboard_osc52.py /opt/baseline/lib/status_bar.py \
         /opt/baseline/lib/config_apply.py /opt/baseline/lib/config_pipeline.py \
         /opt/baseline/lib/persist_bind_mounts.py /opt/baseline/bin/baseline-persist-bind-mounts \
         /opt/baseline/lib/physical_device_safety.py /opt/baseline/lib/drive_installer.py \
         /opt/baseline/lib/config_diff.py /opt/baseline/lib/update_pipeline.py \
         /opt/baseline/lib/backup_restore.py /opt/baseline/lib/config_crypto.py \
         /opt/baseline/lib/control_panel_web.py /opt/baseline/lib/iso_builder.py \
         /opt/baseline/lib/scripts_inbox.py /opt/baseline/lib/scripts_inbox_web.py /opt/baseline/lib/scripts_inbox_gate.py \
         /opt/baseline/lib/sensors_interval_control.py \
         /opt/baseline/lib/backup_recurring.py /opt/baseline/bin/baseline-backup-recurring \
         /opt/baseline/lib/recovery_mode.py /opt/baseline/bin/baseline-recovery-mode \
         /opt/baseline/lib/drive_admin.py /opt/baseline/lib/baseline_web.py /opt/baseline/bin/baseline-web \
         /opt/baseline/bin/baseline-diff /opt/baseline/bin/baseline-update \
         /opt/baseline/bin/baseline-backup /opt/baseline/bin/baseline-config-crypto \
         /opt/baseline/bin/baseline-control-panel /opt/baseline/bin/baseline-build-iso \
         /opt/baseline/bin/baseline-scripts-inbox /opt/baseline/bin/baseline-scripts-inbox-gate \
         /opt/baseline/bin/baseline-sensors-set-interval; do
    [ -s "$f" ] || verify_fail "missing or empty staged file: $f"
done
command -v podman >/dev/null 2>&1 || verify_fail "podman not found on PATH after install"
[ -d /etc/containers/systemd ] || verify_fail "missing /etc/containers/systemd (Quadlet unit directory)"
for u in baseline.service baseline-additive-dhcp-reapply.service baseline-firstboot.service \
         baseline-sensors-collect.service baseline-sensors-collect.timer baseline-kiosk.service \
         baseline-web.service baseline-scripts-inbox.service \
         baseline-backup-recurring.service baseline-backup-recurring.timer; do
    [ -s "/etc/systemd/system/$u" ] || verify_fail "missing staged unit: $u"
done
for f in /opt/baseline/bin/baseline /opt/baseline/bin/baseline-firstboot \
         /opt/baseline/bin/baseline-repair-rollback /opt/baseline/bin/baseline-additive-dhcp-reapply \
         /opt/baseline/bin/baseline-sensors-collect /opt/baseline/bin/baseline-kiosk-gate \
         /opt/baseline/bin/baseline-settings-web /opt/baseline/bin/baseline-settings-web-gate \
         /opt/baseline/bin/baseline-persist-bind-mounts \
         /opt/baseline/bin/baseline-diff /opt/baseline/bin/baseline-update \
         /opt/baseline/bin/baseline-backup /opt/baseline/bin/baseline-config-crypto \
         /opt/baseline/bin/baseline-control-panel /opt/baseline/bin/baseline-build-iso \
         /opt/baseline/bin/baseline-scripts-inbox /opt/baseline/bin/baseline-scripts-inbox-gate \
         /opt/baseline/bin/baseline-sensors-set-interval /opt/baseline/bin/baseline-backup-recurring \
         /opt/baseline/bin/baseline-recovery-mode /opt/baseline/bin/baseline-web; do
    [ -x "$f" ] || verify_fail "staged entry point not executable: $f"
done
echo "PASS: all staged files and units present and correctly permissioned."

echo "=== Enabling units for next boot (no --now, no getty changes - nothing here touches this session's tty) ==="
systemctl daemon-reload
systemctl enable baseline-persist-bind-mounts.service
systemctl enable baseline-firstboot.service
systemctl enable baseline.service
systemctl enable baseline-additive-dhcp-reapply.service
systemctl enable baseline-sensors-collect.timer
systemctl enable baseline-kiosk.service
systemctl enable baseline-web.service
systemctl enable baseline-scripts-inbox.service
systemctl enable baseline-backup-recurring.timer

for u in baseline-persist-bind-mounts.service baseline-firstboot.service baseline.service baseline-additive-dhcp-reapply.service baseline-sensors-collect.timer baseline-kiosk.service baseline-web.service baseline-scripts-inbox.service baseline-backup-recurring.timer; do
    [ "$(systemctl is-enabled "$u")" = "enabled" ] || verify_fail "unit did not report enabled after systemctl enable: $u"
done
echo "PASS: all eight units confirmed enabled."

echo
echo "Done. Nothing on this tty/session was touched or disabled - this"
echo "shell keeps running exactly as it was. baseline-firstboot.service"
echo "will take over tty1 automatically on the NEXT boot (via its own"
echo "Conflicts=getty@tty1.service ordering), present the integrated"
echo "first-boot authorization screen, and hand off to baseline.service"
echo "once committed. Reboot when ready:"
echo "  reboot"
echo
echo "Run the setup wizard yourself (it's interactive - a form with"
echo "sensible defaults, and it can restore identity/state from a"
echo "previous build's encrypted handoff packet instead of starting"
echo "from scratch):"
echo "  /opt/baseline/bin/baseline-setup-wizard"
echo "If you skip it or aren't restoring a token, run"
echo "  /opt/baseline/bin/baseline-auth-setup.sh"
echo "yourself afterward (it needs your own interactive login) to connect an AI account."
