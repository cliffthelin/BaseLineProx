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
chmod +x /opt/baseline/bin/baseline /opt/baseline/bin/baseline-auth-setup.sh /opt/baseline/bin/baseline-setup-wizard /opt/baseline/bin/baseline-repair-rollback /opt/baseline/bin/baseline-additive-dhcp-reapply /opt/baseline/bin/baseline-firstboot

echo "=== Installing systemd unit (Baseline takes over tty1) ==="
cp "$SRC/boot/baseline.service" /etc/systemd/system/baseline.service

echo "=== Installing systemd unit (additive-repair DHCP reapply, decision record 17) ==="
cp "$SRC/boot/baseline-additive-dhcp-reapply.service" /etc/systemd/system/baseline-additive-dhcp-reapply.service

echo "=== Installing systemd unit (first-boot network-repair authorization, Gate E) ==="
cp "$SRC/boot/baseline-firstboot.service" /etc/systemd/system/baseline-firstboot.service

systemctl daemon-reload
systemctl disable --now getty@tty1.service
systemctl enable baseline-firstboot.service
systemctl enable --now baseline.service
systemctl enable baseline-additive-dhcp-reapply.service

echo "=== Installing the Proxmox<->BaselineOS return command ==="
# The (p) key inside Baseline switches tty1 -> tty2 (a real Proxmox
# login console); this installs the 'baseline' shell command that
# switches back, so the round trip works both directions.
cp "$SRC/boot/baseline-return.sh" /etc/profile.d/baseline-return.sh

echo "=== Verifying tty1 console font ==="
bash "$SRC/tests/console_font_check.sh"

echo
echo "Done. Baseline owns tty1. Run the setup wizard yourself (it's"
echo "interactive - a form with sensible defaults, and it can restore"
echo "identity/state from a previous build's encrypted handoff packet"
echo "instead of starting from scratch):"
echo "  /opt/baseline/bin/baseline-setup-wizard"
echo "If you skip it or aren't restoring a token, run"
echo "  /opt/baseline/bin/baseline-auth-setup.sh"
echo "yourself afterward (it needs your own interactive login) to connect an AI account."
