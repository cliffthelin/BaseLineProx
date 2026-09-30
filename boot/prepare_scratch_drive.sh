#!/usr/bin/env bash
# Partition the ONE approved scratch drive for the hardened-appliance work
# (docs/design/hardened-appliance-prd.md, section 11). Dry-run by default.
#   p1  200G  raw    Proxmox rehearsal disk (QEMU target, never a real install)
#   p2  100G  LUKS2  scratch volume for systemd-cryptenroll / PCR tests (H5)
#   p3  rest  ext4   scratch data
# Refuses any device except the pinned by-id serial below.
set -euo pipefail

# DISABLED 2026-09-30. This script invented its own layout and bypassed
# physical_device_safety / drive_installer (decision record 49 forbids ad hoc
# destructive commands). Baseline's real volumes are defined in
# baseline/lib/drive_installer.py (SHARED_VOLUMES, persona volumes). Use that.
echo "REFUSING: superseded; see decision record 49 and drive_installer.py" >&2
exit 1

DEV=/dev/sdd
SERIAL_ID=/dev/disk/by-id/ata-PC401_NVMe_SK_hynix_512GB_MD89N41071210AP4E
MIN_BYTES=$((400 * 1024**3)); MAX_BYTES=$((600 * 1024**3))
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1

die() { echo "REFUSING: $*" >&2; exit 1; }

[[ "$(readlink -f "$SERIAL_ID" 2>/dev/null)" == "$DEV" ]] || die "$DEV is not the pinned drive ($SERIAL_ID)"
bytes=$(blockdev --getsize64 "$DEV")
(( bytes >= MIN_BYTES && bytes <= MAX_BYTES )) || die "unexpected size $bytes"
[[ "$(lsblk -dno TRAN "$DEV")" == "usb" ]] || die "not a USB-attached drive"
if lsblk -nro MOUNTPOINTS "$DEV" | grep -q .; then die "$DEV has mounted partitions"; fi
root_src=$(findmnt -no SOURCE /); [[ "$root_src" != "$DEV"* ]] || die "$DEV holds the root filesystem"

echo "Target: $DEV ($((bytes / 1024**3)) GiB), current contents:"; lsblk -o NAME,SIZE,FSTYPE,LABEL "$DEV"
echo "Plan: wipe, GPT; p1 200G rehearsal, p2 100G LUKS2 scratch, p3 remainder ext4"
(( APPLY )) || { echo "Dry run only. Re-run with sudo and --apply to erase $DEV."; exit 0; }
[[ -w "$DEV" ]] || die "--apply needs write access to $DEV (root or disk group)"

wipefs -a "$DEV"
sgdisk --zap-all "$DEV"
sgdisk -n1:0:+200G -t1:8300 -c1:proxmox-rehearsal \
       -n2:0:+100G -t2:8309 -c2:luks-scratch \
       -n3:0:0     -t3:8300 -c3:scratch-data "$DEV"
# Re-reading the table needs root; the disk-group path cannot, and that is fine.
if partprobe "$DEV" 2>/dev/null && udevadm settle && [[ -b "${DEV}3" ]]; then
    mkfs.ext4 -q -L scratch-data "${DEV}3"
else
    echo "Kernel did not re-read the table (needs root). Formatting p3 via its byte offset instead."
    start=$(sgdisk -i3 "$DEV" | awk '/First sector/ {print $3}')
    end=$(sgdisk -i3 "$DEV" | awk '/Last sector/ {print $3}')
    mkfs.ext4 -q -L scratch-data -E offset=$((start * 512)) "$DEV" "$(( (end - start + 1) / 2 ))k"
fi
echo "Done. p2 is left unformatted: run cryptsetup luksFormat ${DEV}2 yourself when testing H5."
