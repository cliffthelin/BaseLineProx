# PC601 UEFI portability preflight

Observed 2026-10-09 against the current mounted EFI partition, selected by
the host inventory as PC601 serial `<PC601 drive serial>` (historically `/dev/sdb`;
the name is not a persistent identity).

- `findmnt -no SOURCE,TARGET,OPTIONS /mnt/sdb2` reported `/dev/sdb2`,
  `/mnt/sdb2`, and `ro,nosuid,nodev,...`.
- `EFI/BOOT/BOOTx64.efi` exists and is an x86-64 EFI PE32+ application,
  1,032,032 bytes, SHA256
  `9dee7152ef3b7acbe621fcff45ed96b589282ab2ff623dd4ebc776ff605fcb37`.
- `EFI/proxmox/grubx64.efi` exists and is an x86-64 EFI PE32+ application,
  2,685,544 bytes, SHA256
  `95ddb4cb4656445c89b3f8648f795cdd581420822ace1a960661f376c009898a`.
- `EFI/proxmox/grub.cfg` searches for UUID
  `fa48739d-a429-4ac2-a2d5-7a6ab0883046`; read-only inventory in
  `../143/physical-metadata.json` identifies this as the PC601 `pve-root`
  filesystem UUID.

No disk writes occurred. This is a physical read-only boot-file preflight,
not an executed boot. DR117 records a real QEMU/KVM boot using a read-only
PC601 raw source and disposable overlay. No second-machine hardware was
available to this preflight, so its native boot and network path remain open.
