# Independent drive installation checklist

Living checklist for REAL-013 and installer queue 72/75/76. Each 512 GB
SK hynix drive must boot independently and use the same role policy. Disk,
filesystem and LVM identities must remain unique. A checked implementation
item is not physical verification; evidence is recorded beside each item.

- [x] Common single-drive role/host sizing and growth reserve (DR145; unit tests).
- [x] Explicit selected-serial CLI and web plan (DR145; unit/local HTTP tests).
- [x] Refuse insufficient installer target capacity before credentials (DR145; unit tests).
- [x] Validate complete measurements, identity and role mappings; persist the policy atomically (actual PC401 provisioning, DR146; later restoration must remeasure retained data).
- [ ] Reassess insufficient capacity against measured suitable alternate storage; preserve role separation.
- [ ] Implement one target-analysis action that selects Install/Build for a proven-empty target or Rebuild/Update for a recognized install, repairing missing expected components while preserving persistent data; block writes only when identity/ownership cannot be established (DR147).
- [ ] Put repeatable drive analysis, build/rebuild, verification, recovery and safe power-off behind the production web application; no routine operator/agent CLI or hand-run script workflow (v0.2 queue row78; operator instruction 2026-10-04).
- [~] Host restart through the web application requests the native Ubuntu confirmation dialog (DR148; software/HTTP tests pass; actual dialog and restart pending).
- [x] Bind provisioning to the actual root disk serial and its sole physical VG backing device (actual PC401 provisioning, DR146).
- [x] Fail closed on ambiguous/malformed LVM inventory and interrupted volume creation; never reformat existing data (code checks; PC401 initial provisioning real, interrupted physical retry still pending).
- [x] Connect firstboot storage verification to the persisted policy; service installed and enabled on PC401. Successful boot execution remains pending.
- [x] Isolate PC401 LVM identity by serial and VG UUID; PC601 retains its existing unique identity (actual rename DR146; post-rename boot pending).
- [x] Inventory and quiesce PC401; produce independently verified recovery image (whole raw source comparison, image check and SHA-256, DR146). PC601 remains untouched.
- [x] Implement resumable restoration with integrity checks; 22 PC401 files restored and hashed. Post-reboot persistence remains open.
- [ ] Exercise missing/unknown capacity, undersized/thin targets and interrupted migration in tests.
- [ ] Exercise installation, provisioning, migration, OS rebuild and independent boots in disposable QEMU.
- [ ] PC601 conversion is not the current write target; preserve it while finishing PC401.
- [ ] Finish PC401 conversion: Proxmox installation/disk boot, unique VG, eight physical roles, Baseline deployment and restoration/checksum of all 22 retained files are done. Post-rename boot verification remains blocked by PC401's root LV mount in the host `systemd-oomd` namespace. UDisks safe power-off was refused because PC601's EFI partition is mounted; both drives share one USB bridge, so the power-off button does not isolate PC401.
- [ ] Verify each physical drive boots with the other absent; verify both attached without identity conflicts.
- [ ] Verify vanilla sources, disposable OS rebuild and retained user/application data on each target.
- [ ] Run required regression/documentation checks and update INSTALL, REAL-013, queue and decision record with evidence.

No physical changes occurred in DR145. DR146 actually installed Proxmox on
PC401, booted it under QEMU, renamed its VG and provisioned all eight roles.
The consolidated `baseline/bin/baseline-independent-drive-install` resumes
completed stages by real inspection, including a boot-only mode. PC401's
recovery, role identities, Baseline deployment and 22-file restoration have
been reverified against the physical target. Post-rename boot verification is
still blocked: the target root LV appears in the host `systemd-oomd` mount
namespace, but normal unmount commands cannot release its mount. The script now
uses a private mount namespace for new runs and records this blocker rather than
claiming completion. Recovery and identity gates precede writes; generated
proof credentials remain private.

The 2026-10-04 retry changed cleanup to enter PID 1224's mount namespace with
`nsenter` before a normal `umount`; it still failed to release the root LV.
Focused command-construction test passed, but no physical unmount or post-rename
boot is verified. UDisks also refused safe power-off because PC601's EFI
partition is mounted on the same USB bridge. Neither drive was disconnected.
The user confirmed neither drive was actively in use. GNOME Disks later listed
both enclosure members and reported PC401 `/dev/sdd` busy during `fsync`. A
root-aware normal-unmount retry across mount namespaces also stopped with
PC401 root still mounted; it did not deactivate LVM or power off the enclosure.
Read-only diagnosis first found nine stacked root mounts across 23 namespaces,
with the listed path resolving to `ENOENT` in helper/process roots. The user
authorized a controlled host restart, but the normal restart request was blocked
by active GNOME/session shutdown inhibitors. A later serial-bound continuation
still found PC401's root LV open under `systemd-oomd`, now across 45 processes (DR157 confirms 23 distinct mount
namespaces), and stopped before VG deactivation or boot. Do not claim post-rename
boot verification; resolve the host lifecycle blocker before continuing. The
production web-app-only action flow requested for repeatable drive work is queued
as v0.2 row78 and remains unimplemented.


- [x] Recheck PC401 boot prerequisites read-only on physical ext4/LVM: eight role UUIDs/fstab, separate policy/marker, renamed GRUB root, nonempty boot files, enabled firstboot unit files and 22-entry restoration manifest (DR157). Runtime boot/service execution remains unchecked.

## PC401 boot continuation — 2026-10-04 (DR157)

Recovery/physical identity checks passed, but the guarded boot-only attempt
stopped before VG deactivation/QEMU: root is held by 23 distinct mount namespaces
across 45 processes. Ordinary namespace unmounts did not release it. Current
GNOME shutdown inhibition requires the supported native-confirmed host lifecycle
step before another boot attempt; no host restart or enclosure power-off occurred.
Actual read-only ext4/LVM checks passed eight fstab role UUIDs, separate storage
policy and marker identities, renamed GRUB root, nonempty kernel/initramfs files,
enabled firstboot unit files and a 22-entry restoration manifest. This is physical
configuration proof, not runtime services, post-rename QEMU boot or native cold
boot. No FakeRunner. See DR157 and verification/157. Boot remains open under
DR146/queue78; payload restoration hashes were not rechecked in this increment.
