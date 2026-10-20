# DR181: Hardware inventory preserves unknown observations

Date: 2026-10-09

## Decision

Successful command execution without textual stdout is an `InventoryError`,
not an empty bus. PCI driver metadata read failures are kept distinct from a
successful `uevent` read that has no `DRIVER` field. The hardware page can
therefore report “driver metadata unavailable” without claiming that no driver
is bound.

## Verification and limits

Test-first regression coverage first failed on all four collectors when stdout
was absent, and showed unreadable sysfs metadata being labeled “no driver
bound.” After the correction, 61 focused inventory and truthful-runtime tests
passed. A read-only development-host probe parsed 45 PCI devices and 13 whole
block devices; all 45 PCI `uevent` reads succeeded, with 16 devices reporting
no bound driver. `lsusb` and `ip` exited with sandbox-restriction errors, so
those buses remain unknown in this environment. No Proxmox target was queried,
no drive was changed, and no physical deployment proof is claimed.
