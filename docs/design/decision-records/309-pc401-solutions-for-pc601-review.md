# DR309 — Useful PC401 solutions for PC601

2026-10-17. The operator requested comparison and identification of useful
ports to PC601. No physical deployment or change to the other checkout.

Compare PC401 `610cd62` with current PC601 source `b4e41ec`. The two share the
same substrate/cache/persona/session-layer design. PC601 has newer Kasm,
registry, OS-base and swap work; replacing it with the PC401 tree would regress
those features. Its installed build and current source are different claims:
the latest shared PC601 physical-target installation record is dated Oct 13;
DR260 separately records newer nested-QEMU/KVM Kasm acceptance, not native PC601.

Prepared a selective source candidate in the isolated
`baseline-build/pc601-port-review-20261017` checkout, branch
`codex/pc601-backport-review`. Candidate fixes:

1. Check migration command failures, retain interrupted-migration identity and
   refuse destination collisions. Preserve PC601's newer service-quiescence
   guard, applying it to pending retries as well as first migration.
2. Keep VG renaming pending until boot regeneration succeeds; retry against
   the same serial/VG UUID even if the VG already has its new name. Refuse an
   unreadable destination-name ownership probe.
3. Refuse missing/unmounted layered-settings reads. Keep PC601's newer guest
   swap and host-only settings schema and inheritance rules intact.
4. Record NIC bring-up failures and preserve same-second bridge backups.
5. Refuse unknown/ambiguous serials before registered-GUID formatting allowances;
   require observed whole-disk state. Reuse the freshly validated serial in the
   self-installer guard rather than issuing an inconsistent second observation.
6. Apply lane exclusion to existing-drive update discovery/execution. In this
   candidate PC601 remains the assigned drive and PC401 remains protected.

Eleven selected regressions fail against unmodified PC601 source. An additional
injected-unit regression proves why pending retries must preserve the newer
running-service guard. The combined candidate passes 308 focused tests,
including real-file/production-mv tests, pure logic, and injected command tests.
It is not a full-suite, new QEMU, database recovery, or physical PC601 claim.
The PC401 predecessor's 14 real QEMU live-environment checks remain useful
evidence of the underlying helpers; they do not certify this adapted candidate.

PC601 installer identity, Kasm setup/registry, OS build, swap implementation
and Proxmox drop-in are byte-identical to current PC601 source. Neither root
image, installer UUID nor PC401-specific handoff/history should be transplanted.

Recommendation: adopt the selected fixes on PC601's current branch, review
callers of the stronger serial guard, then verify the combined migration and
VG retry/reboot paths in a disposable installed Proxmox guest before physical
rollout. Queue72/74/75/76/78 remain open. See `docs/verification/309/` for the
comparison and test evidence. The actual PC601 installed filesystem was not
inspected; no claim is made that current source equals its installed contents.

Caller checks also caught the two Drive Administration paths needing the freshly validated serial. Those calls are included, with destination-lane data-protection fixtures. The complete self-installer/data-protection subset now passes 50 tests alongside the 258 core tests. The missing-serial regression now verifies the earlier refusal and absence of workspace/QEMU creation.
