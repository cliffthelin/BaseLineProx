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
cp "$SRC/baseline/lib/firstboot_statemachine.py" /opt/baseline/lib/firstboot_statemachine.py
cp "$SRC/baseline/bin/baseline-firstboot" /opt/baseline/bin/baseline-firstboot
# Physical Phase P0: read-only current-drive inventory collector, ported
# from cliffthelin/baseline's inventory/current-drive-manifest branch
# (docs/design/current-drive-inventory-plan.md) - never invoked by
# provision.sh or any other automated path; deployed so it is present
# for an operator to run by hand (`baseline-drive-inventory collect`)
# on demand. Collects only; never repairs, reconfigures, or restarts
# anything.
cp -r "$SRC/baseline/lib/inventory" /opt/baseline/lib/inventory
cp "$SRC/baseline/bin/baseline-drive-inventory" /opt/baseline/bin/baseline-drive-inventory
chmod +x /opt/baseline/bin/baseline /opt/baseline/bin/baseline-auth-setup.sh /opt/baseline/bin/baseline-setup-wizard /opt/baseline/bin/baseline-repair-rollback /opt/baseline/bin/baseline-additive-dhcp-reapply /opt/baseline/bin/baseline-firstboot /opt/baseline/bin/baseline-drive-inventory

echo "=== Staging systemd units (not yet activated - see verification/activation below) ==="
cp "$SRC/boot/baseline.service" /etc/systemd/system/baseline.service
cp "$SRC/boot/baseline-additive-dhcp-reapply.service" /etc/systemd/system/baseline-additive-dhcp-reapply.service
cp "$SRC/boot/baseline-firstboot.service" /etc/systemd/system/baseline-firstboot.service

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
         /opt/baseline/lib/firstboot_statemachine.py /opt/baseline/lib/firstboot_network_repair.py \
         /opt/baseline/lib/proxmox_detect.py /opt/baseline/lib/diagnostics.py /opt/baseline/lib/setup_intent.py \
         /opt/baseline/lib/repair.py /opt/baseline/lib/repair_additive.py /opt/baseline/lib/network.py; do
    [ -s "$f" ] || verify_fail "missing or empty staged file: $f"
done
for u in baseline.service baseline-additive-dhcp-reapply.service baseline-firstboot.service; do
    [ -s "/etc/systemd/system/$u" ] || verify_fail "missing staged unit: $u"
done
for f in /opt/baseline/bin/baseline /opt/baseline/bin/baseline-firstboot \
         /opt/baseline/bin/baseline-repair-rollback /opt/baseline/bin/baseline-additive-dhcp-reapply; do
    [ -x "$f" ] || verify_fail "staged entry point not executable: $f"
done
echo "PASS: all staged files and units present and correctly permissioned."

echo "=== Enabling units for next boot (no --now, no getty changes - nothing here touches this session's tty) ==="
systemctl daemon-reload
systemctl enable baseline-firstboot.service
systemctl enable baseline.service
systemctl enable baseline-additive-dhcp-reapply.service

for u in baseline-firstboot.service baseline.service baseline-additive-dhcp-reapply.service; do
    [ "$(systemctl is-enabled "$u")" = "enabled" ] || verify_fail "unit did not report enabled after systemctl enable: $u"
done
echo "PASS: all three units confirmed enabled."

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
