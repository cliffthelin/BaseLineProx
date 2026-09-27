# Guardian Phase 0/1 — G8 Milestone Record

## Project identity

```text
Project display name:  Guardian Plane
Repository slug:       guardian-plane
GitHub repository:     github.com/cliffthelin/guardian-plane
Permanent D-Bus namespace: io.github.cliffthelin.Guardian1
```

## Decision

```text
Gate:               G8 — Initial Providers
Governing:          docs/guardian/30_TDD/GUARDIAN_G8_IMPLEMENTATION_HANDOFF.md,
                     docs/guardian/30_TDD/GUARDIAN_G8_INDEPENDENT_REVIEW_HANDOFF.md
Normative IDs:       P1-SYS-001..003, P1-PSI-001..005, P1-LGI-001..002,
                     P1-UDS-001..004, P1-UPW-001..002, P1-ACC-001..003
                     (19 total) — ALL PASS
Status:              Accepted — PASS on independent re-audit
                     ("G8 is accepted" — 2026-09-02 re-audit)
```

This record is written at publication time, after acceptance — it
summarizes the accepted result and preserves the audit/repair history
below rather than rewriting it into a clean narrative that hides the
real rejection and repair cycle the candidate went through.

## Accepted providers

```text
systemd         — org.freedesktop.systemd1, native D-Bus. Real LoadUnit +
                  property read for an explicitly-named allowed unit
                  (P1-SYS-001..002); no StartUnit/StopUnit/RestartUnit
                  exists anywhere.
PSI             — crates/guardian-core/src/psi.rs (unmodified G5 model)
                  wrapped by crates/guardian-core/src/providers/psi.rs:
                  real /proc/pressure/{cpu,memory,io} reads, real kernel
                  trigger registration + poll(POLLPRI) wake, real
                  PsiEventSource dispatching a real Guardian Event through
                  the unmodified G5 ThresholdMonitor/severity model
                  (P1-PSI-001..005).
logind          — org.freedesktop.login1, native D-Bus. Real
                  ListInhibitors only; no Inhibit() acquisition exists
                  anywhere (P1-LGI-001..002).
UDisks2         — org.freedesktop.UDisks2, native D-Bus. Real
                  GetManagedObjects() topology, stable-identity selection,
                  sibling discovery, the six PowerOff() precondition
                  checks as pure validation logic, and a real
                  TopologyTracker emitting Removed/Reenumerated events
                  across consecutive real snapshots; no PowerOff() call
                  exists anywhere (P1-UDS-001..004).
UPower          — org.freedesktop.UPower, native D-Bus. Real
                  GetDisplayDevice/EnumerateDevices reads, honest
                  battery-absence handling; no power-management write
                  exists anywhere (P1-UPW-001..002).
AccountsService — org.freedesktop.Accounts, native D-Bus for
                  discovery/user-cache; real filesystem scan of
                  installed .desktop sessions (the correct next layer
                  down the hierarchy, per contract §28); no SetSession()/
                  SetXSession() exists anywhere (P1-ACC-001..003).
```

Every provider is read-only by construction — verified repeatedly by
direct source grep across every audit round, not merely asserted. The
Capability Registry (`crates/guardian-core/src/providers/registry.rs`)
populates real `CapabilityRecord`s from these six providers'
live reads; every record has `write_support: false` and honest
`Knowledge::Unknown` authorization ownership. The registry-population
worker in `guardian-daemon` reconnects every bounded cycle and clears
its snapshot on connection failure — no stale healthy state survives a
real provider outage.

## Independent audit history (preserved, not collapsed)

