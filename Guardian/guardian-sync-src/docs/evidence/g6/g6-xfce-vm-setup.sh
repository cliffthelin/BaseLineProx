#!/bin/bash
# Reproducible setup for the G6 Xfce 4.20 evidence spike, run against a
# disposable Ubuntu 26.04.1 cloud-image VM only -- never on a primary
# development workstation (AGENTS.md; G6 handoff §10/§13).
#
# Sibling of g6-gnome-vm-setup.sh -- reuses the same base cloud image, a
# separate overlay/port/QMP socket so both can (in principle) run
# concurrently. Produces the screenshots/logs in
# docs/evidence/g6/xfce420-ksni/ (see G6_XFCE_KSNI_SPIKE_EVIDENCE.md).
#
# Usage:
#   bash docs/evidence/g6/g6-xfce-vm-setup.sh
set -euxo pipefail

WORKDIR=/tmp/g6-evidence-vm-xfce
GNOME_WORKDIR=/tmp/g6-evidence-vm  # reuse its base image if present

mkdir -p "$WORKDIR/seed"
cd "$WORKDIR"

if [ ! -f ubuntu-26.04-server-cloudimg-amd64.img ]; then
  if [ -f "$GNOME_WORKDIR/ubuntu-26.04-server-cloudimg-amd64.img" ]; then
    cp "$GNOME_WORKDIR/ubuntu-26.04-server-cloudimg-amd64.img" .
  else
    curl -sL -o ubuntu-26.04-server-cloudimg-amd64.img \
      https://cloud-images.ubuntu.com/releases/26.04/release/ubuntu-26.04-server-cloudimg-amd64.img
  fi
fi

[ -f vm_key ] || ssh-keygen -t ed25519 -f vm_key -N "" -C "g6-evidence-vm-xfce"

cat > seed/meta-data <<'EOF'
instance-id: g6-evidence-vm-xfce-01
local-hostname: g6-evidence-vm-xfce
EOF
PUBKEY="$(cat vm_key.pub)"
cat > seed/user-data <<EOF
#cloud-config
hostname: g6-evidence-vm-xfce
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - $PUBKEY
package_update: true
packages:
  - openssh-server
runcmd:
  - systemctl enable ssh
  - systemctl start ssh
EOF
xorriso -as genisoimage -output seed.iso -volid cidata -joliet -rock \
  seed/user-data seed/meta-data

qemu-img create -f qcow2 -F qcow2 -b ubuntu-26.04-server-cloudimg-amd64.img \
  vm-disk.qcow2 20G

# Distinct hostfwd port (2223), VNC display (:6), and QMP/monitor sockets
# from the GNOME setup script so both VMs can run side by side without
# collision.
qemu-system-x86_64 \
  -name g6-evidence-vm-xfce \
  -machine q35,accel=kvm:tcg \
  -cpu max -m 4096 -smp 2 \
  -drive file=vm-disk.qcow2,if=virtio,format=qcow2 \
  -drive file=seed.iso,if=virtio,format=raw,readonly=on \
  -netdev user,id=net0,hostfwd=tcp::2223-:22 \
  -device virtio-net-pci,netdev=net0 \
  -vga std -display none -vnc :6 \
  -qmp unix:"$WORKDIR"/qmp.sock,server,nowait \
  -monitor unix:"$WORKDIR"/monitor.sock,server,nowait \
  -serial file:"$WORKDIR"/serial.log \
  > qemu.log 2>&1 &
echo $! > qemu.pid

for i in $(seq 1 24); do
  ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o ConnectTimeout=3 -i vm_key -p 2223 ubuntu@localhost \
      "cloud-init status --wait" && break
  sleep 10
done

SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i $WORKDIR/vm_key -p 2223 ubuntu@localhost"

# --- real Xfce 4.20 desktop; verify with `dpkg -l xfce4-session` (must
#     report 4.20.x) ---
$SSH "sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq"
$SSH "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  xfce4 xfce4-session lightdm lightdm-gtk-greeter xfce4-terminal \
  dbus-x11 policykit-1-gnome network-manager"
$SSH "dpkg -l xfce4-session | tail -1"   # must show version 4.20.x

# --- autologin: lightdm's own conf.d snippet mechanism (simpler than
#     GDM's custom.conf-vs-daemon.conf split found on the GNOME run) ---
$SSH "sudo mkdir -p /etc/lightdm/lightdm.conf.d && sudo tee /etc/lightdm/lightdm.conf.d/50-autologin.conf > /dev/null << 'EOF'
[Seat:*]
autologin-user=ubuntu
autologin-user-timeout=0
autologin-session=xfce
EOF"
$SSH "sudo systemctl set-default graphical.target && sudo systemctl enable lightdm && sudo systemctl start lightdm"
sleep 15

# --- StatusNotifierItem support: NOT present in the default xfce4
#     panel layout (only the legacy XEmbed 'systray' plugin is) -- see
#     G6_XFCE_KSNI_SPIKE_EVIDENCE.md for what this looks like without
#     the plugin below. ---
$SSH "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  xfce4-indicator-plugin libayatana-appindicator3-1"
$SSH "export DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus XAUTHORITY=/home/ubuntu/.Xauthority
xfconf-query -c xfce4-panel -p /plugins/plugin-11 -n -t string -s indicator
xfconf-query -c xfce4-panel -p /panels/panel-1/plugin-ids -n -a \
  -t int -s 1 -t int -s 2 -t int -s 3 -t int -s 4 -t int -s 5 \
  -t int -s 6 -t int -s 7 -t int -s 8 -t int -s 9 -t int -s 10 -t int -s 11
xfce4-panel -r"

# --- Rust toolchain, for building candidate prototypes on-VM ---
$SSH "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  cargo rustc pkg-config libdbus-1-dev libgtk-3-dev"

echo "VM ready. SSH: \$SSH"
echo "TEARDOWN when done:"
echo "  1. revert plugin-ids to the 10-item baseline (drop the appended 11) + xfce4-panel -r"
echo "  2. kill \$(cat $WORKDIR/qemu.pid) via QMP 'quit'"
echo "  3. rm -f $WORKDIR/vm-disk.qcow2"
