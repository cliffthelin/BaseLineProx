# G7 — Production Daemon: Real-System Evidence

Governing: `docs/guardian/30_TDD/GUARDIAN_G7_IMPLEMENTATION_HANDOFF.md`,
`docs/adr/ADR-002-guardian-privilege-topology.md`. Normative IDs:
`P1-DMN-001..005`, `P1-SEC-001..004`.

## Revision note (preserved history — read before the rest of this document)

This is the **original candidate's** evidence, preserved as-is (not
rewritten) for history. An independent implementation audit
(`docs/evidence/g7/G7_REPAIR_EVIDENCE.md` §"Original audit verdict")
found this candidate `FAIL — G7 TRANSACTION/RECOVERY CONTRACT VIOLATED`
with four blocking findings. All four were repaired; see
`docs/evidence/g7/G7_REPAIR_EVIDENCE.md` for the repair, its own fresh
real-VM evidence, and the corrected disposition of every claim below.
Specifically, superseded by the repair:

- **§"P1-DMN-005" / recovery claims below**: this document's own
  `recover_on_startup` only classified and logged nonterminal
  transactions — it never executed a resume or durable termination. The
  repair replaced this with real recovery execution; see the repair
  evidence's recovery matrix.
- **§"Class B — provider-owned authorization stays out of the helper"**:
  `AttemptProviderDelegatedWrite`/`Guardian1.Transactions1`, described
  below as part of `guardian-daemon`'s production surface, was found to
  be an unjustified permanent API addition and was **removed**. Class B's
  architecture is now evidenced by a disposable prototype under
  `tests/vm/g7-class-b-prototype/`, not production code.
- **§"G4/G5 forward-constraint findings" (FC-2)**: this document claimed
  FC-2 (`RecorderPolicy` runtime wiring) closed. The audit found the two
  policy branches produced no real behavioral difference. The repair
  withdraws the closure claim — FC-2 remains open — while keeping the
  real, permanent (now periodic, Class C) policy evaluation this
  candidate introduced.
- **Test coverage**: this candidate added zero automated tests (189
  unchanged). The repair adds 15 Layer-1 tests (204 total).

The systemd hardening, privilege topology (unprivileged daemon / root
helper with empty capabilities), direct-call architecture, disjoint
persistent-state ownership, real polkit authorization, and
helper-unavailable fail-closed behavior documented below were
independently re-verified by the audit and preserved unchanged by the
repair — those sections remain accurate and are not superseded.

## Environment

Disposable Ubuntu 26.04 LTS VM (`multipass`, KVM-backed), `guardian-g7-vm`,
built and destroyed entirely within this evidence pass — never the primary
workstation. Real `rustc`/`cargo` 1.93.1, real `systemd`, real
`polkitd` (`127-2ubuntu1`), real system D-Bus. VM created, evidenced, and
deleted/purged in this session; no state persists beyond this repository's
own committed artifacts.

## What was built

```text
guardian-daemon  — crates/guardian-daemon/src/bin/guardian-daemon.rs
                    (new binary target on the existing crate; reuses the
                    unchanged G0 GuardianContract at /io/github/cliffthelin/
                    Guardian1, adds an additive child object at
                    /io/github/cliffthelin/Guardian1/Transactions exposing
                    one Class B evidence method)
guardian-helper  — crates/guardian-helper/ (new crate/binary), owns
                    io.github.cliffthelin.GuardianHelper1, exposes
                    GuardedWrite (Class A) and CallCount (read-only
                    evidence accessor)
```

Systemd units, D-Bus policy, and polkit policy/rules used for this pass
are committed alongside this document: `guardian-daemon.service`,
`guardian-helper.service`, `io.github.cliffthelin.Guardian1.conf`,
`io.github.cliffthelin.GuardianHelper1.conf`,
`io.github.cliffthelin.guardian.g7.policy`, `50-guardian-g7.rules`.

## P1-DMN-001..005 matrix

