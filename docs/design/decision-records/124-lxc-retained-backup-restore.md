# DR124 — Stopped LXC retained-data backup and new-container restore

Date: 2026-10-02. Accepted. Narrows DR118/120/123 retained-backup gaps.

## Implemented workflow

Authenticated admin Container actions submit durable backup/restore jobs. Backup
requires a ready, cleanly stopped managed container. A mounted, serial-validated
separate local disk is required; the running boot disk, managed SK Hynix disks,
and any disk backing retained data are refused. Runtime block names are used
only for current ancestry comparison, never stored as persistent identity.

GNU tar archives /home, /root and /data with numeric ownership, modes, links,
POSIX ACLs and user xattrs. Nested mounts, special files and unsupported attribute
namespaces are refused. Safe member validation, SHA256 and destination identity
recheck precede the complete manifest. Each set is exclusive and add-only;
Baseline never deletes backup files. Failed sets remain incomplete. The manifest
explicitly excludes OS packages, /etc, immutable base/downloads and login hash.

The backup page shows coverage before restore. Restore requires explicit
confirmation, a new unused name, an unchanged same-host native immutable base,
valid archive checksum/member paths and enough unpacked-data space. It extracts
into new retained directories, allocates a new native ID, clones/configures/boots
via the established Proxmox adapter, and applies a fresh one-time login. Existing
resources and original retained data are preserved. Native errors leave an
incomplete reservation for inspection; automated incomplete-restore repair is
not implemented. No AI runtime is required. Provision staging includes the new
module. These are not full guest backups or application sandbox enforcement.

## Verification

TDD RED preceded implementation for archive/restore, UI, space, metadata,
destination continuity and source/destination disk separation. Guarded unit
coverage uses fake Proxmox/block identities plus real GNU archive/file operations;
unit tests alone do not prove native guest behavior.

Actual authenticated Baseline jobs against disposable Proxmox-in-KVM backed up
stopped Alpine retained data and restored two new native containers. Running
restores read all three retained areas; customized /etc was absent as declared.
Numeric ownership, modes, symlink, user xattr and POSIX ACL were preserved. Fresh
native login hash matched the new generated value and differed from the original.
Original data, earlier backup archive and unrelated backup-disk file stayed intact.
One-time result retrieval and completed jobs survived web service restart.
The final ancestry guard also passed a read-only native check.

Destination was a separately attached 256MiB ext4 USB virtual disk, serial
BASELINE_BACKUP124. It proves separate virtual devices, not separate physical
failure domains. Physical source backing remained read-only; writes stayed in
approved disposable overlays/images. No physical drive writes/deployment, real
physical off-drive recovery, ordinary-network firstboot, cross-host migration or
power-loss recovery were verified. No operator credentials or private keys are
published. Evidence: docs/verification/124.

## Open work and continuity

Rows59/60 remain partial for full VM/split-store recovery, live-volume safeguards,
recurring/encrypted retained sets and physical off-drive proof. Row73 now has
stopped bind-data backup/restore evidence for Alpine only; requested systems and
physical deployment remain open. Row75 includes incomplete-restore recovery;
row74 application lifecycle and applied isolation remains open. INSTALL, queue,
functional audit and handoff are updated in place. Earlier decision records and
verification artifacts remain historical; their original evidence is unchanged.

Final guarded unit suite: **2,905 passed in 133.73s**. Provision import staging
check and git diff whitespace check passed. Unit Proxmox/drive identities are
fakes; the separate native evidence above is actual disposable KVM execution.
