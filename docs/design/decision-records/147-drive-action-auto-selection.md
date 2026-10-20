# DR147 — Select build or rebuild from fresh drive analysis

Date: 2026-10-04. Accepted direction; implementation remains open.

The operator should choose a target drive by its serial and press one action.
The installer must inspect that target and select the safe operation; the
operator should not have to decide whether the drive needs Install/Build or
Rebuild/Update.

The classification is fail-closed and based on fresh physical identity and
layout evidence:

- An enrolled, unmounted drive proven empty selects **Install/Build**.
- A recognized independent Baseline installation with matching serial-bound
  PV/VG and storage-role identities selects **Rebuild/Update**, including when
  expected OS components or role volumes are missing. Rebuild repairs the
  expected layout and replaces only disposable OS state; it retains vanilla
  installer sources and persistent user/application data according to the role
  policy. A missing role is recreated only after checking that it does not
  contain recoverable data; existing data is recovered before any replacement.
- Unknown foreign ownership, conflicting serial/UUID evidence, or damaged
  identity selects no write. The action still explains which automatic
  inventory/recovery/repair step is required; the operator is not asked to
  guess between Build and Rebuild. A mounted target is quiesced through its
  owning mount namespace before mutation, never by removing power.

The single action must show the detected mode and a reviewable plan before any
write. Its execution path must re-resolve by serial and repeat the analysis
immediately before mutation. Build must not erase data; Rebuild/Update must not
reformat persistent roles. No implicit fallback from an unknown target to a
fresh build is allowed. Both 512 GB drives use the same role sizes and policy,
with unique physical identifiers so they boot independently.

The current installer-plan page has read-only discovery, validation and stage
preview; it does not run either operation. Its `single-drive` proposal assumes
a fresh build and does not yet classify a populated independent LVM target.
The label **Rebuild/Update** describes the current PC401 continuation, but the
physical post-rename boot check is still blocked by a root-LV mount held in the
host mount namespace. No real Rebuild/Update action is claimed implemented.

Acceptance requires real-command inventory and fail-closed behavior for each
recognized/unknown state, passing software checks, and separate physical
evidence for both drives. QEMU or fake-runner tests cannot be described as
physical verification. PC601 remains outside DR146's authorized write scope.