| ID | Claim | Evidence | Result |
|---|---|---|---|
| P1-DMN-001 | Boot start, before graphical login | Real `sudo reboot`; VM confirmed at `uptime: up 0 min`; both units `active (running)` within 7s of boot, `Invocation` IDs fresh, `WantedBy=multi-user.target` (no graphical/session-bus dependency). `guardian-daemon-journal.txt`/`guardian-helper-journal.txt` show the post-boot `Started ...` lines. | PASS |
| P1-DMN-002 | Restart preserves required persistent state | **guardian-helper**: counter `2` before `systemctl restart`, `2` after, next call `→ 3` (continuity, not reset). **guardian-daemon**: counter `1` before restart, `1` after, next call `→ 2`. Evidenced separately per process, per G7 handoff §2.5/§5. | PASS |
| P1-DMN-003 | No desktop dependency | VM has no desktop session at all (`gnome-shell`: not found); both units run under `system.slice`, `Type=simple`, no `session bus`/`Requires=graphical-session.target`. | PASS |
| P1-DMN-004 | Clean stop, no corrupt persistence | `systemctl stop` both (idle); `sudo systemctl is-active` → `inactive`/`inactive`; every persisted `.txn` record under both `transactions/` directories re-read and confirmed parseable (schema_version=1, valid fields, no corruption); clean `systemctl start` afterward succeeded. | PASS |
| P1-DMN-005 | Crash recovery, no corrupt state | **guardian-helper**: real `kill -9` landed on a genuinely in-flight transaction (`GUARDIAN_HELPER_APPLY_DELAY_MS=8000` evidence-only hook held the process inside a real Apply call; persisted record showed `state=applying apply_outcome=not_recorded` at kill time); systemd auto-restarted (`Restart=on-failure`); real startup recovery classified it `SafeToResume` via unmodified `guardian_core::transaction::recovery::classify`. **guardian-daemon**: identical pattern, same real classification. See `guardian-helper-journal.txt`/`guardian-daemon-journal.txt` for the exact real transcript (`Main process exited, code=killed, status=9/KILL` → `Scheduled restart` → `recovery: ... classification=SafeToResume`). | PASS |

## P1-SEC-001..004 matrix

| ID | Claim | Evidence | Result |
|---|---|---|---|
| P1-SEC-001 | Hardening review artifact exists | `sudo systemd-analyze security` captured separately for both units (not a combined/summarized claim): `guardian-daemon.service: 0.6 SAFE`, `guardian-helper.service: 1.1 OK` — numerically identical to G2's accepted Model B measurements. Full outputs: `guardian-daemon-security.txt`, `guardian-helper-security.txt`. | PASS |
| P1-SEC-002 | Path access bounded to declared writable paths | Real behavioral proof, not unit-file inspection: `nsenter --target <helper-pid> --mount` then `echo x > /root/should-fail-write` → `Read-only file system`; the same namespace writing to `/var/lib/guardian/helper/...` → succeeded. `ProtectSystem=strict` + `ReadWritePaths=` genuinely enforced at the kernel/mount-namespace level. | PASS |
| P1-SEC-003 | No arbitrary shell/command execution surface | Full `gdbus introspect --recurse` of both services (`guardian1-introspection.txt`, `guardianhelper1-introspection.txt`) shows exactly: `Guardian1` → `ContractVersion`, `ServiceState` (unchanged G0 shape); `Guardian1.Transactions1` → `AttemptProviderDelegatedWrite` (no args); `GuardianHelper1` → `GuardedWrite(bool) -> u64`, `CallCount() -> u64`. No path/argv/opaque-payload/action-name parameter anywhere. | PASS |
| P1-SEC-004 | Unauthorized client denied | Real, genuinely different unprivileged identity `guardiang7denied` (separate real Linux account, no group overlap with `guardiang7caller`) called `GuardedWrite` directly against `GuardianHelper1` → real polkit denial: `io.github.cliffthelin.Guardian1.Error.NotAuthorized: authorization denied for io.github.cliffthelin.guardian.g7.bounded-write`; helper's counter confirmed unchanged before/after (no mutation occurred). Call went directly to `guardian-helper`, never through `guardian-daemon`. | PASS |

## Class A — helper-local full lifecycle, direct client call

`GuardedWrite` drives the complete, unmodified G4 engine
(`snapshot`→`validate`→`authorize`→`apply`→`observe`→`confirm`/`rollback`)
entirely inside `guardian-helper`. Real end-to-end run: `guardiang7caller`
(a real, distinct Linux account) called `GuardianHelper1.GuardedWrite`
directly on the system bus; the counter advanced `1 → 2 → 3` across
separate real calls, confirming genuine, non-fabricated mutation each
time. `guardian-daemon` never appears anywhere in this call path — see
"Direct-call invariant findings" below.

