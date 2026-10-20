# DR157 — PC401 boot-gate retry and physical read-only prerequisites

2026-10-04 local. Continues DR146 / REAL-013 / queue78 at the operator's request.

## Actual physical checks

PC401 serial <PC401 drive serial> resolves to /dev/sdd in this observation; it is
not persisted as device identity. Serial/512110190592-byte size and exact
PV/VG UUID gates passed. The existing recovery image independently verified
before the guarded boot-only attempt. PC601 <PC601 drive serial> is preserved.

The read-only diagnosis found nine stacked root mounts per representative
namespace and 23 distinct mount namespaces. Boot-only attempted ordinary
namespace-targeted unmounts but stopped: the root remained open with references
in 45 processes. Its report says "process namespaces", but those are process
counts, not distinct namespace counts. First failures were ENOENT on recorded
child mount paths. Host-root path lookup now resolves a directory on device
48, not the selected root LV 252:6; a visible same-named directory does not
make the buried mount accessible. A sole systemd-oomd namespace was not proven,
so its guarded service-restart branch did not execute.

No formatting, new provisioning, force/lazy unmount, VG deactivation, QEMU boot,
enclosure power-off or host restart occurred. This is an actual refused boot
attempt, not a completed post-rename boot. Neither native cold boot nor runtime
installed storage/persistence services are verified by this increment.

## Read-only prerequisite test

Added tests/integration/verify_pc401_offline_boot_files.py, which reads curated
public metadata with debugfs without -w, mounting or journal replay, after
serial/size/PV/VG validation. Actual checks passed:

- Eight distinct role filesystem UUIDs match fstab; root UUID also matches.
- Drive marker agrees with physical root/PV/VG; the separate SUBSTRATE policy
  passes its existing schema/capacity validator and matches every role identity.
- GRUB names the renamed root VG and correct root UUID; referenced kernel,
  initramfs and memtest files exist as nonempty regular files.
- Storage verification and persistence unit files exist and have enabled
  multi-user symlinks; this is configuration proof, not running service proof.
- Debian OS metadata is readable; the USER_ADMIN restoration manifest contains
  22 recorded SHA-256 entries. Payload hashes were not reverified in this test.

Initial exploratory /etc/os-release cat failed because debugfs does not follow
that symlink; the test reads /usr/lib/os-release. An initial test also incorrectly
looked for the SUBSTRATE policy inside root; correcting the test to read its
separate volume passed. These are harness corrections, not production fixes or
a production TDD RED/GREEN claim. debugfs command failures can return status
zero, so the test rejects additional error output and empty reads. No FakeRunner,
mock process or synthetic physical result. Syntax and diff checks passed.

## Remaining lifecycle action

Current systemd-inhibit observation lists 15 inhibitors, including GNOME's
shutdown block and VS Code's shutdown delay. The supported next step is the
production web Restart host action and native Ubuntu confirmation, respecting
those inhibitors; no forced restart or broad service termination. After return,
re-resolve PC401 serial and mount holders, then resume the existing boot-only
verifier. Its pending actual stages are renamed-disk boot under QEMU, guest
storage/persistence service execution and clean shutdown. That still does not
prove native machine cold boot, which remains a separate checklist item.

No production code or running web process was changed. Artifacts are under
verification/157. INSTALL, independent-drive checklist, runtime register, queue
and handoff are updated in place; DR146 remains history and the boot items remain
unchecked. Earlier 23-namespace diagnoses are consistent; the 45-process count
must not be presented as 45 distinct namespaces.
