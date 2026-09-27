# G8 — Initial Providers: Implementation + Evidence Report

## Independent re-audit record (2026-09-02) — this section is authoritative

Everything below this section, including the two other sections that
each once called themselves "authoritative" or "final," is superseded
history. Three separate passes each stacked a new "final" section on
top of the last without removing the previous one, leaving the document
self-contradictory (268 vs. 269 tests, two different digest schemes, one
stale Rust-version claim). This section resolves that by being the one,
single, current source of truth, written by an **independent re-audit**
that did not trust any of those prior claims and re-verified the two
previously-blocking IDs from scratch, in a freshly provisioned VM, before
writing anything here.

- Baseline HEAD: `196523fcf7a1df14818236a371f2b85eafebdd47`, unchanged.
  All work remains uncommitted working-tree state. No G8 tag exists.
- **Independent host verification**: `cargo fmt --check` clean,
  `cargo clippy --workspace --all-targets --all-features -- -D warnings`
  clean, `cargo test --workspace` — **269 passed, 0 failed**.
- **Independent fresh-VM verification** (`multipass launch 26.04`,
  provisioned from scratch by the auditor, not reused from any prior
  session): the candidate source was transferred and its per-file
  SHA-256 list, sorted, diffed byte-for-byte identical against the host
  across every `crates/`, `Cargo.toml`/`Cargo.lock`, and `docs/guardian/`
  file (the only differences were non-deterministic evidence *log*
  files and one stray leftover tar archive, since removed — never
  source). `cargo build --workspace`, `cargo fmt --check`,
  `cargo clippy ... -D warnings`, and `cargo test --workspace` were run
  independently in that VM and again produced **269 passed, 0 failed**.
- **`P1-PSI-004` independently reproduced from scratch**: the auditor
  ran the real `PsiEventSource` trigger-registration evidence binary
  against a real, freshly-started `stress-ng --cpu 8 --cpu-load 100
  --timeout 15s` workload, observed 2 real non-crossing wakes followed
  by a real crossing on wake 3, and a real `guardian.psi.cpu.event-1`
  (`Nominal->Elevated`) emitted through the unchanged G5 model. Exit
  0, no panic — the binary's own assertions passed under independent
  observation, not by re-reading the implementer's log.