## Class B — provider-owned authorization stays out of the helper

`AttemptProviderDelegatedWrite` (on `guardian-daemon`) drives its own,
separate, in-process G4 engine instance against a distinct stand-in
adapter and distinct counter file. `Authorize` is recorded as delegated
(no `CheckAuthorization` call — `guardian-daemon`'s source contains zero
references to `PolkitAuthorizer`/`CheckAuthorization`). Confirmed via
source grep: `guardian-daemon`'s binary contains **zero** references to
`GuardianHelper1` anywhere (comments explaining the absence aside — no
`zbus::Proxy`/client construction against the helper's name exists). The
helper-unavailable test (below) additionally confirms Class B continues
to function independently of the helper's own state.

## Persistent state

```text
/var/lib/guardian/daemon/  — owner guardiand:guardiand, mode 0755 (dir)
  /delegated-counter        — 0600, guardiand:guardiand
  /transactions/*.txn       — 0600, guardiand:guardiand, sole writer guardiand

/var/lib/guardian/helper/  — owner root:root, mode 0755 (dir)
  /guarded-counter           — 0600, root:root
  /transactions/*.txn       — 0600, root:root, sole writer root
```

Full real listing: `state-ownership.txt`. Cross-read denial proven
directly: `sudo -u guardiand cat /var/lib/guardian/helper/guarded-counter`
→ `Permission denied` (real filesystem enforcement, not merely absent
code). No transaction file exists in both directories; no file was ever
observed with mixed ownership. Corruption/recovery: both processes use
G4's unmodified `persistence`/`recovery` modules independently — see
P1-DMN-004/005 above for real recovery-classification evidence.

## D-Bus evidence

```text
io.github.cliffthelin.Guardian1        owner (unique name at capture time): confirmed via
                                        real GetNameOwner call, matches guardian-daemon's pid
io.github.cliffthelin.GuardianHelper1  owner: confirmed via real GetNameOwner call, matches
                                        guardian-helper's pid
```

Real caller resolution: every `GuardedWrite` call above used the actual
OS identity of the real calling user (`guardiang7caller`/
`guardiang7denied`), resolved by `guardian_core::identity::
resolve_caller_identity` from the live D-Bus connection — never a
client-supplied field (the method's only parameter is `interactive: bool`).

## Polkit evidence

- Real authorization granted: `guardiang7caller` → `GuardedWrite` succeeds
  (real `polkit.addRule` match on real Linux username, `50-guardian-g7.rules`).
- Real denial: `guardiang7denied` → real `NotAuthorized` D-Bus error.
- Helper-unavailable fail-closed: see adversarial check 11 below — a
  `ServiceUnknown` D-Bus error, not a misclassified denial, not a silent
  success.

## systemd evidence

Boot (real reboot), restart (graceful), clean stop, crash recovery
(real `kill -9` with a genuinely in-flight transaction), and desktop
independence are all evidenced above with real transcripts
(`*-journal.txt`, `combined-final-journal.txt`).

## Privilege evidence

Captured directly from `/proc/<pid>/status`, both before and after a real
reboot (`post-reboot-privilege.txt`):

```text
guardian-daemon: Uid=999(guardiand) Gid=986 Cap{Inh,Prm,Eff,Bnd,Amb}=0 NoNewPrivs=1
guardian-helper: Uid=0(root)        Gid=0   Cap{Inh,Prm,Eff,Bnd,Amb}=0 NoNewPrivs=1
```

Matches ADR-002's accepted Model B measurement exactly: the daemon is
genuinely unprivileged (non-root, zero capabilities); the helper runs as
root (required for polkit's trusted-caller constraint, per ADR-002 — not
a Guardian design choice) but with **zero** Linux capabilities — no
capability was granted "just in case." `systemd-analyze security` scores
(0.6 SAFE / 1.1 OK) are numerically identical to G2's accepted evidence
for the same topology.

## Adversarial checks (§6a, all eleven)

| # | Check | Evidence | Result |
|---|---|---|---|
| 1 | Daemon relay test | `grep GuardianHelper1 crates/guardian-daemon/**` — zero code references (only explanatory doc comments); behaviorally, Class A only ever succeeded via direct calls to `GuardianHelper1`, never via `guardian-daemon`. | PASS (no relay exists) |
| 2 | Caller-identity-through-relay (must FAIL if found) | No relay path exists (check 1) — nothing to exercise, stated explicitly rather than fabricating one. | N/A — correctly nothing to exercise |
| 3 | Forwarded-UID trust test | `GuardedWrite`'s only parameter is `interactive: bool` (confirmed via live introspection) — structurally no field exists for a caller-supplied UID/identity to occupy. | PASS |
| 4 | Forwarded-authorization trust test | Every `GuardedWrite` call (granted and denied) produced a real, distinct polkit result tied to the real calling identity — no "pre-authorized" bypass parameter exists. | PASS |
| 5 | Daemon-writes-helper-state test | `sudo -u guardiand cat /var/lib/guardian/helper/guarded-counter` → `Permission denied`; source grep confirms no code path attempts it. | PASS |
| 6 | Helper-accepts-daemon-authorship test | `grep 'guardian/daemon\|GUARDIAN_DAEMON' crates/guardian-helper/src/main.rs` — zero references; helper never reads anything daemon-authored. | PASS |
| 7 | Class B routed through helper test | Same grep as check 1 — zero references to `GuardianHelper1` anywhere in `guardian-daemon`. | PASS |
| 8 | Dual-writer test | `/var/lib/guardian/daemon/transactions/` and `/var/lib/guardian/helper/transactions/` are disjoint directories with disjoint ownership (`state-ownership.txt`); no transaction ID ever appeared in both. | PASS |
| 9 | Generic-helper-method audit | `GuardianHelper1` exposes exactly two methods: `GuardedWrite(bool)` (one typed bool, no path/argv/opaque payload) and `CallCount()` (read-only, no input). | PASS |
| 10 | Guardian1/GuardianHelper1 growth audit | `Guardian1`: `ContractVersion`/`ServiceState` — unchanged from G0. `Guardian1.Transactions1`: one method, required by P1-DMN/P1-SEC's need for a real Class B path. `GuardianHelper1`: two methods, required by P1-SEC-004/evidence. No unmapped surface found. | PASS |
| 11 | Helper-unavailable fail-closed check | `guardian-helper` stopped; direct call → real `ServiceUnknown` error (fail-closed); `guardian-daemon`'s only reachable method (`AttemptProviderDelegatedWrite`) is Class B, a structurally different capability/counter — confirmed via introspection to have no Class A method at all; helper's counter (`3`) unchanged before/after. Zero privileged mutation occurred; no fallback path exists. | PASS |

## G4/G5 forward-constraint findings

- **G5's FC-2 (`RecorderPolicy` runtime wiring)**: closed for `guardian-daemon`. Real journal evidence: `[guardian-daemon] recorder: len=1 dropped=0 policy=Normal free_space=Sufficient` — `recorder_policy_for()` is called on every real Class B/C call and its result (`Normal`/`MemoryFirst`) is logged and acted on (spill attempted only under `Normal`). `FreeSpaceState` is derived from a real (not fixture) probe write to the daemon's own state directory, observing a genuine `io::ErrorKind::StorageFull` as the `Critical` signal — deliberately minimal, disclosed as not a full disk-usage provider (G8 scope).
- **G5's FC-1 (byte-boundedness)**: not newly implicated — this evidence build's recorder payloads are small and fixed-shape; a byte-level bound was not required and none was added, consistent with the FC's own scoping.
- **G4's FC-3 (recorder/persistence relationship)**: the recorder and the Class B/C transaction persistence module now share `guardian-daemon`'s process for the first time. Decision: they remain independent — recorder events do not reference transaction IDs in this evidence build, and no code path couples them. Documented here as the explicit decision this FC required, not silently ignored.

## Scope confirmation

No real G8 provider (UDisks/NetworkManager/systemd1/PSI/etc.) was
implemented — Class B uses a minimal typed stand-in adapter only. No G9
client/CLI/TUI/GUI/indicator was built. `tests/vm/g6-daemon-evidence-stub`
was not touched, referenced, or reused. No incidental growth on either
public D-Bus name beyond what the nine normative IDs required.

## Teardown

VM stopped, deleted, and purged (`multipass stop/delete/purge`) after
evidence capture; `multipass list` confirms no instances remain.
