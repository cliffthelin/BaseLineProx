#!/bin/bash
# Reproducible setup for the G6 GNOME 50 evidence spike, run against a
# disposable Ubuntu 26.04.1 cloud-image VM only -- never on a primary
# development workstation (AGENTS.md; G6 handoff §10/§13).
#
# This is the exact sequence used to produce the screenshots and logs in
# docs/evidence/g6/gnome50-ksni/ (see G6_GNOME_KSNI_SPIKE_EVIDENCE.md for
# the results these produced).
#
# Unlike G1/G2 (headless D-Bus/polkit evidence, no GUI), this VM boots a
# real graphical GNOME Shell session and is inspected via QEMU's own QMP
# `screendump` command -- no VNC client, no separate framebuffer capture
# tool required; QMP writes a real PPM screenshot of the guest's actual
# video output directly to a host file.
#
# Usage (from the host, with qemu-system-x86_64, qemu-img, xorriso,
# ssh-keygen, python3, and python3-pil available):
#   bash docs/evidence/g6/g6-gnome-vm-setup.sh
set -euxo pipefail

WORKDIR=/tmp/g6-evidence-vm
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

mkdir -p "$WORKDIR/seed"
cd "$WORKDIR"

# --- disposable base image (never written to directly -- see the qcow2
#     overlay below) ---
if [ ! -f ubuntu-26.04-server-cloudimg-amd64.img ]; then
  curl -sL -o ubuntu-26.04-server-cloudimg-amd64.img \
    https://cloud-images.ubuntu.com/releases/26.04/release/ubuntu-26.04-server-cloudimg-amd64.img
fi

# --- SSH keypair for this run only ---
[ -f vm_key ] || ssh-keygen -t ed25519 -f vm_key -N "" -C "g6-evidence-vm"

# --- cloud-init seed: creates the 'ubuntu' user with the key above,
#     enables sshd. No password auth, no secrets committed anywhere. ---
cat > seed/meta-data <<'EOF'
instance-id: g6-evidence-vm-01
local-hostname: g6-evidence-vm
EOF
PUBKEY="$(cat vm_key.pub)"
cat > seed/user-data <<EOF
#cloud-config
hostname: g6-evidence-vm
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

# --- disposable overlay disk: the base cloud image is never modified;
#     every write goes to this qcow2 overlay, which this script's
#     teardown step below deletes. ---
qemu-img create -f qcow2 -F qcow2 -b ubuntu-26.04-server-cloudimg-amd64.img \
  vm-disk.qcow2 20G

# --- boot: -vnc :5 exposes a VNC framebuffer (unused directly here, kept
#     for interactive debugging); QMP over a Unix socket is what actually
#     drives screendump/input-send-event for evidence capture. Port 2222
#     on the host forwards to the guest's SSH (hostfwd), never exposed
#     beyond localhost. ---
qemu-system-x86_64 \
  -name g6-evidence-vm \
  -machine q35,accel=kvm:tcg \
  -cpu max -m 4096 -smp 2 \
  -drive file=vm-disk.qcow2,if=virtio,format=qcow2 \
  -drive file=seed.iso,if=virtio,format=raw,readonly=on \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -vga std -display none -vnc :5 \
  -qmp unix:"$WORKDIR"/qmp.sock,server,nowait \
  -monitor unix:"$WORKDIR"/monitor.sock,server,nowait \
  -serial file:"$WORKDIR"/serial.log \
  > qemu.log 2>&1 &
echo $! > qemu.pid

# --- wait for SSH ---
for i in $(seq 1 24); do
  ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o ConnectTimeout=3 -i vm_key -p 2222 ubuntu@localhost \
      "cloud-init status --wait" && break
  sleep 10
done

SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i $WORKDIR/vm_key -p 2222 ubuntu@localhost"
SCP="scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i $WORKDIR/vm_key -P 2222"

# --- real GNOME 50 desktop: gdm3 + gnome-shell + gnome-session, matching
#     the exact candidate version the contract targets (verify with
#     `gnome-shell --version` after install -- must report "GNOME Shell
#     50.x"). ---
$SSH "sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq"
$SSH "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  gdm3 gnome-shell gnome-session gnome-terminal xterm dbus-x11 \
  policykit-1-gnome network-manager"
$SSH "gnome-shell --version"   # must print 'GNOME Shell 50.x'

# --- autologin (GDM reads /etc/gdm3/custom.conf, NOT daemon.conf --
#     confirmed empirically this pass; an ExecStartPre regenerates
#     greeter dconf defaults on every gdm3 start but does not touch
#     custom.conf, so this edit persists across restarts) ---
$SSH "sudo sed -i 's/\[daemon\]/[daemon]\nAutomaticLoginEnable=true\nAutomaticLogin=ubuntu/' /etc/gdm3/custom.conf"
$SSH "sudo systemctl restart gdm3"
sleep 15

# --- Rust toolchain, for building candidate prototypes on-VM ---
$SSH "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  cargo rustc pkg-config libdbus-1-dev libgtk-3-dev"

echo "VM ready. SSH: \$SSH   Screendump: see docs/evidence/g6/README-qmp-screendump.md"
echo "TEARDOWN when done: kill \$(cat $WORKDIR/qemu.pid) via QMP 'quit', then: rm -f $WORKDIR/vm-disk.qcow2"