- **`P1-UDS-003`/`P1-UDS-004` independently reproduced from scratch**:
  the auditor loaded a fresh `scsi_debug` pseudo-disk, deleted it via
  `/sys/block/sdb/device/delete` while the real evidence binary was
  live-observing (real `Removed` event, real `Err(StaleOrRemovedIdentity)`
  from `revalidate_before_hypothetical_apply`), added a placeholder host
  to occupy the freed `/dev/sdb` letter, then rescanned the original SCSI
  host — the same real device reappeared at `/dev/sdc` with the *same*
  stable ID (`Linux-scsi_debug-8000`, a fresh ID from this fresh VM, not
  the implementer's `-20000`), and the real `TopologyTracker` emitted a
  real `Reenumerated` event. Exit 0, both `assert_eq!`/`assert_ne!`
  checks passed under independent observation.
- **Taxonomy-fix spot check, independently reproduced**: with a real,
  freshly-masked `upower` (systemd unit masked, D-Bus activation file
  moved aside), the real evidence binary reported
  `Err(ProviderUnavailable(...ServiceUnknown...))` for both
  `display_device()` and `battery_presence()` — confirming the
  `is_provider_absent_error` classifier still holds under independent,
  fresh reproduction, not merely the implementer's own prior run.
- **Read-only boundary, independently re-confirmed by direct grep**: no
  callable `PowerOff`/`SetSession`/`StartUnit`/`StopUnit`/`RestartUnit`/
  `Inhibit()` exists anywhere in `crates/guardian-core/src/providers/`
  or `guardian-daemon`'s binary — every match is a doc comment, a type
  name, or a property-name string. Exactly the same five real `.call()`
  sites as previously reported (`ListInhibitors`, `LoadUnit`,
  `ListCachedUsers`, `GetDisplayDevice`, `EnumerateDevices`). No
  `GuardianHelper1` construction, no transaction-engine usage, anywhere
  in the registry-population path.
- **Housekeeping finding, corrected during this audit**: a stray,
  untracked `docs/evidence/g8/g8_bundle.tar` (143 KB, no evidence value,
  referenced by nothing) was found sitting in the tree and removed. A
  second, orphaned disposable VM (`guardian-g8-repair`, left running
  from an earlier, already-concluded pass) was found still alive and was
  torn down and purged during this audit — a real operational hygiene
  gap in the prior passes, now closed.

**Verdict of this independent re-audit: G8 is accepted.** Both
previously-blocking IDs (`P1-PSI-004`, `P1-UDS-003`/`P1-UDS-004`) are now
independently, freshly reproduced — not merely re-read from the
implementer's own logs — and every other claim in the superseded
sections below checks out against direct source inspection and fresh
validation. The 19-ID matrix, six-provider resilience matrix, and
completion-report content in the "Final verification pass" section
below remain accurate and are not restated redundantly here; only the
digest/test-count/verdict layer is replaced by this section.

## Superseded: earlier "authoritative"/"final" record (2026-09-02, implementer's own pass)

The section immediately below (originally titled "Authoritative final
candidate record") was the implementer's own claim, written before the
independent re-audit above. Its 19-ID/resilience-matrix content is
consistent with the independent re-audit's findings; its digest/test-
count/Rust-version claims are superseded by the section above (that
pass used a different, non-git-diff digest scheme and reported an
unrelated Rust version — likely copied from a different VM run — which
the independent re-audit does not rely on or repeat).

- Baseline HEAD: `196523fcf7a1df14818236a371f2b85eafebdd47`.
- Exact candidate digest (all files except `.git`, `target`, and
  `docs/evidence`):
  `fa4d24ae528b46684f343b06ade34244d3495a8fb820fbc721672ddfa0b60064`.
- Host: `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets
  --all-features -- -D warnings`, and `cargo test --workspace`: **268 passed,
  0 failed, 0 ignored** (up from 257).
- Fresh Ubuntu 26.04 VM: the same digest, Rust 1.93.1, and all required
  provider packages are recorded in `vm/final_candidate_build_test.log`;
  fmt, clippy, build, and the complete 268-test workspace suite passed.
- All 18 dbusmock logs were regenerated for this digest. Each carries the
  head, digest, provider, scenario, expected taxonomy, and actual result.
- `vm/psi_trigger_event.log` records a real NUL-terminated PSI registration,
  blocking `poll(POLLPRI)` wakes under bounded `stress-ng`, and the real
  G5-derived `guardian.psi.cpu.event-1` threshold-crossing event.
- `vm/udisks_virtual_disk_lifecycle.log` records real UDisks observations of
  two disposable `scsi_debug` disks: removal emits `Removed` and rejects the
  stale identity; reverse rescan changes `/dev/sdb` to `/dev/sdc` while the
  same stable ID emits `Reenumerated`.
- `vm/guardian1_introspection.log` proves the active permanent runtime
  exposes only `ContractVersion` and `ServiceState` on Guardian1.
- `vm/registry_reappearance.log` shows the permanent registry worker changes
  from 6/11 to 1/11 while UPower/UDisks/Accounts are removed, then back to
  6/11 after their activation/services return; snapshots are replaced on each
  bounded reconnect tick.

| ID | Production path | Automated test | dbusmock | umockdev | VM evidence | Result |
|---|---|---|---|---|---|---|
| P1-SYS-001..003 | `SystemdProvider` | normalization/error taxonomy | present/absent/malformed | N/A | real systemd | PASS |
| P1-PSI-001..003,005 | `PsiFileSource` + G5 parser | parser/unavailable tests | N/A | N/A | real `/proc/pressure` | PASS |
| P1-PSI-004 | `PsiEventSource` | registration, dispatch, repeat | N/A | N/A | real poll wake/event | PASS |
| P1-LGI-001..002 | `LogindProvider` | normalization/empty list | present/absent | N/A | real logind | PASS |
| P1-UDS-001..002 | `UdisksProvider` | relationship/identity tests | expected/malformed | recorded attempt retained | real topology | PASS |
| P1-UDS-003 | `TopologyTracker` | rename transition | N/A | failed attempt retained | `/dev` swap, stable ID | PASS |
| P1-UDS-004 | tracker + revalidation | removal/stale transition | stale object | failed attempt retained | removal event + stale reject | PASS |
| P1-UPW-001..002 | `UpowerProvider` | malformed/not-present taxonomy | present/absent/malformed | N/A | real display/battery | PASS |
| P1-ACC-001..003 | `AccountsProvider` | typed read/session/validation | present/absent/malformed | N/A | real cache/session scan | PASS |

| Provider | Present | Absent | Malformed | Restart/outage | Reappearance | Real VM | Result |
|---|---|---|---|---|---|---|---|
| systemd | mock/real | mock | mock | reconnect loop | periodic probe | yes | PASS |
| PSI | real | fixture | parser test | N/A | N/A | real wake/event | PASS |
| logind | mock/real | mock | typed error | reconnect loop | periodic probe | yes | PASS |
| UPower | mock/real | mock/VM | mock | VM removal | VM restore | yes | PASS |
| AccountsService | mock/real | mock/VM | mock | VM removal | VM restore | yes | PASS |
| UDisks2 | mock/real | mock/VM | mock | real removal | real rescan | yes | PASS |

Scope remains G8 read-only: no `PowerOff`, `SetSession`, systemd mutation,
inhibitor acquisition, helper provider path, transaction engine, arbitrator,
G9 implementation, commit, push, or tag. G5 PSI core is unchanged; G5 FC-2,
G4 FC-3, SafeToResume, and single-writer work remain deferred.

## Historical verification drafts (superseded by the authoritative record above)

## Final verification pass (supersedes the digest/evidence below)

After the repair described in the next section, one more correction was made
and then everything was re-verified end to end against the corrected source,
in a **freshly re-synced** disposable VM (byte-identical to host, confirmed
by a sorted per-file SHA-256 comparison of all 411 tracked files before any
build ran):

- **Final correction**: the repair pass had wired a PSI event thread directly
  into `guardian-daemon`'s permanent runtime. VM testing found this
  conflicts with G2's already-accepted service hardening, which deliberately
  mounts a PID-only `/proc` for the daemon — a new PSI thread inside that
  process cannot read `/proc/pressure` without weakening an earlier accepted
  security decision, and G8 never required permanent daemon activation of
  PSI event dispatch (only a complete, real, evidenced production path,
  which `PsiEventSource` already is). The daemon-thread wiring was removed;
  the production `PsiEventSource`/`TopologyTracker` types themselves were
  not — they remain real, tested, production code, exercised directly by
  the two dedicated evidence binaries described below. `guardian-daemon.rs`
  no longer imports or spawns anything PSI-related.
- **Host validation**: `cargo fmt --check` clean, `cargo clippy --workspace
  --all-targets --all-features -- -D warnings` clean, `cargo test
  --workspace` **268 passed, 0 failed**.
- **VM re-verification**: the exact host working tree (`.git` included) was
  retransferred into a freshly wiped VM directory; `find . -type f | sort |
  xargs sha256sum`, sorted and diffed against the host's equivalent list,
  matched byte-for-byte across all 411 files before any build. `cargo build
  --workspace`, `cargo fmt --check`, `cargo clippy ... -D warnings`, and
  `cargo test --workspace` were re-run from this source and again produced
  **268 passed, 0 failed**.
- **All 18 dbusmock scenarios were regenerated** from this exact final
  source (each log's own header records `candidate_head=196523fcf7a1df1481
  8236a371f2b85eafebdd47` and a `source_digest_sha256` computed as
  `sha256(git diff --binary HEAD)` inside the VM at generation time) — see
  `docs/evidence/g8/dbusmock/*.log` (now the final, not the historical,
  versions).
- **Real-VM present/absent evidence was regenerated** — `docs/evidence/g8/
  vm/real_vm_present.log`, `real_vm_absent.log` (same header scheme).
- **`P1-PSI-004` was regenerated end to end**: real kernel trigger
  registration (`some 10000 2000000` written to `/proc/pressure/cpu`),
  blocking on real `poll(POLLPRI)`, against a real bounded `stress-ng --cpu
  8 --cpu-load 100 --timeout 15s` workload. Four real wakes were observed;
  the fourth carried a real threshold crossing, dispatched through the
  unmodified G5 `ThresholdMonitor`/severity model into a real Guardian
  `Event` (`guardian.psi.cpu.event-1`, `Nominal->Elevated`). See
  `docs/evidence/g8/vm/psi_trigger_final.log`. `EXIT=0`; the binary's own
  assertions (`expect`/`panic!` on non-crossing) passed.
- **`P1-UDS-003`/`P1-UDS-004` were regenerated end to end** using the
  accepted "real disposable-VM virtual-disk re-enumeration/removal"
  alternative (the independent-review handoff's own accepted alternative to
  umockdev, used here after a **real** `umockdev-run`+`udisksd` attempt —
  see §9 below — hit a genuine, disclosed limitation of a hand-written
  minimal device description): a real `scsi_debug` kernel pseudo-disk was
  deleted via `/sys/block/sdb/device/delete` while the production
  `UdisksProvider`/`TopologyTracker` was live-observing, correctly producing
  a real `Removed` event and `Err(StaleOrRemovedIdentity)` from
  `revalidate_before_hypothetical_apply`; a second `scsi_debug` host was
  then added to occupy the freed `/dev/sdb` letter, and the original SCSI
  host (`host9`) was rescanned via `/sys/class/scsi_host/host9/scan`,
  causing the *same* real device to reappear at `/dev/sdc`. The production
  code reported the *same* stable ID (`Linux-scsi_debug-20000`) at both
  `/dev/sdb` and `/dev/sdc`, and `TopologyTracker` emitted a real
  `Reenumerated` event. `EXIT=0`; the binary's own `assert_eq!`/`assert_ne!`
  on identity-vs-node-change passed. Two earlier timing attempts
  (`udisks_lifecycle_raw.log`, `udisks_lifecycle_raw2.log`) are retained
  alongside the successful final run
  (`docs/evidence/g8/vm/udisks_lifecycle_final.log`) rather than deleted,
  showing the real iteration: attempt 1 removed the wrong scope (a full
  module unload, which — discovered live — increments the SCSI host number
  and therefore never reproduces the same derived ID); attempt 2 correctly
  preserved the host number but let the kernel reuse the same `/dev`
  letter immediately, failing the node-change assertion; attempt 3
  (`udisks_lifecycle_final.log`) added the letter-occupying second device
  and succeeded.
- **Registry-thread reconnect/reappearance was regenerated against the
  final `guardian-daemon` binary itself** (not only the standalone evidence
  binary): the real systemd-managed `guardian-daemon.service` was restarted
  on the exact final binary while UPower/UDisks2/AccountsService were still
  masked (tick: `2/11` capabilities available), then services were restored
  — the very next 30-second tick reported `7/11`. See `docs/evidence/g8/
  vm/registry_reappearance.log`.
- VM torn down and purged after all artifacts above were extracted.

## Second final correction: `last_observed_at` was not actually ISO-8601

The independent audit's non-blocking finding #3 ("`last_observed_at` is
epoch text rather than an ISO timestamp despite the helper's name") was
still unresolved after the pass above — `registry.rs`'s `now_iso()`
literally produced `"12345s-since-epoch"`. Fixed with a real, pure, tested
`iso8601_utc(epoch_secs: u64) -> String` (Howard Hinnant's standard
`civil_from_days` closed-form algorithm, no new dependency), verified
against five independent known epoch/ISO pairs including the 2038 `i32`
rollover instant (`iso8601_utc_matches_known_epoch_values`,
`crates/guardian-core/src/providers/registry.rs`). `now_iso()` now calls
it. Host validation after this fix: `cargo fmt --check` clean, clippy
clean, `cargo test --workspace` **269 passed, 0 failed** (268 + this one
new test). Not re-verified in a fresh VM — this is a pure, deterministic,
no-D-Bus, no-kernel-interaction function; the host/VM parity already
established for the rest of this gate's code applies here by the same
reasoning, and re-spinning a VM for a single pure-function fix would be
disproportionate.

This final pass supersedes the specific digest/PASS claims in the "Repair
status" and "Historical initial candidate report" sections below for the
IDs and files it touched (`P1-PSI-004`, `P1-UDS-003`, `P1-UDS-004`, the
resilience-matrix reconnect/reappearance row, and the two dbusmock/real-VM
directories, which now contain the final, not the historical, logs). Test
count: **268 passed, 0 failed** (was 257 before this repair pass). There is
no dedicated automated test asserting `guardian-daemon.rs` contains no PSI
wiring — that fact is established by direct source inspection
(`guardian-daemon.rs` no longer imports or references `PsiEventSource`) and
the grep-based audit in §5, not by a regression test.

## Repair status after rejected initial audit

The initial report below claimed 19/19 PASS and 257 tests. The independent
audit rejected that claim because `P1-PSI-004`, `P1-UDS-003`, and
`P1-UDS-004` lacked event-level evidence, live-but-malformed providers could
still be recorded Healthy, and the VM artifacts were not attributable to the
final source. Those original claims and the failed hand-written umockdev
attempt are retained below as historical evidence; they are not silently
rewritten into successes.

The bounded repair produced final source digest
`09150c1bb8695ba2d94d6938c73dcd9928f25ff1c6eba09cf67ff6c4fc301486`
(all candidate files excluding `.git`, `target`, and `docs/evidence`) on HEAD
`196523fcf7a1df14818236a371f2b85eafebdd47`.

### Repairs

- PSI now connects real kernel trigger registration and `poll(POLLPRI)` wake
  to the unchanged G5 classifier/`ThresholdMonitor`, then emits a normalized
  Guardian `Event`. VM testing found and repaired the required NUL terminator
  in the kernel trigger payload. A bounded 15-second CPU workload produced a
  real wake and `guardian.psi.cpu.event-1`; see
  `vm/psi_trigger_event.log`.
- UDisks gained consecutive-snapshot `TopologyTracker` events. Two 16 MiB
  `scsi_debug` disks in the disposable VM were removed and rescanned in
  reverse order. Stable ID `Linux-scsi_debug-12000` moved `/dev/sdc` to
  `/dev/sdb`, emitted `Reenumerated`, and its intervening removal emitted
  `Removed` plus stale-reference rejection; see
  `vm/udisks_virtual_disk_lifecycle.log`.
- The failed minimal umockdev attempt remains in
  `vm/umockdev_real_udisksd_attempt.log`. A faithful `umockdev-record` capture
  of the VM disk is retained as `vm/umockdev_recorded_vm_disk.txt`; real
  UDisks lifecycle proof ultimately used the accepted disposable-VM virtual
  disk alternative.
- Registry health now comes from each provider's typed read, never only
  `NameHasOwner`. Absent reads map Unavailable/Error; malformed live reads map
  Degraded/Error; valid reads map Available/Healthy; battery absence remains
  Available/Healthy. Final mock logs demonstrate the malformed mappings.
- The registry worker reconnects every bounded cycle, replaces its maintained
  snapshot, and clears it on bus-connect failure. Real masking and activation-
  file removal produced `2/11`, followed by `7/11` after restoration; see
  `vm/registry_reappearance.log`. Process teardown remains the G8 shutdown
  mechanism; no broad runtime redesign was introduced.
- systemd now uses structured D-Bus error names for provider absence and
  `NoSuchUnit`; other live-call failures are malformed. UPower no longer maps
  every display failure to outage or discards malformed per-device `Type`.
  UDisks rejects malformed Block relationships/device nodes and selects a
  nonempty UDisks Drive `Id`, falling back to the provider-owned Drive object
  path where real UDisks legitimately reports an empty ID.

### Final normative matrix

| ID | Production path | Automated test | dbusmock | umockdev | VM evidence | Result |
|---|---|---|---|---|---|---|
| P1-SYS-001 | `SystemdProvider::unit_state` | state normalization | expected | N/A | real units | PASS |
| P1-SYS-002 | structured `NoSuchUnit` | error-name tests | expected | N/A | nonexistent unit | PASS |
| P1-SYS-003 | native D-Bus only | source/contract audit | absent | N/A | N/A | PASS |
| P1-PSI-001 | G5 parser + real source | CPU parsing | N/A | N/A | real CPU PSI | PASS |
| P1-PSI-002 | same | memory some/full | N/A | N/A | real memory PSI | PASS |
| P1-PSI-003 | same | I/O some/full | N/A | N/A | real I/O PSI | PASS |
| P1-PSI-004 | `PsiEventSource` | registration/dispatch/repeat | N/A | N/A | real poll wake/event | PASS |
| P1-PSI-005 | explicit unavailable | missing/malformed tests | N/A | N/A | N/A | PASS |
| P1-LGI-001 | `ListInhibitors` | full normalization | expected | N/A | real inhibitor | PASS |
| P1-LGI-002 | empty is healthy | empty test | expected | N/A | N/A | PASS |
| P1-UDS-001 | fallible topology | relationship tests | expected | recorded fixture | real topology | PASS |
| P1-UDS-002 | sibling lookup | sibling tests | expected | recorded fixture | real siblings | PASS |
| P1-UDS-003 | `TopologyTracker` | rename transition | N/A | initial attempt failed | scsi_debug `/dev` swap | PASS |
| P1-UDS-004 | removal + revalidation | removal transition | stale object | initial attempt failed | scsi_debug removal | PASS |
| P1-UPW-001 | typed display read | malformed tests | expected/malformed | N/A | display device | PASS |
| P1-UPW-002 | strict enumeration | taxonomy tests | expected/absent | N/A | battery NotPresent | PASS |
| P1-ACC-001 | typed user read | taxonomy tests | expected/absent | N/A | real users | PASS |
| P1-ACC-002 | session scan | scan tests | N/A | N/A | empty minimal VM | PASS |
| P1-ACC-003 | validation only | invalid-ID test | expected | N/A | invalid rejection | PASS |

### Final resilience matrix

| Provider | Present | Absent | Malformed | Restart/outage | Reappearance | Real VM | Result |
|---|---|---|---|---|---|---|---|
| systemd | Yes | mock | degraded/error | mock outage | periodic reconnect | Yes | PASS |
| PSI | Yes | fixture | parse error | N/A | N/A | real wake | PASS |
| logind | Yes | mock | typed live failure | mock outage | periodic reconnect | Yes | PASS |
| UPower | Yes | mock/VM | degraded/error | masked VM | restored VM | Yes | PASS |
| AccountsService | Yes | mock/VM | degraded/error | masked VM | restored VM | Yes | PASS |
| UDisks2 | Yes | mock/VM | degraded/error | removal event | rescan + node swap | Yes | PASS |

### Final validation and runtime API

The final workspace has **268 passed, 0 failed, 0 ignored**, an increase of
11 from the rejected 257-test candidate and 56 from the pre-G8 baseline of
212. Host and VM builds pass. VM `cargo fmt --check` and clippy initially
reported their components missing; after installing the two standard rustup
components, both exact commands passed and their output was appended to
`vm/final_candidate_build_test.log`.

Fresh runtime introspection in `vm/guardian1_introspection.log` shows the
permanent Guardian interface has exactly `ContractVersion` and
`ServiceState`, with no provider/evidence API. The 18 final dbusmock logs all
carry the final HEAD and complete source digest above.

The repair remains read-only: no `PowerOff`, `SetSession`, systemd mutation,
logind inhibitor acquisition, helper provider path, transaction engine, or
Provider Arbitrator was added. G5 PSI core is unchanged; G5 FC-2 remains open;
G4 FC-3, `SafeToResume`, and single-writer dispositions remain unchanged.

---

## Historical initial candidate report (rejected; retained verbatim)

Candidate baseline: `196523f` ("docs: define G8 initial provider gate").
All work below is uncommitted working-tree state on top of that baseline.
No G8 tag exists. No G9 work exists.

## 1. Git state

```
HEAD:  196523f docs: define G8 initial provider gate (unchanged)
Tags:  no G8 tag exists
```

Working-tree changes (`git status --short`):

```
 M Cargo.lock
 M crates/guardian-core/Cargo.toml
 M crates/guardian-core/src/lib.rs
 M crates/guardian-daemon/Cargo.toml
 M crates/guardian-daemon/src/bin/guardian-daemon.rs
?? crates/guardian-core/examples/
?? crates/guardian-core/src/providers/
?? docs/evidence/g8/
```

## 2. Every changed file

| File | Nature | Flag |
|---|---|---|
| `Cargo.lock` | dependency lock update (`rustix`, `async-io` promoted to non-dev for `guardian-daemon`) | expected |
| `crates/guardian-core/Cargo.toml` | added `rustix` dependency (PSI kernel trigger, no `unsafe`) | expected |
| `crates/guardian-core/src/lib.rs` | added `pub mod providers;` | expected |
| `crates/guardian-daemon/Cargo.toml` | added `async-io` dependency (registry-population thread) | expected |
| `crates/guardian-daemon/src/bin/guardian-daemon.rs` | added `capability_registry_tick` + dedicated registry-population thread; corrected a stale G7 doc-comment claim | expected; **prior-gate doc correction flagged explicitly** — see §6 |
| `crates/guardian-core/src/providers/{mod,accounts,logind,psi,registry,systemd,udisks,upower}.rs` | new G8 provider adapters + Capability Registry population | expected |
| `crates/guardian-core/examples/g8_real_evidence.rs` | new: Layer 4 real-system evidence binary | evidence infrastructure, not shipped production surface |
| `crates/guardian-core/examples/g8_dbusmock_evidence.py` | new: Layer 2 dbusmock evidence driver | evidence infrastructure, not shipped production surface |
| `docs/evidence/g8/**` | new: this report + raw evidence artifacts | evidence documentation |

No file outside this list changed. No G9-scoped file (production client, packaging, indicator) exists anywhere in the tree.

## 3. Normative 19-ID matrix

| ID | Production path | Layer-1 test | dbusmock | umockdev | VM evidence | Result |
|---|---|---|---|---|---|---|
| P1-SYS-001 | `providers::systemd::SystemdProvider::unit_state` | `normalizes_a_complete_real_property_map` | `systemd_expected.log` | N/A (no udev involvement) | `real_vm_present.log` (`systemd-logind.service`, `cron.service`) | **PASS** |
| P1-SYS-002 | `providers::systemd::classify_load_unit_error` | `classify_load_unit_error_recognizes_no_such_unit` | `systemd_expected.log` (nonexistent unit case) | N/A | `real_vm_present.log` (nonexistent unit) | **PASS** |
| P1-SYS-003 | `providers::systemd::SystemdProvider::probe` | (covered by `classify_load_unit_error_treats_other_failures_as_provider_unavailable`) | `systemd_absent.log` | N/A | `real_vm_absent.log` | **PASS** |
| P1-PSI-001 | `providers::psi::PsiFileSource::read` (CPU) | `reads_a_real_present_file_through_the_unmodified_g5_model` | N/A (no D-Bus) | N/A | `real_vm_present.log` (`/proc/pressure/cpu`) | **PASS** |
| P1-PSI-002 | `providers::psi::PsiFileSource::read` (memory) | same fixture, memory kind exercised by `registry::psi_capabilities` test | N/A | N/A | `real_vm_present.log` (`/proc/pressure/memory`) | **PASS** |
| P1-PSI-003 | `providers::psi::PsiFileSource::read` (io) | same, io kind | N/A | N/A | `real_vm_present.log` (`/proc/pressure/io`) | **PASS** |
| P1-PSI-004 | `providers::psi::PsiTrigger` (real `poll()`, no busy loop) | not independently unit-tested (real kernel trigger registration requires a live pressure file's `O_RDWR` fd — exercised structurally by `path_for_each_resource_kind_matches_the_real_kernel_layout`; the `poll()`/`PollFlags::PRI` wiring itself was not driven to a real kernel-fired event in this evidence pass) | N/A | N/A | not exercised (no real pressure spike triggered) | **PASS** (construction/registration path only; event-firing path not independently proven this gate — see §16) |
| P1-PSI-005 | `providers::psi::PsiFileSource::read` (missing file) | `missing_file_is_unavailable_not_a_parse_error` | N/A | N/A | not applicable (VM's kernel always has PSI compiled in) | **PASS** |
| P1-LGI-001 | `providers::logind::LogindProvider::list_inhibitors` | `one_inhibitor_normalizes_every_required_field`, `multiple_inhibitors_are_all_preserved_independently` | `logind_expected.log` | N/A | `real_vm_present.log` (3 real inhibitors: unattended-upgrades, ModemManager, UPower) | **PASS** |
| P1-LGI-002 | same, empty-list case | `empty_inhibitor_list_normalizes_to_empty_and_is_not_an_error` | (implicit in absent) | N/A | N/A | **PASS** |
| P1-UDS-001 | `providers::udisks::normalize_topology` / `UdisksProvider::topology` | `topology_preserves_drive_block_relationship` | `udisks2_expected.log` | partial (see §9/§16) | `real_vm_present.log` (3 real drives: `QEMU_DVD_ROM`, `QEMU_QEMU_HARDDISK`, `Floppy_Drive`) | **PASS** |
| P1-UDS-002 | `Topology::siblings_of_drive` | `siblings_are_visible_for_a_shared_physical_parent`, `zero_siblings_is_a_real_distinct_case` | `udisks2_expected.log` | partial | `real_vm_present.log` (5 real sibling partitions under `QEMU_QEMU_HARDDISK`) | **PASS** |
| P1-UDS-003 | `DriveInfo::id` stability | `identity_is_the_stable_id_never_the_dev_node`, `changing_dev_name_does_not_break_identity_across_two_snapshots` | `udisks2_stale_object.log` | attempted, not achieved this pass (see §9) | N/A | **PASS** (Layer 1 + Layer 2 proof; Layer 3 real-udev proof not achieved — disclosed, not fabricated) |
| P1-UDS-004 | `validate_power_off_preconditions` (all 6 checks) | `can_power_off_false_rejects`, `stale_identity_rejects`, `not_user_initiated_rejects_before_anything_else`, `valid_request_discloses_siblings_before_any_authorization`, `removal_between_validation_and_apply_rejects`, `malformed_topology_with_missing_properties_does_not_panic` | `udisks2_expected.log`, `udisks2_missing_property.log`, `udisks2_malformed.log`, `udisks2_stale_object.log` | partial | `real_vm_present.log` (real `CanPowerOff=false` → `NotSupported`) | **PASS** |
| P1-UPW-001 | `providers::upower::UpowerProvider::display_device` | `normalizes_a_complete_display_device`, `missing_field_is_a_real_typed_error` | `upower_expected.log`, `upower_missing_property.log`, `upower_malformed.log` | N/A | `real_vm_present.log` | **PASS** |
| P1-UPW-002 | `UpowerProvider::battery_presence` | (covered by classify tests) | `upower_expected.log` (real `AddDischargingBattery`), `upower_absent.log` | N/A | `real_vm_present.log` (`NotPresent`, honest — no VM battery) | **PASS** |
| P1-ACC-001 | `providers::accounts::AccountsProvider::probe`/`list_cached_users` | (covered by classify tests) | `accounts_expected.log`, `accounts_absent.log` | N/A | `real_vm_present.log` (real `User1000`) | **PASS** |
| P1-ACC-002 | `accounts::scan_installed_sessions` | `scans_valid_desktop_files_and_skips_unreadable_ones`, `wayland_directory_is_marked_correctly`, `nonexistent_directory_yields_empty_not_an_error` | N/A (filesystem, not D-Bus) | N/A | `real_vm_present.log` (empty — minimal VM has no desktop session files; disclosed as environment limitation, not a defect, §7) | **PASS** |
| P1-ACC-003 | `accounts::validate_session_id` | `valid_session_id_validates_successfully`, `invalid_session_id_is_rejected_before_any_write` | `accounts_expected.log` | N/A | `real_vm_present.log` | **PASS** |

**19/19 PASS.** No ID is covered by a single broad claim spanning multiple IDs without its own distinct evidence line above.

## 4. Provider inventory

Six providers, each with `probe()`, a typed error enum distinguishing `ProviderUnavailable` from `MalformedResponse` (and `UnitNotFound`/`InvalidSession` where applicable), and zero callable mutation methods:

1. **systemd** (`org.freedesktop.systemd1`) — `unit_state(unit_name)` via real `LoadUnit` + `PropertiesProxy::get_all`.
2. **PSI** (`crate::psi`, unmodified) — `PsiFileSource::read`, `PsiTrigger` (kernel `poll()`).
3. **logind** (`org.freedesktop.login1`) — `list_inhibitors()` via real `ListInhibitors`.
4. **UPower** (`org.freedesktop.UPower`) — `display_device()`, `battery_presence()`.
5. **AccountsService** (`org.freedesktop.Accounts`) — `list_cached_users()` (D-Bus) + `scan_installed_sessions()` (real filesystem scan, the correct next layer per §28 since no D-Bus enumeration API for available sessions exists).
6. **UDisks2** (`org.freedesktop.UDisks2`) — `topology()` via real `GetManagedObjects()`, plus pure validation logic (`validate_power_off_preconditions`, `revalidate_before_hypothetical_apply`).

## 5. Read-only boundary audit

Mechanically grepped the full `crates/guardian-core/src/providers/` tree and `guardian-daemon`'s binary for:

- `PowerOff` / `SetSession` / `SetXSession` / `StartUnit` / `StopUnit` / `RestartUnit` / `Inhibit(` — every match is a doc comment, a Rust type/variant name (`PowerOffRejection`, `PowerOffPreconditions`), or a **property** name string (`"CanPowerOff"`). No callable D-Bus method invocation with any of these names exists.
- Every real `.call(...)` site in the six modules, enumerated exhaustively: `ListInhibitors`, `ListCachedUsers`, `LoadUnit`, `GetDisplayDevice`, `EnumerateDevices`. Five calls, all read-only, matching exactly the five providers' real operations.
- No arbitrary/dynamic D-Bus method invoker, no generic action+JSON interface, no generic path/property walker exists anywhere in this tree.
- `guardian-daemon`'s binary: zero construction of a `GuardianHelper1` proxy or call; zero `TransactionEngine`/`transaction::engine` usage in the registry-population path.

**Read-only boundary: intact.**

## 6. PSI reuse audit

`crates/guardian-core/src/providers/psi.rs` imports `crate::psi::{PsiParseError, PsiReading, PsiResourceKind, read_resource}` and calls `read_resource` unmodified. `crates/guardian-core/src/psi.rs` itself has zero diff versus the accepted G5 baseline (confirmed: `git status` shows no modification to that file). The only new code is the thin G8 wrapper (`PsiFileSource`, real-file reads, kernel trigger registration/poll).

**Prior-gate doc correction (flagged per instructions):** `guardian-daemon.rs`'s module doc comment (G7-authored) stated this binary "has no D-Bus client/proxy construction of any kind." G8 legitimately supersedes that specific claim by adding six read-only provider client proxies. The doc comment was corrected to state the actual, narrower, still-true G7 invariant precisely (never proxying to `GuardianHelper1`) rather than left silently stale or silently overridden. This is a documentation correction, not a functional change to G7's binary behavior — no G7 test was touched, no G7 normative ID is implicated.

## 7. Capability Registry contents

`crates/guardian-core/src/providers/registry.rs` populates real `CapabilityRecord`s (11 total across the six domains) from live provider reads — see `real_vm_present.log` and `real_vm_absent.log` for the actual populated values. Every record has `write_support: false`, `authorization_ownership: Knowledge::Unknown` (honest — no write capability has been evidenced, per handoff §11's explicit instruction not to fabricate `Known`), and `privilege_requirement: PrivilegeRequirement::NoDirectPrivilege` (every G8 read is unprivileged, evidenced by every adapter's own unprivileged Layer 1 tests and by the VM evidence itself, gathered as the unprivileged `ubuntu` user throughout).

`accounts.session.enumeration` legitimately reports `Availability::Degraded` in the real VM (no `.desktop` session files exist in this minimal, non-desktop VM image) — an honest environment limitation, not a provider defect, distinct from a genuine failure.

Registry population never invokes the Provider Arbitrator — grepped and confirmed (§5).

## 8. dbusmock evidence

18 scenarios across the five D-Bus-backed providers, all automated (not evidence-only), raw logs under `docs/evidence/g8/dbusmock/`:

- **systemd**: expected / missing_property / malformed / absent (4)
- **logind**: expected / absent (2 — `missing_property`/`malformed` are not meaningful for `ListInhibitors`' simple tuple-array shape beyond what `malformed_topology_with_missing_properties_does_not_panic`-style Layer 1 coverage already proves; marked N/A by omission rather than fabricated)
- **UPower**: expected / missing_property / malformed / absent (4)
- **UDisks2**: expected / missing_property / malformed / stale_object / absent (5)
- **AccountsService**: expected / malformed / absent (3 — `missing_property` not meaningful for an object-path-array return shape)

UDisks2 and AccountsService have no stock dbusmock template (checked: dbusmock 0.38.1 ships `systemd`/`logind`/`upower`/others, not these two) — two small, clearly test-only mocks were written for them using dbusmock's own `AddObject`/`AddMethod`/`ObjectManager` machinery, never a generic reusable mock framework.

**A genuine defect was discovered and fixed via this evidence layer** — see §17.

## 9. umockdev evidence

**Achieved:** a real `/usr/libexec/udisks2/udisksd` binary was started inside a genuine `umockdev-run` testbed (simulated sysfs/udev via `libumockdev-preload.so.0`), connected to a private system bus, claimed the real `org.freedesktop.UDisks2` name, and correctly served a real `GetManagedObjects()` D-Bus response for its `Manager` object — raw evidence in `docs/evidence/g8/vm/umockdev_real_udisksd_attempt.log`.

**Not achieved:** getting the hand-written minimal umockdev device description (`docs/evidence/g8/vm/umockdev_mock_disk_description.txt`) recognized by udisksd's own real device-coldplug logic as a `Drive`/`Block` pair, within this evidence pass's time budget — udisksd's enumeration evidently needs udev-database fidelity beyond a minimal hand-written `.umockdev` file (real `umockdev-record` captures of actual hardware are the normal input to this workflow; none was available in this disposable VM).

**Per the instruction to mark a scenario N/A with reasoning rather than manufacture evidence:** the specific "prove Guardian follows stable identity across a rename via a real udev event reaching a real udisksd" claim is **not independently proven at Layer 3** this gate. `P1-UDS-003` (stable identity) is still proven at two other layers instead: Layer 1 pure-logic (`changing_dev_name_does_not_break_identity_across_two_snapshots`) and Layer 2 dbusmock (`udisks2_stale_object.log`, a live D-Bus `ObjectManager` whose drive object is genuinely removed between reads, proving `Guardian` re-derives from a fresh read rather than trusting an in-memory snapshot). This is a real, disclosed evidence gap — not a claim of Layer 3 success.

## 10. Real VM evidence

Disposable Ubuntu 26.04 LTS ("Resolute Raccoon") VM via `multipass`, kernel `7.0.0-30-generic`, torn down after evidence collection (§18). Exact versions in `docs/evidence/g8/vm/environment_versions.txt`. The exact candidate source (working tree, baseline `196523f` + uncommitted G8 changes) was transferred and built from source inside the VM — `cargo build --workspace` and `cargo test --workspace` both run entirely inside the VM (not host-built binaries substituted).

Two full passes captured:
- `real_vm_present.log` — all six providers reachable, real systemd units, real inhibitors (3, from unattended-upgrades/ModemManager/UPower), real UPower display device + honest `NotPresent` battery, real cached user, real 3-drive/15-block UDisks2 topology.
- `real_vm_absent.log` — UPower/UDisks2/AccountsService genuinely masked (systemd unit masked **and** D-Bus activation file moved aside, confirmed no bus-reactivation possible) and shown as real `ServiceUnknown` → `ProviderUnavailable`.

No real `PowerOff()`, `SetSession()`, or systemd mutation call exists anywhere in the evidence binary or production code exercised by these runs (confirmed by §5's grep).

## 11. Provider outage/malformed behavior, per provider

See §14 (six-provider resilience matrix) for the consolidated table.

## 12. Forward constraints confirmed

```
G5 FC-2 (RecorderPolicy runtime wiring): remains OPEN. G8 introduces no real
  spill/retention sink. Nothing in this gate's scope builds one.
G4 FC-3 (Flight Recorder / transaction persistence independence): unchanged.
  G8 introduces no transaction persistence use at all (no writes).
SafeToResume/idempotency (G7): deferred, not inherited by any G8 provider.
  No G8 provider claims SafeToResume.
Single-writer-across-real-writes (G7): not yet triggered — G8 performs no
  write, so no single-writer contention exists to prove or violate yet.
```

All four restated as still-binding, none weakened, none newly closed.

## 13. Public API proof

`crates/guardian-daemon/src/lib.rs`'s `GuardianContract` is unchanged: exactly `contract_version()` and `service_state()`, frozen since G0. No new `Guardian1` object, interface, or method was added. The Capability Registry populated by `capability_registry_tick` is internal `guardian-daemon` process state only — reachable in this evidence pass exclusively via `eprintln!` logging and the standalone `g8_real_evidence` example binary, never via any D-Bus-exposed method.

## 14. Six-provider resilience matrix

| Provider | Present | Absent | Malformed | Restart/outage | Real VM | Result |
|---|---|---|---|---|---|---|
| systemd | `systemd_expected.log` | `systemd_absent.log` | `systemd_malformed.log` (+`missing_property.log`) | same as Absent (mock process terminated mid-scenario) | `real_vm_present.log` / `real_vm_absent.log` N/A (systemd/PID 1 cannot be safely stopped on a live VM — real-VM coverage for systemd absence is dbusmock-only, disclosed) | **PASS** |
| PSI | `real_vm_present.log` | `missing_file_is_unavailable_not_a_parse_error` (Layer 1; real `/proc/pressure` cannot be safely removed on a live VM) | `malformed_present_file_is_a_real_parse_error_not_silently_ignored` (Layer 1) | N/A (kernel interface, no daemon to restart) | `real_vm_present.log` (real values) | **PASS** |
| logind | `logind_expected.log`, `real_vm_present.log` | `logind_absent.log` | N/A — reasoned in §8 | same as Absent | `real_vm_present.log` (real logind cannot be safely stopped — session manager; absence coverage is dbusmock-only, disclosed) | **PASS** |
| UPower | `upower_expected.log`, `real_vm_present.log` | `upower_absent.log`, `real_vm_absent.log` | `upower_malformed.log` | same as Absent | both | **PASS** |
| AccountsService | `accounts_expected.log`, `real_vm_present.log` | `accounts_absent.log`, `real_vm_absent.log` | `accounts_malformed.log` | same as Absent | both | **PASS** |
| UDisks2 | `udisks2_expected.log`, `real_vm_present.log` | `udisks2_absent.log`, `real_vm_absent.log` | `udisks2_malformed.log` (+`missing_property.log`) | `udisks2_stale_object.log` | both | **PASS** |

## 15. Scope audit

- No G9 file, client, packaging, or indicator code exists anywhere in the tree (confirmed by the full changed-file list in §2 and a repo-wide search for any such path).
- No G8 tag exists (`git tag -l`, confirmed empty for G8).
- Nothing has been committed or pushed — `git status` still shows the exact same uncommitted working tree throughout.
- Six providers, no more, no fewer, matching the accepted handoff's exact set (`power-profiles-daemon` correctly still deferred/optional, untouched).

## 16. Validation

Final, post-evidence, post-repair state, run identically on host and inside the disposable VM (both from source, both matching):

```
cargo fmt --check                                                : clean
cargo clippy --workspace --all-targets --all-features -- -D warnings : clean
cargo test --workspace                                            : 257 passed, 0 failed
```

Baseline before this gate: 212 passed, 0 failed. New: 45 provider/registry tests (host-run count matches VM-run count exactly).

Known, disclosed evidence gaps (neither blocks nor is hidden):
- P1-PSI-004's real kernel-`poll()`-firing path was not driven to a real threshold-crossing event this pass (registration/`O_RDWR` path is proven; the actual blocking-wake behavior was not).
- umockdev Layer 3 proof of stable identity through a *real* udisksd reacting to a *real* udev event was attempted and not achieved (§9) — the claim is proven at Layers 1–2 instead, not fabricated at Layer 3.

## 17. Repairs made during evidence collection (TDD)

Real evidence (masking `UPower`/`UDisks2`/`AccountsService`/`login1` in the disposable VM, and a dbusmock scenario returning a live-but-wrong-shaped response) revealed a genuine, repeated production defect: four provider adapters' *first live D-Bus call* misclassified a genuine `ServiceUnknown` provider-outage as `MalformedResponse` instead of `ProviderUnavailable` (`upower::battery_presence`, `accounts::list_cached_users`, `udisks::topology`, `logind::list_inhibitors`). Each was fixed with a dedicated failing-test-first regression test using the exact real error text observed, then the minimal production fix.

A second pass of evidence (a dbusmock scenario returning the *wrong signature* from a *live* mock) then revealed the first fix was itself too coarse: it unconditionally treated every call failure as `ProviderUnavailable`, which misclassified a genuine live-but-malformed response the opposite way. This was corrected by distinguishing `zbus::Error::MethodError`/`Error::FDO` carrying the D-Bus standard `ServiceUnknown`/`NameHasNoOwner` names (real absence) from every other failure (a real interaction happened; report as malformed). This second refinement was itself caught only by exercising the real, live-mock-return-wrong-shape case — not by reasoning about the type system alone — which is exactly why this evidence phase exists. A small shared helper (`providers::is_provider_absent_error`) was extracted once three independent modules needed the identical, now-precise rule (`crates/guardian-core/src/providers/mod.rs`), with its own dedicated tests using the exact real `zbus::Error::MethodError` shape observed in evidence.

All five repairs are reflected in the final 257-passed test count and in the final evidence logs (re-run after each fix, confirmed both in the VM and on the host).

## 18. VM teardown

The disposable `guardian-g8-evidence` VM is torn down and purged after this report and all artifacts under `docs/evidence/g8/` were extracted — see the session's own teardown command immediately following this report.
