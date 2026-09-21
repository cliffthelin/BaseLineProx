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
chmod +x /opt/baseline/bin/baseline /opt/baseline/bin/baseline-auth-setup.sh /opt/baseline/bin/baseline-setup-wizard

echo "=== Installing systemd unit (Baseline takes over tty1) ==="
cp "$SRC/boot/baseline.service" /etc/systemd/system/baseline.service
systemctl daemon-reload
systemctl disable --now getty@tty1.service
systemctl enable --now baseline.service

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
