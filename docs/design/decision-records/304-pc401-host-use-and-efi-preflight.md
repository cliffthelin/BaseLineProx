# DR304: PC401 host-use and EFI preflight

**Date:** 2026-10-11  
**Status:** safe to disconnect for native test; native boot unverified

## Host-use checks

PC401 was resolved afresh by serial `<PC401 drive serial>` to the whole disk for
this observation. Its partition tree showed no mounted filesystems. Its LVM PV
had an empty sysfs `holders` directory; the host had no `/sys/class/block/dm-*`
devices; no readable process mount namespace referenced the PC401 VG or mapped
LVs; and `fuser` reported no process using the whole disk or PV. These
read-only observations show no current host mapping or process use of PC401's
storage.

`sudo -n lvs --readonly --reportformat json --devices <PC401-PV>` listed the
expected VG/LV metadata but reported `lv_attr` state/open positions as `XX`.
That LVM activity field is unknown, not an inactive result. The no-use
conclusion is supported by the independent live kernel mapping, mount, holder
and process checks above. No activation, deactivation, mount, unmount or write
was performed. PC401 is ready to disconnect from this development host for
native testing. Do not repeat raw-backed QEMU attachment.

## EFI preflight

The EFI System Partition was resolved through the same serial-specific `lsblk`
inventory and read without mounting. GPT places it at LBA 2048, and the FAT
BPB hidden-sector field is also 2048. `mdir` listed
`EFI/BOOT/BOOTX64.EFI` and `EFI/BOOT/GRUBX64.EFI`; `fsck.fat -n` exited 0 with
no reported errors. The `mdir` CHS geometry warning is consistent with the
partition's 2048-sector offset and the tool's legacy 63-sector geometry; it is
not a FAT consistency error. No filesystem repair was performed.

These observations do not prove that the target machine's firmware accepts the
drive, that Proxmox boots natively, or that GUI, network, firewall, workloads
and persistence work. Continue those checks in the ordered checklist in
`docs/INSTALL.md`.