```text
Round 1 — initial implementation + evidence pass
  Implementer's own claim: 19/19 PASS, 257 tests.
  Independent audit verdict: FAIL — G8 REQUIRED EVIDENCE INCOMPLETE.
  Two blocking findings: P1-PSI-004 had no real kernel-poll()-firing
  event evidence (registration/O_RDWR path proven, the actual blocking
  wake was not); P1-UDS-003/P1-UDS-004 had no real Layer-3 re-
  enumeration/removal evidence (a hand-written minimal umockdev device
  description was not recognized by real udisksd's own enumeration
  logic within the evidence pass's time budget — disclosed honestly,
  not fabricated). Every other claim in that round (read-only boundary,
  provider taxonomy, dbusmock evidence, real-VM present/absent evidence)
  was independently found sound and was preserved unchanged through the
  repair.

Round 2 — repair + re-verification
  Repair: P1-PSI-004 closed with a real PsiEventSource driven by a real
  poll(POLLPRI) wait against a real bounded stress-ng CPU workload,
  producing a real threshold-crossing Guardian Event. P1-UDS-003/004
  closed using the accepted "real disposable-VM virtual-disk re-
  enumeration/removal" alternative to umockdev: a real scsi_debug
  kernel pseudo-disk, deleted and rescanned via real /sys/block/*/
  device/delete and /sys/class/scsi_host/*/scan, proving the same
  stable identity survives a real /dev node change and a real removal
  event via TopologyTracker. Real evidence during this repair also
  surfaced and fixed a genuine, repeated production defect: four
  provider adapters' first live D-Bus call misclassified a genuine
  ServiceUnknown provider-outage as MalformedResponse instead of
  ProviderUnavailable; a second evidence pass then caught that the
  first fix was itself too coarse (misclassifying a live-but-malformed
  response as ProviderUnavailable), corrected via a shared, precisely-
  scoped is_provider_absent_error helper. A separate correction removed
  a PSI-event daemon-thread wiring attempt that conflicted with G2's
  already-accepted PID-only-/proc service hardening. A further
  correction replaced a non-ISO-8601 last_observed_at implementation
  (`"12345s-since-epoch"`) with a real, tested `iso8601_utc()`. Tests:
  212 (pre-G8 baseline) -> 269.

Round 3 — independent re-audit (this record's basis)
  Scope: did not trust the implementer's own re-verification claims,
  which had themselves accumulated three internally-inconsistent
  "final/authoritative" report sections with conflicting digests and
  test counts (268 vs. 269, two digest schemes, one stale Rust-version
  claim) — flagged and consolidated into one authoritative record as
  part of this round.
  Independently reproduced from scratch, in a freshly provisioned
  disposable VM (not reused from any prior session): byte-identical
  source confirmed via sorted per-file SHA-256 across every crates/,
  Cargo.toml/Cargo.lock, and docs/guardian/ file; clean fmt/clippy;
  269/0 test run; P1-PSI-004's real trigger/poll/event chain reproduced
  independently (2 non-crossing wakes, a real crossing on wake 3, a
  real Guardian Event); P1-UDS-003/004's real scsi_debug delete/rescan
  reproduced independently (same stable ID survives a real /dev node
  change, real Removed/Reenumerated events); the taxonomy-fix
  classification spot-checked independently against a freshly-masked
  real UPower. Read-only boundary re-confirmed by direct grep. One
  operational-hygiene finding corrected during this round: an orphaned
  disposable VM left running from an earlier pass, and a stray
  untracked evidence-bundle tar file, were found and cleaned up.
  Verdict: G8 is accepted. Zero blocking findings.
```

## Evidence index (referenced, not duplicated here)

```text
docs/guardian/30_TDD/GUARDIAN_G8_IMPLEMENTATION_HANDOFF.md
docs/guardian/30_TDD/GUARDIAN_G8_INDEPENDENT_REVIEW_HANDOFF.md
docs/evidence/g8/G8_EVIDENCE_REPORT.md (full implementation/repair/
  independent-re-audit narrative, in order, not collapsed)
docs/evidence/g8/dbusmock/*.log (18 Layer-2 scenarios, final digest)
docs/evidence/g8/vm/*.log (Layer-4 real-VM evidence: present/absent,
  PSI trigger/event, UDisks lifecycle, registry reappearance,
  environment versions, the disclosed umockdev attempt)
crates/guardian-core/src/providers/{mod,accounts,logind,psi,registry,
  systemd,udisks,upower}.rs (production provider adapters)
crates/guardian-core/examples/g8_*.rs, g8_dbusmock_evidence.py
  (evidence infrastructure, not a shipped production surface)
crates/guardian-daemon/src/bin/guardian-daemon.rs (registry-population
  worker; also carries this gate's correction to a stale G7 doc-comment
  claim about "zero D-Bus client/proxy construction")
```
