# Decision record 176: PC601 UEFI portability preflight

Date: 2026-10-09
Status: read-only preflight complete; second-machine native boot remains open.

## Result

The selected disk remains PC601, serial `FD01N6557110C271B`. Its EFI
partition was available at `/mnt/sdb2` and `findmnt` reported it mounted
read-only. The mounted EFI files included:

- `EFI/BOOT/BOOTx64.efi` (1,032,032 bytes), recognized by `file` as an
  x86-64 PE32+ EFI application; SHA256
  `9dee7152ef3b7acbe621fcff45ed96b589282ab2ff623dd4ebc776ff605fcb37`.
- `EFI/proxmox/grubx64.efi` (2,685,544 bytes), recognized as an x86-64
  PE32+ EFI application; SHA256
  `95ddb4cb4656445c89b3f8648f795cdd581420822ace1a960661f376c009898a`.
- `EFI/proxmox/grub.cfg` points GRUB at root filesystem UUID
  `fa48739d-a429-4ac2-a2d5-7a6ab0883046`, matching the PC601 `pve-root`
  UUID in read-only physical inventory evidence `docs/verification/143`.

These files establish a usable UEFI fallback path and a matching Proxmox GRUB
root reference. They make the disk ready for a controlled boot attempt on
another x86-64 UEFI machine without depending on the current machine's saved
UEFI boot entry. No disk writes or configuration changes occurred in this
preflight. The EFI partition is still mounted read-only on the current host;
it must be cleanly unmounted and the device safely disconnected before moving
it. Do not power off a shared enclosure if that would disconnect PC401 too.
The unmount was attempted normally and failed with `must be superuser to
unmount`; the requested privileged `pkexec /usr/bin/umount /mnt/sdb2` did not
run because its approval call returned `aborted`. The EFI mount remains in
place. No alternate privilege path was used.

Decision record 117 separately documents a real QEMU/KVM boot of a clone whose
raw backing source was this PC601 disk opened read-only, with all writes in a
disposable overlay. Decision record 04 demonstrates fresh OVMF NVRAM portability
for a different disk image, not PC601. Neither substitutes for booting PC601
from its own controller on the actual second machine.

## Controlled second-machine test

1. On the current host, unmount `/mnt/sdb2` normally and use the supported
   device-removal flow after confirming the whole device still maps to serial
   `FD01N6557110C271B`. Avoid commands based on a remembered `/dev/sdX` name.
2. Install PC601 in the second machine with power off. Use UEFI mode and its
   one-time boot menu to select the PC601 NVMe. Leave that machine's other
   disks untouched. Do not change its boot order permanently or run an
   installer against PC601.
3. Record whether it reaches the local Proxmox login prompt. Then verify the
   machine's actual LAN address, HTTPS Proxmox GUI from a separate browser,
   internet reachability, and host firewall state. Record failures as failures;
   do not infer these from a login prompt.
4. Shut Proxmox down normally before any further storage movement. Preserve
   the current data and report the second machine's model, firmware mode,
   storage controller, NIC, and observations with the result.

Until those steps are performed, physical second-machine boot, GUI, network,
firewall, workloads, drivers, and persistence remain unverified. This does not
close queue items 72/73/74/75/76/78 or alter the selected-drive decision DR174.
