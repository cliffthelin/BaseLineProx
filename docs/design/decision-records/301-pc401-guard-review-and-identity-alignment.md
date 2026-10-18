# DR301: PC401 guard review and identifier alignment

**Date:** 2026-10-11  
**Status:** implemented in the isolated Codex checkout; physical write and boot remain unverified

## Review findings addressed

Claude's peer review identified that a failed serial probe could fall through to
an installer-UUID allowance in the shared registry, and that a partition does
not carry the parent disk's serial. The format guard now fails closed when the
serial is absent/ambiguous or the state cannot be read as one whole disk. A
partition path is refused. Destructive production paths pass the serial
returned by `physical_device_safety.validate_target_device`, which already
resolves and validates the whole block device; direct guard calls still require
an unambiguous read-only serial probe.

## Identity

This checkout pins Codex lane UUID
`5029a80d-c748-4616-aa08-99ac560f5311`. DR255's existing derivation produces
PC401 host UUID `5029a80d-d894-0a4e-1023-eb118fbb8f00`: non-hex serial
characters are skipped, and the final byte is `00` for ordinary deterministic
identities. The identifier implementation already reserves the final byte for
special handling (`00` ordinary, `01` external UUID cross-map, `02` portable).
`installer_identity.child_uuid()` delegates to this same derivation, and its
stamp operation sets/read-backs that GPT identifier. The installed-drive update
path does not write a GPT identifier; it preserves the current one.

## Verification

The Python unit suite completed with **3,940 passed and 9 subtests passed**.
It includes existing scripted unit fixtures; this is unit evidence, not live
installation evidence. A separate read-only production guard invocation on the
attached devices permitted the exact PC401 whole disk (`/dev/sdb` at this
observation), refused its partition `/dev/sdb3`, and refused PC601
(`/dev/sdc`). `lsblk` independently showed PC401's GPT identifier already
matches the derived UUID. No physical disk was written.

Read-only `pvs`/`vgs` inspection could not acquire `/run/lock/lvm/P_global`
as the unprivileged user. Empty visible holder and mount-namespace checks do
not establish that PC401's VG is inactive. Do not attach its raw disk to a VM
until LVM/use-state is established through the approved application path.

## Remaining PC401 work

PC401 native boot, Proxmox GUI/API login, NIC/DHCP, internet, firewall, and VM
or container workload acceptance remain open under queue row 78 and related
rows 72/74/75/76. The prior headless guest's lack of IPv4 and HTTPS 8006 is
not resolved by this source guard change. No new QEMU was started: a separate
QEMU rehearsal was visible under the CACHE checkout and was left untouched.
