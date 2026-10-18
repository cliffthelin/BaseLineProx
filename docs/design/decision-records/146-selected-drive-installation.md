# DR146 — Selected independent drive installation and verified recovery

Date: 2026-10-04. Status: in progress. Continues DR145 / REAL-013.

The user directs installation onto one of the two connected 512 GB SK hynix
drives. Select PC401 `<PC401 drive serial>`; preserve PC601
`<PC601 drive serial>`. Identical role layout does not imply cloned UUIDs.

## Physical evidence so far

The selected drive is 512110190592 bytes. Its six existing Baseline ext4
filesystems were normally unmounted after root process-use inspection.
The add-only whole-drive image at
`/mnt/10TB/backup/baseline-recovery-20261004T095423Z-e228c4285b1047958cccbb164ec9ec6d`
passed image checks, comparison of the entire raw source and independent
checksum verification. Image bytes: 7975665664. SHA-256:
`2d3b319931691b1423bafe2c5f8ca091eb5dca96a96fde0ae013c86bd0a4919a`.
Read-only physical filesystem inspection (`ro,noload`) found role index files,
Baseline source/design files and `seed/baseline-seed.tar.gz`; these are backed up,
not assumed absent.

The GPT identity predates the installer registry and its data-protection gate
correctly refuses formatting. The existing `stamp_installer_identity` adoption
operation is allowed only for entirely Baseline-owned partitions; it is the
established path, not a formatting override. It must follow target validation
and verified recovery. It stamped/registered GUID
`a40a7971-2f3a-4cc1-972b-5c57bac8d29f` before installation. No gate was disabled.

The first QEMU launch failed during GTK initialization before installation.
A confirmed failing test preceded the headless-monitor fix; 50 installer
regression tests passed outside the socket-restricted sandbox. The subsequent
HTTP-answer installation wrote PC401 and rebooted into `baseline-pc401 login:`.
The guest had only that physical drive attached. This verifies installed
physical storage booting under QEMU, not native machine cold boot. Workspace:
`.runtime-proof146/physical-pc401-20261004T104710Z` (private generated TLS key;
excluded from version control). PC601 was never an installation target.

## Implementation evidence and remaining work

Actual physical continuation: PC401 VG was renamed by UUID to
`baseline_1b75c1a556ee`; PC601 remains `pve`. PC401 PV UUID is
`PtJxk3-3YnM-AnWA-fsJQ-MbDy-TJOB-yiCyM8`; VG UUID is
`Okyyas-6SZq-tSzV-trFO-K5RW-hmXQ-TWPyAE`. Real root/swap are 32/4 GiB.
The initial host gate refused its real 66567798784-byte thin data pool.
Upstream [Proxmox Install.pm](https://github.com/proxmox/pve-installer/blob/master/Proxmox/Install.pm)
deducts two metadata allocations and one 4-MiB extent from maxvz; the gate
was corrected to that physical formula, without expanding over reserved space.
Subsequent real provisioning created BASELINE 8 GiB, INSTALLER_CACHE 62 GiB,
SESSION_TEMP 8 GiB, SUBSTRATE 1 GiB, USER_ADMIN/PERSONAL 62 GiB each and
APPDATA_ADMIN/PERSONAL 35 GiB each. UUID mounts and policy were persisted.
Initramfs and GRUB were regenerated. Real package deployment installed
diagnostics, Chromium/Cage, Podman, Node22 and Claude Code, then stopped at
missing source automation assets. The consolidated script corrects staging and
adds retained-file restoration with real checksum checks plus physical-disk
QEMU/SSH verification. Those later stages are not yet demonstrated. Its latest
privileged invocation is still waiting at the local privilege broker.
The consolidated script handles already-completed recovery/installation by
inspection and never repeats the earlier format operation. Generated temporary
verification keys are excluded from git and revoked after successful proof.

Real-command provisioning now binds a measured policy to root/PV/VG/filesystem
identities, refuses malformed inventories and mount failures, persists UUID-based
fstab and a policy, and stages a firstboot verification service. These paths are
unit-tested with fakes, not physically provisioned or boot-verified yet.
The recovery helper additionally passed an actual regular-image integration
test. The QEMU answer server now binds only loopback, reachable through its
single named guest-forward rule; a failing unit test preceded that fix.

Independent cold boots, duplicate-VG isolation, restoration/migration and
complete provisioning remain on the living checklist. Disposable QEMU proof
attempt failed to create its monitor socket in the sandbox; no disposable boot
or physical verification is claimed from it. Historical records remain intact;
INSTALL is updated in place to distinguish the new recovery evidence from
DR143's earlier read-only inspection.

## 2026-10-04 status correction

The continuation completed on real PC401: Baseline deployment and enabled
units were staged successfully, the vanilla source ISO was checksum-compared,
and 22 original files were restored with per-file SHA-256 verification. The
script now uses a private mount namespace for future runs and offers a
boot-only resume. Post-rename QEMU/SSH verification remains blocked: LVM reports
the PC401 root LV open and `/proc/*/mountinfo` places it under the host
`systemd-oomd` namespace. Attempts to normally unmount the recorded paths report
that they are not mountpoints from the invoked utility; no force or lazy unmount
was used. Thus no post-rename boot or native cold boot is claimed. PC601 remains
untouched. See the current checklist and INSTALL status.

UDisks status was then checked against both live drive serials. PC401 and PC601
have the same USB `SiblingId` (Realtek RTL9220DP bridge). A serial-validated
UDisks safe-power-off request for PC401 was refused because PC601's `/dev/sdc2`
was mounted. No power-off occurred. The GUI action therefore controls a shared
USB device in this setup, not just one SK hynix module; do not use it to
power-cycle only PC401. PC601's existing mounted EFI volume is preserved.

2026-10-04 continuation: the single-drive script now enters the reported
`systemd-oomd` mount namespace with `nsenter` before issuing normal unmounts.
The physical retry still found PC401 root mounted and stopped before LVM
deactivation or QEMU boot. No power-off or disconnect occurred. The alternate
command path is unit-tested only; physical boot verification remains open.

Later that day, the user confirmed neither drive was in active use. GNOME
Disks displayed both members of the shared enclosure and failed opening PC401
`/dev/sdd` for `fsync` because it was busy. The script retried normal unmounts
across the observed mount namespaces, including entering each namespace root;
PC401 root remained mounted. No LVM deactivation, power-off or boot occurred.

Read-only diagnosis found nine stacked PC401 root mounts across 23 mount
namespaces. Their mountinfo records list `/tmp/baseline-pc401-target`, while
`stat` of that path from the helper and representative process roots returns
`ENOENT`; `umount2` consequently cannot resolve a target. The recovery image
and serial/LVM identity still verify. No forced/lazy unmount, LV deactivation,
host restart, or enclosure power-off occurred. Post-rename boot remains open.
