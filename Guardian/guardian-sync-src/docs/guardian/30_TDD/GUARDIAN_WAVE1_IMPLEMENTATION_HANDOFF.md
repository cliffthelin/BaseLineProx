# Guardian Wave 1 Implementation Handoff
## First Production Mutation Capability

Baseline: HEAD `c02b43ebae0801d3dff6571757fb919569a33578`, tagged
`phase0-g9-clients-packaging`. G0–G9 closed, independently accepted,
published. Governing amendment: TDD contract §50 (adds Wave 1 as a
distinct, unnumbered interstitial phase — **not** TDD-contract Phase 2;
§47's original read-only-only TDD-contract Phase 2 framing is preserved
unchanged and untouched — read §50 in full, including its revision
history, before this handoff).

**Revision note**: this handoff has been rewritten four times.

- The **first** rewrite fixed an empirically-wrong authorization-owner
  conclusion (verified live against real systemd/polkit in a disposable
  VM) and an ambiguous ID prefix (`P2-*`) — but its own fix required a
  new, **Guardian-owned** `PolkitAction`/`.policy` action for a
  capability G2 already classified as provider-owned.
- The **second** rewrite fixed that: a more focused independent review
  found the Guardian-owned action silently converted a provider-owned
  classification to a Guardian-owned one, and it also found two
  unrelated defects — a mislabeled recovery classification for an
  in-flight `RestartUnit` crash, and no normative coverage for the
  compensating rollback itself failing. It fixed all three, but stated
  `authorization.rs` would remain unmodified while also requiring a
  provider-action check that unmodified module cannot express.
- This, the **third** rewrite, fixes that gap: a further independent
  review found the second rewrite's design unimplementable as worded —
  `PolkitAction` is a closed enum with no way to carry an arbitrary
  provider action id. `authorization.rs` now has an explicitly scoped,
  small production change: a new, equally closed `ProviderPolkitAction`
  enum (one variant, `SystemdManageUnits`) and a new, equally typed
  `authorize_provider_action` entry point, distinct from
  `authorize(PolkitAction)` — never a generic raw-action-id interface.
  This is not a new authorization model; it is the missing typed
  representation the already-approved Model B design needs. The
  `W1-VM-002b` sub-ID (no precedent anywhere in the project's accepted
  gate history) is also renumbered sequentially in this pass.
- This, the **fourth** rewrite, fixes a defect the third rewrite's own
  fix left open: checking the *correct action id* is not the same as
  reproducing the *provider's real authorization decision*. A further
  independent review empirically confirmed, by observing the real
  `CheckAuthorization` D-Bus call in a disposable VM, that systemd's own
  `manage-units` request for a unit restart carries non-empty details
  (`unit`, `verb`, `polkit.message`, `polkit.gettext_domain`) that a real
  admin polkit rule may branch on — while `PolkitAuthorizer::authorize()`
  hardcodes an empty details map for every existing call, and the third
  rewrite's `ProviderPolkitAction::SystemdManageUnits` carried no way to
  express them. §7/§10/§12 below are corrected: the provider-
  authorization request is now a closed representation of the resolved
  capability that derives **both** the action id and its complete
  details internally — never a caller-suppliable detail map, and never a
  partial subset of the real fields.

The selected capability (systemd unit restart) is unchanged across every
revision — only the authorization architecture, the recovery table, and
the method's own API shape around it are corrected.

This is a **planning document**. No Wave 1 production code exists yet.
This handoff selects and fully specifies the one candidate to implement
next; it does not implement it.

# 1. Mechanically re-derived Wave 1 scope

No prior document in this repository used the term "Wave 1" before §50.
Scope is derived from §50's acceptance bar plus the existing G2 Privilege
Requirement Inventory (`docs/evidence/g2/PRIVILEGE_REQUIREMENT_INVENTORY.md`,
24 rows, still the only real privilege-classification research this
project has done) and the six G8 read providers already in production.

| Capability family | In Wave 1 scope? | Evidence source | Write/Read | Notes |
|---|---|---|---|---|
| systemd service control (start/stop/restart) | Candidate | G2 inventory row 2 (provider-owned authorization); G8 real read provider (`crates/guardian-core/src/providers/systemd.rs`, P1-SYS-001..003) | Write | Direct extension of an already-evidenced read provider |
| power-profiles-daemon `HoldProfile` | Candidate | G2 inventory row 10 (**Guardian polkit authorization**, not provider-owned) | Write | No G8 read provider exists yet for PPD at all |
| NetworkManager configuration write | Candidate | G2 inventory row 16 (provider-owned authorization, incl. checkpoint/rollback) | Write | No G8 read provider exists yet for NetworkManager |
| AccountsService `SetSession` | Candidate | G2 inventory row 21 (provider-owned authorization); G8 real read provider (P1-ACC-001..003) | Write | Session-affecting; disruptive during VM evidence gathering |
| UDisks `PowerOff()` | Evaluated, rejected | G2 inventory row 6 (provider-owned authorization); G8 real read provider (P1-UDS-001..004); G2 inventory's own text explicitly defers storage power-off to "the I/O Guardian module phase" | Write | Selecting this as Wave 1 would silently begin the separately-gated I/O Guardian module (**master-spec** Phase 2 — see §50's disambiguation rule) — explicitly forbidden by §50's scope exclusions |
| thermald write / NVML / fwupd / apt-package-state / generic-hardware-control / BPF / usbguard / journald-rotation | Out of scope | G2 inventory: all eight rows classified `unknown — requires host research` | Write (would be) | No identified authorization owner exists for any of these — fails §50's acceptance bar outright, not merely lower-ranked |
| cgroups / transient scopes | Out of scope this round | G2 inventory row 3 (provider-owned, via `systemd1.Manager.StartTransientUnit`) | Write | Real candidate in principle, but no G8 read provider or prior evidence exists for transient-scope lifecycle; not evaluated further this pass to keep the candidate set to what already has real prior evidence |

# 2. The relay-authorization rule (§50, corrected) applies to every candidate — but not identically

Before scoring, the correction that changes every row below: **G2's
"provider-owned authorization" classification is not, by itself, a
reason a candidate needs no independent Guardian-side authorization
check.** An independent planning review found and empirically confirmed
(real `systemd`/polkit test in a disposable VM) that once
`guardian-helper` (root) is the process issuing the provider call, the
provider's own polkit check authorizes `guardian-helper` itself, not the
real end client — an unprivileged, non-admin user's own direct
`RestartUnit` call was correctly denied against that user's identity;
the identical call issued as root returned a job path with **no check
performed at all**. This is not specific to systemd — it applies
identically to NetworkManager and AccountsService's own "provider-owned"
classifications, since all three would be relayed through the same root
process.

A second, more focused review then found that the first fix — requiring
a **new, Guardian-owned** `PolkitAction`/`.policy` action before every
such relayed call — does not actually preserve "provider-owned
authorization"; it silently replaces it with a Guardian-owned decision
wearing a provider-owned label (§50's revision history has the full
finding). §50's relay-authorization rule was corrected: `guardian-helper`
performs its own mediated authorization check, resolving the real caller
from its own D-Bus connection exactly as before, but against the
**provider's own real, already-shipped polkit action id** — for systemd,
`org.freedesktop.systemd1.manage-units`, confirmed present at
`/usr/share/polkit-1/actions/org.freedesktop.systemd1.policy` in a
disposable Ubuntu 26.04.1 VM — never a Guardian-invented substitute.

A third, focused review then found *that* correction unimplementable as
worded: `PolkitAction` is a closed enum with no way to carry an
arbitrary provider action id, so "no new `PolkitAction` variant, no
change to `authorization.rs`" and "check `manage-units`" were mutually
contradictory as originally written. §50's rule is corrected a second
time (§7 below has the full design): a **separate**, equally closed
`ProviderPolkitAction` enum — one variant for Wave 1,
`SystemdManageUnits` — represents provider-owned policy actions Guardian
may mediate, through its own typed entry point. `PolkitAction` itself
still gets **no new variant**, and no new Guardian `.policy` file is
required — but `authorization.rs` does get a small, disclosed
production addition (the new enum and entry point), which this handoff
now states explicitly rather than claiming the module stays unmodified.

**Consequence for the candidate matrix — corrected**: the
authorization-clarity axis is *not* flat across the four candidates, and
saying so in the first fix's version of this section was itself an
error. Systemd already ships a real, well-defined, already-packaged
polkit action (`manage-units`) that `guardian-helper` can query today,
with no new packaging of any kind. AccountsService and NetworkManager's
real action ids were not independently re-evidenced in this pass and
must be confirmed, not assumed, before either could claim the same
advantage. PPD `HoldProfile` remains the one candidate G2's own
inventory classifies as **Guardian polkit authorization**, not
provider-owned — meaning PPD is the one candidate for which a
Guardian-owned check is actually correct architecture, not a workaround.
This restores, rather than flattens, systemd's authorization advantage
over PPD, and leaves NetworkManager/AccountsService's authorization
clarity genuinely unresolved pending their own real action-id evidence —
none of which changes the final selection (§4): systemd restart wins on
the combination of this now-real authorization simplicity, the
strongest G8-provider reuse, the only genuinely real observable
postcondition (`JobRemoved`), and the most mature prior evidence
infrastructure of the four.

# 3. Candidate property matrix (corrected)

| Property | systemd restart | PPD `HoldProfile` | NetworkManager config write | AccountsService `SetSession` | UDisks `PowerOff` |
|---|---|---|---|---|---|
| Provider | `org.freedesktop.systemd1` | `net.hadess.PowerProfiles` | `org.freedesktop.NetworkManager` | `org.freedesktop.Accounts` | `org.freedesktop.UDisks2` |
| Exact mutation | `Manager.RestartUnit(name, mode)` on one allowlisted unit | `HoldProfile(profile, reason, application_id)` | e.g. `Connection.Update`/`Activate` | `User.SetSession(id)` | `Drive.PowerOff(options)` |
| Authorization owner (corrected) | `guardian-helper`, mediating the **provider's own real** `org.freedesktop.systemd1.manage-units` action for the resolved caller — no new Guardian action; the provider's own policy stays authoritative (§2) | `guardian-helper`, via a genuinely **new Guardian-owned** `PolkitAction` — correct here, since G2 classifies PPD as Guardian polkit authorization, not provider-owned; PPD never had a provider action to mediate | Unresolved — `guardian-helper` should mediate NetworkManager's own real action id once evidenced (Model B, matching systemd); not yet confirmed in this pass | Unresolved — same as NetworkManager: AccountsService's own real action id must be evidenced before Model B can be claimed here | Same (rejected on scope grounds regardless) |
| Privilege boundary | `guardian-helper` (root), caller connects to `guardian-helper` directly — see §9 | `guardian-helper` | `guardian-helper` | `guardian-helper` | `guardian-helper` |
| Transaction owner | `guardian-helper` | `guardian-helper` | `guardian-helper` | `guardian-helper` | `guardian-helper` |
| Snapshot possible? | Yes — G8 read provider already returns `ActiveState`/`SubState` | Yes — G8 has no PPD reader; would need building | No G8 reader exists | Yes — G8 read provider returns session list | Yes — G8 read provider returns drive/block topology |
| Validation possible? | Yes — unit in allowlist, `LoadState != "not-found"`, not masked | Yes — profile name is one of a known-small enum | Partial — connection identity/precondition modeling not built | Yes — session id must be a real, enumerated session | Yes — G8 already implements the six real precondition checks |
| Postcondition observable? | Yes — real `JobRemoved` signal (`result`: done/failed/canceled/timeout/dependency/skipped) plus re-read `ActiveState` | Weak — `HoldProfile` has no job/signal completion model researched yet | Weak — activation has async state, not yet researched for this project | Yes — session change is a property read-back | Yes — device disappears from `GetManagedObjects()` |
| Rollback possible? | Weak-but-real — no true inverse of "restart"; a compensating restart is the only real option | Real — `ReleaseProfile` is the documented inverse | Real — NM's own checkpoint/rollback API exists (per G2 research) | Real in principle — re-`SetSession` to the prior id | None/weak — a powered-off drive has no software-observable "undo" |
| Rollback reliable? | Reliable for the *mechanism* (retry is safe); does not undo whatever the restart itself changed in the unit's own state | Reliable — release is a documented, symmetric operation | Unverified — checkpoint/rollback was research-only, never exercised in this project | Reliable in principle, unverified | Unreliable/nonexistent — this is exactly why G2's own inventory already defers it |
| Idempotent Apply? | Yes — systemd de-dupes/merges concurrent restart jobs for the same unit (to be confirmed empirically, not assumed — see §8) | Likely yes (hold is naturally re-appliable) | Unverified | Likely yes | N/A (rejected) |
| SafeToResume possible? | Yes, provably, for the pre-mutation states — see §8 | Not yet analyzed | Not yet analyzed | Not yet analyzed | N/A (rejected) |
| External competing writer? | A human/script `systemctl restart`, or systemd's own auto-restart-on-failure policy for the unit | Desktop-environment power-profile UI is a very plausible real competing writer | Desktop NetworkManager applets are a very plausible real competing writer | Session/login manager itself | udisks-notify / desktop "safely remove" UI |
| User impact if wrong | Bounded to one named, non-critical service | Could visibly fight a real user's own power-profile choice mid-session | Could sever the very connection Guardian's own control channel may depend on | Could disrupt the active graphical session | Ejects/powers off real (or virtual) storage — highest impact of the set |
| VM-testable? | Yes, fully, no hardware | Yes, no hardware, but no real evidence infrastructure exists yet | Yes in principle; real evidence infrastructure does not exist yet | Yes | Yes for the virtual-disk case (G8 already has real evidence infra for this) |
| Hardware required? | No | No | No | No | No (virtual disk suffices, per G8's own precedent) |

# 4. Ranked candidates (re-scored after §2's correction)

| Rank | Capability | Safety | Reversibility | Evidence quality | Architectural value | Recommendation |
|---|---|---|---|---|---|---|
| 1 | systemd unit restart (allowlisted) | High — mediates a real, already-shipped provider action (`manage-units`); no new Guardian action, no new packaging; strongest evidence of the four to bound it correctly | Medium — compensating retry only, honestly disclosed as `RollbackKind::BestEffort` | High — extends G8's already-evidenced read provider directly; real `JobRemoved` signal gives a genuine postcondition no other in-scope candidate matches | High — the natural, minimal extension of existing G8 infrastructure; systemd's job model maps almost directly onto G4's Apply/Observe discipline | **Select** |
| 2 | AccountsService `SetSession` | Medium — Model B (mediating AccountsService's own real action) is presumed available by analogy to systemd, but its action id is unevidenced in this pass; would need confirming before implementation | Medium — a second `SetSession` call is a real inverse, unverified in practice | Medium — G8 read provider exists, but exercising this destructively disrupts the very VM session used to gather evidence | Medium — real extension of an existing provider, narrower blast radius than NM, but harder to evidence cleanly and no comparable postcondition signal to `JobRemoved` | Fallback |
| 3 | power-profiles-daemon `HoldProfile` | High, but architecturally different — G2 classifies this as Guardian polkit authorization, not provider-owned, so a genuinely new Guardian-owned action is correct here, not a workaround | High — `ReleaseProfile` is a clean documented inverse, the strongest rollback story of the four | Low — no G8 read provider, no prior evidence infrastructure | Low for a *first* mutation — still requires building a read provider from scratch, which none of the other three do | Not selected — wait until a G8-class PPD read provider exists; reconsider for a later mutation once one does, given its strong rollback story |
| 4 | NetworkManager configuration write | Medium — Model B presumed available by analogy, action id unevidenced; also a real risk of severing Guardian's own management channel during VM evidence gathering, a genuinely worse operational hazard than the other three | Unverified — checkpoint/rollback was research-only | Low — nothing built yet | Low for a *first* mutation | Not selected — highest operational risk of the four in-scope candidates |
| — | UDisks `PowerOff()` | Rejected by §50's scope exclusions directly (I/O Guardian module ownership), independent of its own technical properties | Weak/none | High technically, but scope-inadmissible | N/A | **Explicitly rejected**, not merely lower-ranked — see §1 |

# 5. Selected capability: systemd unit restart, allowlisted target

**`RestartUnit` on one Guardian-configured, explicitly-named unit,
selected only by a Guardian-defined `capability_id` (§10)** — never an
arbitrary or caller-suppliable unit name. First real evidence target
recommended: `cups.service` (present on stock Ubuntu, safe to restart
repeatedly, does not affect SSH/VM connectivity or Guardian's own
processes), exposed as the single capability-table row `cups-restart` —
chosen only as a **replaceable, test-specific** evidence target; the
capability's own contract describes a generic "restart one allowlisted
unit" operation, not a CUPS-specific one, and the capability table is
Guardian-configured, not fixed to this one unit forever. **`guardian-
daemon`/`guardian-helper` themselves are explicitly excluded** —
restarting the very process handling the request is architecturally
circular, and there is structurally no `capability_id` row that could
name either of them.

**Second-best fallback**: AccountsService `SetSession`, if `RestartUnit`
is found unsafe in practice. PPD `HoldProfile` is a credible *future*
candidate once a G8-class read provider exists for it — its rollback
story is actually the strongest of the four — but is not ready now.
NetworkManager waits because of its distinctive operational hazard
(severing Guardian's own control channel during evidence gathering), not
because of authorization clarity, which no longer distinguishes it from
the others.

# 6. Transaction ownership (G4 lifecycle, unmodified; corrected caller path)

| Step | Authoritative process | Detail |
|---|---|---|
| Snapshot | `guardian-daemon` (read-only, informational only — see note below) | Reuses the existing G8 systemd read provider — `ActiveState`/`SubState` for the target unit, exactly as any G9 client can already read it. No new privilege. |
| Validate | `guardian-helper` | `capability_id` resolves to a known row in Guardian's own compiled/configured capability table (§10) — an unknown `capability_id` is rejected before any unit name is even looked up; the resolved unit's `LoadState != "not-found"`; unit is not masked; `RefuseManualStart`/`RefuseManualStop` (or equivalent) is not set for this unit (a real, already-encountered case in this project — `xdg-desktop-autostart.target` during G9). Performed by `guardian-helper` itself, not relayed from `guardian-daemon`'s own read, since `guardian-helper` must not trust a value it did not itself observe for a decision that gates a privileged action. |
| Authorize | **`guardian-helper`**, resolving the real caller's identity **directly from its own incoming D-Bus connection** (`resolve_caller_identity`, exactly matching `GuardedWrite`'s existing precedent in `crates/guardian-helper/src/main.rs` — never a relayed/daemon-supplied identity claim), then calling the new, typed `authorize_provider_request(caller, ProviderAuthorizationRequest::SystemdRestart { capability: resolved_capability }, interactive)` entry point, which internally derives both the **provider's own** `org.freedesktop.systemd1.manage-units` action id and its complete real authorization details (`unit`, `verb`, `polkit.message`, `polkit.gettext_domain`) from the already-resolved capability row, and checks them against the resolved caller — never a Guardian-owned `PolkitAction` substitute, and never an empty or partial details map. This is the corrected step — see §7. |
| Durable intent | `guardian-helper` | Persists a real transaction record via the unmodified G4 persistence module, before calling systemd, mirroring `GuardedWrite`'s own accepted pattern exactly. |
| Apply | `guardian-helper` | `Manager.RestartUnit(unit_name, "replace")` → real systemd `Job` object path. |
| Apply outcome | `guardian-helper` | `ConfirmedSuccess` once a job path is returned; `PartialOrUncertainMutation` if the D-Bus call's response is lost after systemd may have already accepted it. |
| Observe | `guardian-helper` | Waits for the real `JobRemoved` signal matching the job id; `PostconditionMet` = `result == "done"` **and** a fresh read confirms `ActiveState`/`SubState` match the expected post-restart state; `PostconditionNotMet` = `result` in `{failed, timeout, dependency}`; `Ambiguous` = the signal was never observed (connection lost) and re-query cannot resolve it. |
| Confirm / Commit | `guardian-helper` | Transitions to `Committed` only once `PostconditionMet`. |
| Rollback | `guardian-helper` | `RollbackKind::BestEffort` — the only real compensating action is retrying `RestartUnit` once more. Disclosed honestly, not upgraded to `Native`. |
| Recovery after crash | `guardian-helper`, on restart, via the unmodified `crates/guardian-core/src/transaction/recovery.rs::classify()` | See §8 — every crash point maps onto an existing, unmodified `RecoveryClassification` variant. No new recovery logic is introduced. |

**Note on Snapshot**: `guardian-daemon`'s read is retained in the table
because it is what any G9 client already sees (e.g. before deciding to
request a restart), but it is explicitly **not** trusted by
`guardian-helper` as an input to Validate/Authorize — `guardian-helper`
re-reads and re-validates everything it needs itself, for the same
reason it resolves identity itself rather than trusting a relayed claim.

# 7. Why `guardian-helper` must perform its own authorization check, against systemd's own action and its real details (corrected four times)

The first version of this handoff concluded that `RestartUnit`'s
"provider-owned authorization" meant Guardian needed no new privilege
decision of its own — only that the *relay* had to originate from a
trusted (root) process. An independent planning review found this
conclusion empirically wrong: it correctly identified that ADR-002's
trusted-caller finding governs `CheckAuthorization`'s explicit-subject
delegation pattern, and separately reasoned through (then verified live
in a disposable VM) that `RestartUnit` is authorized against *whoever is
actually on the wire* — for a call `guardian-helper` makes, that is
`guardian-helper` itself (root), which trivially satisfies systemd's own
`auth_admin`-class check regardless of who the real requester was. The
live evidence: an unprivileged, non-admin VM user's own direct
`RestartUnit` call was correctly denied against that user's identity;
the identical call issued as root returned a job path with no check
performed at all. **Relaying this call through root, as originally
planned, would have meant Guardian's first production write path
performed no real per-user authorization decision whatsoever.**

The second version of this handoff over-corrected: it required
`guardian-helper` to check a brand-new, **Guardian-owned** `PolkitAction`
before calling `RestartUnit`. A further independent review found this
conflates two distinct claims:

```text
trusted to query polkit's authorization decision for another subject
≠
owner of the policy that decision is made against
```

`guardian-helper`'s root identity and its own D-Bus-resolved caller
identity together satisfy the *first* claim — ADR-002's trusted-caller
finding is about who may query, not which action id they query. They
say nothing about the *second* claim. A Guardian-invented action makes
Guardian's own policy authoritative for an operation G2 already
classified as provider-owned, discarding whatever an OS administrator
has already configured against systemd's own real action — this is a
silent reclassification, not a preservation, of "provider-owned
authorization."

The second version's own corrected rule ("`guardian-helper` performs its
own real `CheckAuthorization`... using systemd's own real, already-
shipped action id... No new `PolkitAction` variant and no new `.policy`
file are required") was, in turn, found **unimplementable as worded** by
a third, focused independent review: `PolkitAction`
(`crates/guardian-core/src/authorization.rs`) is a closed 5-variant enum
(`Read`, `LowRiskWrite`, `ModerateWrite`, `HighRiskWrite`,
`GuardianBoundedWrite`), and `Authorizer::authorize()` takes a typed
`PolkitAction`, not a raw action-id string — `PolkitAuthorizer`'s
underlying D-Bus proxy does accept any `action_id: &str` at the wire
level, but nothing in Guardian's own typed API surface (the thing this
handoff said would remain "unmodified") lets a caller reach that wire
call with `"org.freedesktop.systemd1.manage-units"`. As literally
written, the second version's rule required either silently adding a
`PolkitAction` variant (reintroducing the first correction's defect) or
an undisclosed change to `authorization.rs`. That gap is what this,
third, correction closes.

**Corrected rule (third correction — action id, superseded below)**:
rather than widen `PolkitAction` or accept a raw action-id string (both
rejected — see below), Wave 1's third revision planned a small, explicit,
closed addition to `crates/guardian-core/src/authorization.rs`: a
**separate** enum, `ProviderPolkitAction`, disjoint from `PolkitAction`,
naming one real, already-shipped provider action id
(`SystemdManageUnits` → `"org.freedesktop.systemd1.manage-units"`), with
a new, equally typed `authorize_provider_action(subject, action:
ProviderPolkitAction, interactive)` entry point.

**Fourth correction — the action id alone is not the whole request.** A
further independent review found this third-revision design, while
correctly typed, still insufficient: it checked the *right action id*
but with an **empty** details map — `PolkitAuthorizer::authorize()`
(`crates/guardian-core/src/authorization/polkit.rs`) hardcodes
`details: HashMap::new()` for every existing call. Independently
snooping the real `CheckAuthorization` D-Bus call in a disposable VM
(`busctl monitor --system`) while running `systemctl restart
cups.service` as an unprivileged user showed systemd's own real request
is:

```text
action_id: "org.freedesktop.systemd1.manage-units"
details:
  unit                  = "cups.service"
  verb                  = "restart"
  polkit.message        = "Authentication is required to restart '$(unit)'."
  polkit.gettext_domain = "systemd"
```

A real administrator's polkit `.rules` file may legitimately branch on
`action.lookup("unit")`/`action.lookup("verb")` — a standard pattern for
this exact action. Checking `manage-units` with empty details, as the
third revision planned, would silently diverge from what a direct
systemd call presents to that same admin rule — the mediated check could
authorize (or deny) a caller in a case where a real, detail-sensitive
provider policy would have decided the opposite. This is a genuine
policy-fidelity defect, not a cosmetic gap: "provider policy remains
authoritative" is only true if Guardian's mediated request actually
matches what the provider's own request would be.

**Corrected rule (fourth correction, current)**: `ProviderPolkitAction`
(a bare action-id enum) is replaced by a closed **request** type that
carries both the action id and its complete details, both derived
internally from an already-resolved, Guardian-controlled capability —
never a caller-suppliable detail map:

```rust
/// A provider-owned authorization request Guardian mediates on a
/// resolved caller's behalf -- disjoint from `PolkitAction`, which is
/// reserved for Guardian-owned decisions only. Each variant represents
/// one real, already-shipped provider operation; both its action id and
/// its complete authorization details are derived entirely from the
/// already-resolved, Guardian-controlled capability carried inside it --
/// never from caller input, and never as an open detail map.
pub enum ProviderAuthorizationRequest {
    /// systemd's own real `manage-units` request for a Wave 1
    /// `RestartCapability` row.
    SystemdRestart { capability: RestartCapability },
}

impl ProviderAuthorizationRequest {
    pub fn action_id(&self) -> &'static str {
        match self {
            Self::SystemdRestart { .. } => "org.freedesktop.systemd1.manage-units",
        }
    }

    /// The complete, real authorization details systemd itself would
    /// send for this exact request -- all four evidenced fields, derived
    /// from `capability`, never from caller input.
    pub fn details(&self) -> HashMap<&'static str, String> {
        match self {
            Self::SystemdRestart { capability } => HashMap::from([
                ("unit", capability.unit_name().to_owned()),
                ("verb", "restart".to_owned()),
                (
                    "polkit.message",
                    format!("Authentication is required to restart '{}'.", capability.unit_name()),
                ),
                ("polkit.gettext_domain", "systemd".to_owned()),
            ]),
        }
    }
}
```

**Correction (repair pass; runtime capture is authoritative — see §12's
`W1-AUTH-007` correction note below for the full evidence)**: this worked
example's `polkit.message` line — interpolating `capability.unit_name()`
via `format!`, following this section's own `$(unit)`-literal wire
capture above *inconsistently* — was wrong. A fresh runtime re-capture
established that real systemd never interpolates this field; the wire
value is always the literal, unsubstituted `"Authentication is required
to restart '$(unit)'."`. The shipped implementation constructs
`"polkit.message"` as that fixed literal string, not via `format!` with
the unit name. This is a correction to this worked example only —
`unit`, `verb`, and `polkit.gettext_domain` (all still correctly
interpolated/fixed here) are unaffected.

(exact Rust naming/shape is not binding; the semantics are — `capability`
is the already-validated `RestartCapability` row, resolved *before* this
request is ever constructed, per §6's ordering, so nothing caller-
suppliable reaches `action_id()`/`details()`.) A new, equally typed
entry point — `authorize_provider_request(subject: CallerIdentity,
request: ProviderAuthorizationRequest, interactive: bool) ->
Result<AuthorizationOutcome, AuthorizationError>` — issues the real
`CheckAuthorization` D-Bus call built from that closed request against
the resolved caller. It may reuse `PolkitAuthorizer`'s existing D-Bus
plumbing internally via a dedicated internal path that accepts the
derived, closed details (not by widening every existing `PolkitAction`
call site to accept an arbitrary `details` parameter — `authorize
(PolkitAction, ...)`'s existing 5 variants keep using their current
empty-details behavior unchanged, since nothing established that any of
them need details fidelity). Its **public, typed boundary stays closed**
exactly like `PolkitAction`'s own: no caller-supplied raw action-id
string, no caller-supplied detail keys or values, and no generic
`authorize_provider(action_id: &str, details: HashMap<String, String>,
...)`-shaped interface anywhere. `guardian-helper` calls
`authorize_provider_request(caller, ProviderAuthorizationRequest::
SystemdRestart { capability: resolved_capability }, interactive)`
against the real, resolved caller identity **before** calling
`RestartUnit`.

This makes Guardian's check a mediated provider-policy decision that
actually reproduces the provider's own request, not a second, competing
authority and not a partial imitation of one: whatever an OS
administrator has already granted or denied for `manage-units` — for
*this specific unit and verb*, if their policy is detail-sensitive —
governs the outcome, exactly as it would if the real caller could query
polkit directly (which, per ADR-002, they cannot, for a subject other
than themselves — hence the mediation, not a substitution). **`PolkitAction`
gets no new variant. No new Guardian `.policy` file is required.**
`authorization.rs` does get a new, disclosed, closed
`ProviderAuthorizationRequest` type and entry point — this is a scoped,
independently-reviewable typed addition, not an open-ended authorization
surface, and not the same thing as any prior version's defect: it is
neither a Guardian-owned action masquerading as provider-owned (the
first correction's error), nor an undisclosed/unimplementable "reuse it
unmodified" claim (the second correction's error), nor a correctly-typed
but detail-incomplete request (the third correction's error).

**Why not simpler shapes.** Three alternatives were considered and
rejected: (a) adding a `SystemdManageUnits` variant directly to
`PolkitAction` — rejected, because that enum is semantically reserved
for Guardian-owned decisions (its own doc comment: "each later gate that
adds a genuinely new polkit-gated operation gets its own variant here"
refers to Guardian's own actions, e.g. `GuardianBoundedWrite`; folding a
provider's action into it would misclassify ownership exactly as the
second correction's flat `PolkitAction` reuse implicitly risked); (b) a
generic `authorize_provider(action_id: &str, details: HashMap<String,
String>, ...)` method — rejected, as it reopens exactly the unbounded,
arbitrary-action-and-detail authorization surface Guardian's
typed-`PolkitAction` design has deliberately avoided since G1, for the
sake of one capability; (c) a bare action-id-only `ProviderPolkitAction`
with no details (the third correction's own shape) — rejected per this
section, since it is empirically insufficient to reproduce systemd's
real request. `ProviderAuthorizationRequest` keeps the same type-safety
guarantee `PolkitAction` already provides — nothing caller-suppliable
reaches the action id or the details — while correctly separating *who
owns the policy* and faithfully carrying *what that policy actually
evaluates*.

**Fidelity floor, not ceiling.** All four evidenced detail fields
(`unit`, `verb`, `polkit.message`, `polkit.gettext_domain`) are carried,
not a subset chosen for convenience — `unit`/`verb` are clearly
authorization-sensitive, and `polkit.message`/`polkit.gettext_domain`
are more presentation-oriented, but distinguishing normative policy
context from provider presentation metadata is deferred to a possible
future general provider-authorization abstraction, not decided
prematurely for Wave 1's first candidate. If implementation discovers
the currently-shipped systemd version sends additional or different
details for this exact operation, implementation MUST stop and reconcile
this contract rather than silently dropping or inventing fields — see
§50's binding statement of this rule.

The review also identified that this is not a new problem for this
project: G7's own independent audit already rejected an earlier
`Guardian1.Transactions1.AttemptProviderDelegatedWrite` addition as "an
unjustified permanent production API addition"
(`docs/evidence/g7/G7_MILESTONE.md`, Round 1 finding) — the same relay
shape this rule now forecloses explicitly. It also does not follow that
`GuardedWrite`'s own action (`io.github.cliffthelin.guardian.g7.bounded-
write`) is a template for this candidate: `GuardedWrite`'s action is
correct because the write it gates has no other provider and is
genuinely Guardian-owned, so it belongs on `PolkitAction`. Mirroring its
*identity-resolution mechanism* is correct (§6's note on Snapshot);
mirroring its *own action type* for a capability G2 already classified
as provider-owned would have mirrored the wrong half of the precedent —
which is exactly the error the second version of this handoff made, and
exactly what `ProviderAuthorizationRequest` being a separate, detail-
complete type now prevents structurally rather than by convention alone.

# 8. SafeToResume — earned per crash point, not inherited (crash-mid-call classification corrected)

Using the unmodified `crates/guardian-core/src/transaction/recovery.rs`
classifier directly. A prior version of this table mislabeled the
in-flight-call crash point as `MustObserve`; the real,
unmodified classifier gives that specific point `StateAmbiguous` via
`ApplyOutcome::PartialOrUncertainMutation` — a distinct branch from the
"response lost, call presumed to have completed" case, which really is
`MustObserve`. This table now distinguishes both:

| Crash point | `ApplyOutcome` recorded | `RecoveryClassification` | Why |
|---|---|---|---|
| Before durable intent persisted | (none) | `SafeToResume` | Pre-mutation state (`is_pre_mutation()`), no external call made yet. |
| After durable intent persisted, before `RestartUnit` called | `NotRecorded` | `SafeToResume` | No provider call in flight — `classify_applying`'s first arm. |
| The `RestartUnit` D-Bus call itself was in flight when the crash occurred — whether systemd received/processed it is inherently uncertain from Guardian's own persistence alone | `PartialOrUncertainMutation` | `StateAmbiguous` | `classify_applying`'s dedicated in-flight branch. Never guessed as either extreme; `SafeToResume` must not be claimed here. |
| `RestartUnit` returned (or is believed to have returned) before the crash, but the response was not durably confirmed, or was confirmed then lost before Observe began | `ConfirmedSuccess` \| `ResponseLostOrUnknown` | `MustObserve` | The call is believed to have completed; Observe can still meaningfully answer what happened either way. |
| After Apply outcome recorded, before `JobRemoved` observed | (Observing, no `last_observation`) | `MustObserve` | Job is genuinely in flight; Observe is meaningful and sufficient. |
| Mid-Observe, connection/process lost | `ObservationOutcome::Ambiguous` | `StateAmbiguous` | Neither success nor failure can be honestly asserted from what's durable. |
| Observe determined `PostconditionNotMet` | — | `MustRollback` | The only real compensating action (§6's `BestEffort` retry) applies. |
| Crash during `RollingBack` | — | `MustRollback` | Unmodified `recovery.rs` mapping — restart from the top of rollback, not assumed complete. |
| The `BestEffort` compensating restart itself fails | — | terminal `RollbackFailed` state → `RequiresHumanRecovery` on any later recovery pass | See §12's `W1-REC-008` — mirrors `GuardedWrite`'s own already-accepted `RollbackFailed` fixture coverage exactly; no new G4 state or classification is introduced. |

**Correction (repair pass, governed G4 extension — see TDD contract §50.x
"G4 extension: durable Apply-dispatch marker")**: the row above for the
in-flight-`RestartUnit` crash point states the *required* classification
(`PartialOrUncertainMutation` → `StateAmbiguous`) but this handoff's
original implementation pass found, with real VM evidence
(`docs/evidence/wave1/wave1_vm005_finding.md`), that the **unmodified**
`engine.rs`/`recovery.rs` could not actually reach it: a real `kill -9`
strictly during the in-flight D-Bus call left only
`ApplyOutcome::NotRecorded` durable (identical to the row above it),
which `classify_applying` maps to `SafeToResume` — an unsafe automatic
replay, not the `StateAmbiguous` this row requires. The project owner
adjudicated this conflict: do not weaken this row's requirement; instead
extend G4 with the minimum durable metadata needed to distinguish the two
cases — a durable "dispatch marker", persisted immediately before
`provider.apply` is invoked (a new, disclosed, narrow addition to the
*unmodified-G4* premise stated throughout this handoff, not a Wave-1-
local hack; see TDD contract §50.x for the full governance record). With
that extension, `NotRecorded` + marker set now correctly reaches
`StateAmbiguous`, and this row's requirement is met — re-verified with
fresh real VM evidence (`docs/evidence/wave1/wave1_vm005_finding.md`'s own
"Resolution" section). Every other row in this table, and the classifier
behavior it depends on, is unaffected.

**Apply idempotent?** Yes — systemd merges/queues concurrent restart jobs
for the same unit rather than double-restarting (to be confirmed
empirically in VM evidence, not assumed). **Rollback idempotent?** Yes —
retrying `RestartUnit` again is safe; if the retry itself fails, the
transaction reaches `RollbackFailed` honestly rather than retrying
indefinitely (§12's `W1-REC-008`). **Idempotency key meaningful?**
Yes — the transaction's own id plus target unit name, matching G4's
existing `P0-TXN-009` discipline (`known_completed_apply_is_not_re_
invoked_on_retry`), reused unmodified. **Re-observation sufficient after
crash?** Yes — a fresh `GetUnit`/property read plus a check of systemd's
own job list for any still-pending job on that unit answers the question
definitively, except for the genuinely in-flight case above, which
correctly resolves to `StateAmbiguous`, not a guessed answer.
**SafeToResume allowed?** Yes, for the pre-mutation states only — exactly
as the existing classifier already computes; no special-casing is
introduced for this capability. This section is unaffected by *where*
the `CheckAuthorization` call is inserted (§7) or which action id it
checks — the corrections here are independent of the authorization-model
correction.

# 9. Single-writer analysis

**Authoritative external controller**: systemd itself — Guardian is a
*requester* of systemd's own action, never a competing writer. This maps
directly onto the existing `arbitration.rs::Ownership::
ProviderOwnedWriter(ProviderId)` variant — no new variant is needed.
**Other likely writers**: a human/script issuing `systemctl restart`
directly; systemd's own automatic restart-on-failure policy for the
target unit; a package upgrade (`apt`) restarting the same unit as a
maintainer-script side effect. **Ambiguity detection**: systemd's own
job-merging semantics should de-duplicate a concurrent human-issued
restart against Guardian's own job for the same unit — Guardian's Observe
step picks up whichever job's `JobRemoved` fires. **This must be verified
empirically as real VM evidence** (start a manual `systemctl restart` and
a Guardian-issued one against the same unit concurrently), not assumed.
**Stale ownership**: the real risk is Guardian acting on a `Snapshot`
that's already outdated (someone restarted the unit moments before
Guardian's own `Validate` ran) — handled by the existing `ArbitrationInput
.revision` staleness mechanism (`P0-ARB-003`), unmodified, no new logic.
**Fail-closed conditions**: unit not in the allowlist → `Rejected` before
`Authorize`; unit `LoadState == "not-found"` → `Rejected`; systemd bus
unreachable → `Failed`/`ProviderUnavailable`, never escalated to a more
privileged retry path. **Conclusion: the existing Provider Arbitrator is
sufficient as-is.** No extension is required, and none is authorized by
this handoff. This section is unaffected by the authorization correction.

# 10. Public API minimality and production scope (corrected: capability-ID method shape, disclosed authorization.rs addition)

**No new `PolkitAction` variant and no new Guardian `.policy` file are
needed.** A prior version of this section claimed *zero* new things were
needed anywhere, which a further independent review found untrue as
worded (§7) — the corrected, honest scope is:

```text
authorization.rs:
  + ProviderAuthorizationRequest enum (one variant: SystemdRestart,
    carrying the already-resolved RestartCapability; action_id() and
    details() both derived internally -- unit, verb, polkit.message,
    polkit.gettext_domain, matching systemd's real evidenced request)
  + authorize_provider_request(subject, ProviderAuthorizationRequest,
    interactive) entry point, reusing existing CheckAuthorization/
    PolkitAuthorizer D-Bus plumbing internally via a dedicated internal
    path that accepts the derived, closed details (existing
    PolkitAction call sites are untouched and keep their current empty
    details behavior)
guardian-helper:
  + RestartCapability(capability_id: string, interactive: bool) method
  + a small, fixed capability table (§10 below)
```

This is **not** a new authorization model, and it is **not** the
`PolkitAction` widening or the raw-action-string interface both
explicitly rejected in §7 — it is the missing typed representation the
already-approved Model B design needs to actually compile. Every other
G1–G4 module this handoff claims to reuse (`recovery.rs`,
`arbitration.rs`, `error.rs`, `identity.rs`) remains genuinely
unmodified; only `authorization.rs` gets this one, disclosed, closed
addition.

The one new method is a narrow, typed method on `guardian-helper`. Its
shape is deliberately **capability-ID-based, not unit-name-based** —
this is a stronger structural boundary than validating an arbitrary
caller-supplied unit name after the fact, and closes the escape-vector
question (aliasing, templated units, path-like names, normalization
tricks) at the API surface rather than in a validator that has to get
every such case right:

```text
GuardianHelper1.RestartCapability(capability_id: string, interactive: bool) -> transaction_id: string
```

`capability_id` selects a row from a small, Guardian-compiled/configured
table — never a systemd unit name, and never any other string the caller
gets to choose freely. Each row is a fixed tuple, resolved entirely
inside `guardian-helper`, never derived from caller input:

```text
capability_id            -> ("cups-restart", ...)
canonical unit name       -> "cups.service"        (exact, no normalization
                                                      of caller input — the
                                                      caller never supplies
                                                      a unit name at all)
permitted operation       -> Restart only            (no Start/Stop/other
                                                        operation selectable
                                                        via this method)
provider action to check  -> "org.freedesktop.systemd1.manage-units"
```

For Wave 1's own acceptance, exactly **one** row exists (`cups-restart`
→ `cups.service`), matching §5's selected evidence target. The table's
shape is intentionally extensible to more rows in later work, but
`RestartCapability` itself can never be widened into
`RestartUnit(String)`/`ManageSystemd(unit, action)`/a generic broker
without a new gate: there is no parameter through which a caller can
name an arbitrary unit, an arbitrary operation, or an arbitrary D-Bus
object path — `capability_id` is looked up against a fixed, compiled/
configured table, not interpreted as, concatenated into, or normalized
toward a unit name at any point. `guardian-daemon`/`guardian-helper`'s
own units are excluded by simply never appearing as a row, not by a
runtime check that could be bypassed.

**Capability-table expansion is governed, not configuration.** Adding
another `RestartCapability` row is a capability expansion and requires
its own governed gate/review — exactly the same discipline
`PolkitAction`'s own doc comment already establishes for Guardian-owned
actions ("each later gate that adds a genuinely new... operation gets
its own variant here"), applied here to the capability table instead of
an enum. Implementation must not add rows merely by configuration or
convenience. For Wave 1's own acceptance the table has exactly **one**
governed row:

```text
capability_id: "cups-restart"
  -> unit: "cups.service"
  -> operation: Restart
  -> provider request: ProviderAuthorizationRequest::SystemdRestart
       action id: org.freedesktop.systemd1.manage-units
       details:
         unit                  = "cups.service"
         verb                  = "restart"
         polkit.message        = "Authentication is required to restart '$(unit)'."
           [corrected -- repair pass: real systemd sends the literal,
           unsubstituted "$(unit)" template, not "cups.service"
           interpolated; see §12's W1-AUTH-007 correction note]
         polkit.gettext_domain = "systemd"
```

No aliases, no templated/instance units, no dynamically-constructed unit
strings, and no additional rows without a subsequent governed review.
This is what keeps `capability_id: string` structurally safe despite
being a string type: the accepted values are a closed, compile-time/
governed set, not an open-ended namespace a caller or a future casual
commit could grow.

**Who calls it, and how this closes the "who is the caller" gap the
first version left open**: matching `GuardedWrite`'s own accepted
precedent exactly, `RestartCapability` is called by whatever real,
resolved caller connects to `guardian-helper`'s own D-Bus name directly
— for Wave 1's own acceptance, this is an evidence/test harness (the
same role G7's own harness plays for `GuardedWrite` today), not a G9
client. **No new client-facing (CLI/TUI/GUI/indicator) public capability
is required to close Wave 1** — clients remain read-only exactly as G9
left them, and contract §31 already permits "request transactions" as
future, not required, client behavior. This is not a gap: it is the
same scope Wave 1's acceptance bar (§50) actually requires — proving the
transaction/authorization framework against one real write, not
building a client UI on top of it. A future gate may add a client
affordance for this capability once it exists; that is explicitly
separate work.

# 11. Authorization semantics (corrected)

Reusing the existing 17-category `GuardianErrorCategory`
(`crates/guardian-core/src/error.rs`) unmodified — **no new category is
needed**, confirmed by direct inspection:

| Outcome | Category | Notes |
|---|---|---|
| Authorized | (no error) | `guardian-helper`'s call to `authorize_provider_request(caller, ProviderAuthorizationRequest::SystemdRestart { capability }, interactive)` (§7) — against systemd's own real `manage-units` action **and its complete real details** (`unit`, `verb`, `polkit.message`, `polkit.gettext_domain`), for the real caller identity it resolved directly — succeeded. This is a real, discriminating decision that reproduces the provider's own request, not merely its action id; it does not assume the provider's own subsequent internal check (which will trivially pass for `guardian-helper`'s own root identity) suffices on its own. |
| Denied | `NotAuthorized` | `authorize_provider_request`'s mediated, detail-complete `manage-units` check denied the real caller — the same outcome an OS administrator's existing systemd policy (including any rule keyed on `unit`/`verb`) would produce for that caller directly, mediated because the caller cannot query polkit about themselves via this specific trusted-caller pattern (ADR-002) on their own. |
| AuthenticationUnavailable | `AuthenticationUnavailable` | Reused from G1 unmodified — no authentication agent available for an interactive request. |
| ProviderUnavailable | `ProviderUnavailable` | systemd1 bus name unreachable at Apply time — never collapsed into an auth-shaped error, matching G8's own discipline. Distinct from `NotAuthorized` since Guardian's mediated authorization check and the subsequent `RestartUnit` call are separate steps, even though both ultimately concern the same provider action. |
| ValidationRejected (unit not allowlisted / not found / masked) | `PreconditionFailed` | Already exists in the taxonomy; no new category. |
| OwnershipConflict | `Conflict` | Already exists. |
| Unsupported (e.g. unit has `RefuseManualStart` set) | `Unsupported` | Already exists; a real, already-encountered case in this project. |
| Internal | `Internal` | Genuine Guardian-side invariant failure, distinct from all provider-facing outcomes. |

# 12. New normative IDs (corrected prefix — `W1-`, per §50; `W1-VM-*` renumbered sequentially, no letter-suffixed IDs; `W1-AUTH-007`/`W1-VM-007` added for provider-detail fidelity)

```text
W1-MUT-001 — Valid RestartCapability("cups-restart", ...) request against
             the resolved, existing, unmasked unit, from an authorized
             caller, succeeds and reaches Committed.
W1-MUT-002 — An unknown capability_id is rejected (PreconditionFailed)
             before any unit name is resolved and before Authorize is
             ever reached.
W1-MUT-003 — A resolved unit with LoadState "not-found" is rejected
             before Authorize.
W1-MUT-004 — A resolved unit with RefuseManualStart/RefuseManualStop set
             is rejected as Unsupported, not silently attempted.
W1-AUTH-001 — An unauthorized real caller is Denied via guardian-helper's
              own authorize_provider_request(caller,
              ProviderAuthorizationRequest::SystemdRestart { capability },
              interactive) call against systemd's real
              org.freedesktop.systemd1.manage-units action, with its
              complete real details attached — never via a Guardian-owned
              PolkitAction, and never via systemd's own subsequent
              internal check alone (non-discriminating once relayed as
              root).
W1-AUTH-002 — An interactive request that requires authentication and has
              no available agent reaches AuthenticationUnavailable, not
              Denied.
W1-AUTH-003 — A background (non-interactive) request that would require
              interaction fails closed without prompting (reuses P0-AUTH-003
              semantics for this new capability).
W1-AUTH-004 — guardian-helper resolves the real caller identity from its
              own incoming D-Bus connection only — never from a value
              supplied by guardian-daemon or any other relaying process
              (source-level, mechanically checkable, matching
              GuardedWrite's existing resolve_caller_identity pattern).
W1-AUTH-005 — Source-level, mechanically checkable: Wave 1 introduces no
              Guardian-owned replacement polkit action for systemd
              restart — PolkitAction gains no new variant, and no new
              Guardian .policy action file exists for this capability.
              Provider-owned systemd authorization is represented
              exclusively through the closed ProviderAuthorizationRequest
              type and resolves, via its own action_id(), to exactly the
              literal string "org.freedesktop.systemd1.manage-units" —
              never a caller-supplied or otherwise dynamically
              constructed action-id string.
W1-AUTH-006 — ProviderAuthorizationRequest is disjoint from PolkitAction
              (no shared variant, no conversion that erases which type a
              given check came from); authorize_provider_request's
              parameter type is ProviderAuthorizationRequest, never a raw
              &str/String action id, and its details() return type
              carries no caller-suppliable field — source-level,
              mechanically checkable, closing the generic-authorization-
              surface question directly for both the action id and its
              details.
W1-AUTH-007 — Guardian's mediated provider-policy authorization request
              MUST reproduce the governed systemd operation's
              authorization-relevant provider context. For
              "cups-restart", the action is
              org.freedesktop.systemd1.manage-units and the request's
              details() returns exactly the four evidenced fields — unit
              = "cups.service", verb = "restart", polkit.message =
              "Authentication is required to restart '$(unit)'."
              [corrected -- repair pass, see note below; this section
              previously read "cups.service" interpolated],
              polkit.gettext_domain = "systemd" — matching the real
              systemd request observed on the D-Bus wire in VM evidence
              (§13/W1-VM-007). Source-level, mechanically checkable: (a)
              action_id() and details() are both derived from `capability`
              alone with no other parameter available to influence them;
              (b) neither the action id nor any detail key/value can be
              supplied by a caller of RestartCapability or by any other
              external input; (c) there is no code path by which
              arbitrary detail insertion is possible (no `HashMap`
              parameter reachable from outside authorization.rs's own
              construction of the request).

              **Correction (repair pass, governed decision: runtime
              capture is authoritative)**: this ID's original text (and
              §7's/§10's worked examples above) recorded `polkit.message`
              as the unit name interpolated into the template
              (`"...restart 'cups.service'."`). The original
              implementation pass's own fresh VM re-capture
              (`docs/evidence/wave1/checkauth-comparison.md`) established
              that real Ubuntu 26.04.1 systemd never interpolates this
              field on the wire — it sends the literal, unsubstituted
              template `"Authentication is required to restart
              '$(unit)'."`; substitution is a presentation-layer behavior
              of the polkit authentication-agent UI, not something the
              `CheckAuthorization` caller (systemd) performs. The project
              owner adjudicated: Guardian's `ProviderAuthorizationRequest`
              must reproduce the literal template, not pre-interpolate
              it — implemented in
              `crates/guardian-core/src/authorization.rs`, re-verified
              with fresh native-vs-mediated real VM evidence showing exact
              semantic equality across every field
              (`docs/evidence/wave1/checkauth-comparison.md`'s
              "Resolution" section). `unit`, `verb`, and
              `polkit.gettext_domain` are unaffected by this correction.
W1-TXN-001 — guardian-daemon never calls RestartUnit, and never performs
             the mediated authorize_provider_request check; only
             guardian-helper does (source-level, mechanically checkable).
W1-TXN-002 — Systemd bus unreachable at Apply time reaches
             ProviderUnavailable/Failed, never a privilege escalation.
W1-TXN-003 — Two concurrent Restart requests for the same unit (Guardian
             + a real `systemctl restart`) do not both mutate
             independently — systemd's own job-merging is observed, not
             assumed (real VM evidence required).
W1-REC-001 — Crash before durable intent: SafeToResume, re-derived via
             the unmodified recovery.rs classifier.
W1-REC-002 — Crash after durable intent, before Apply: SafeToResume
             (ApplyOutcome::NotRecorded).
W1-REC-003 — Crash while the RestartUnit call itself is in flight and its
             outcome is durably uncertain: StateAmbiguous
             (ApplyOutcome::PartialOrUncertainMutation) — never
             MustObserve and never SafeToResume for this specific point.
W1-REC-004 — Crash after RestartUnit is believed to have returned but the
             response was lost or only confirmed then lost before Observe
             began: MustObserve (ApplyOutcome::ConfirmedSuccess |
             ResponseLostOrUnknown) — re-query resolves it. Distinct from
             W1-REC-003's genuinely in-flight case.
W1-REC-005 — Crash after Apply outcome recorded, before JobRemoved
             observed: MustObserve.
W1-REC-006 — Crash mid-Observe: StateAmbiguous, honestly reported, never
             guessed either direction.
W1-REC-007 — PostconditionNotMet triggers the BestEffort compensating
             restart, disclosed as such, never presented as a true
             rollback.
W1-REC-008 — The BestEffort compensating restart itself fails: the
             transaction reaches the real, existing RollbackFailed
             terminal state (never a fabricated RolledBack success, never
             an infinite retry loop); GuardianErrorCategory::
             RollbackFailed is surfaced to the caller; a later recovery
             pass over a RollbackFailed transaction reaches
             RequiresHumanRecovery via classify()'s existing fallback
             arm. Mirrors GuardedWrite's own already-accepted
             rollback_failure_during_recovery_is_surfaced_not_silently_
             successful fixture (crates/guardian-helper/src/main.rs) —
             no new G4 state, error category, or classification is
             introduced.
W1-REC-009 — Idempotency key prevents a retried Apply from double-issuing
             RestartUnit for the same transaction (reuses P0-TXN-009's
             mechanism).
W1-VM-001 — Real disposable-VM evidence: an authorized real caller's
            restart succeeds, observed via a real JobRemoved signal, with
            that caller's authorization coming from the real, unmodified
            org.freedesktop.systemd1.manage-units policy (not a
            Guardian-specific grant).
W1-VM-002 — Real VM evidence: a real, denied local user — denied under
            the real, unmodified manage-units policy, not a Guardian-
            specific one — is rejected by guardian-helper's own
            authorize_provider_request check; not merely a direct-to-
            systemd test, since that would not catch the relay defect
            the original design had.
W1-VM-003 — Real VM evidence: a local user who already has a real,
            pre-existing OS-level manage-units grant (independent of
            Guardian) is authorized through guardian-helper without any
            Guardian-specific grant existing — proving the mediated
            check is genuinely provider-policy-governed, not a second,
            independent gate.
W1-VM-004 — Real VM evidence: concurrent human-issued and Guardian-issued
            restart of the same unit, real observed outcome.
W1-VM-005 — Real VM evidence: guardian-helper crashed mid-Apply
            (simulated kill -9 at the right point where RestartUnit's
            call is genuinely in flight), real StateAmbiguous
            classification reproduced (not MustObserve), not merely
            unit-tested.
W1-VM-006 — Real VM evidence: the BestEffort compensating restart itself
            is made to fail (e.g. unit's ExecStart replaced with a
            failing command for the fixture), and the transaction is
            observed to reach RollbackFailed honestly rather than a
            false success — mirrors G7's own RollbackFailed VM/fixture
            evidence.
W1-VM-007 — Real VM evidence, detail-sensitive: an evidence-only (never
            packaged) systemd polkit rule is installed that grants
            manage-units only when unit == "cups.service" AND verb ==
            "restart" (real polkit .rules syntax over
            action.lookup("unit")/action.lookup("verb")). Using this
            rule, prove all of: (1) a direct systemd/systemctl restart
            of cups.service by an authorized real caller is authorized,
            as the baseline; (2) guardian-helper's mediated
            authorize_provider_request for the same real caller and the
            same capability produces the identical decision; (3) a
            variant of the rule keyed on a mismatched unit or verb
            denies the request, and guardian-helper's mediated check
            reproduces that denial too (not merely that some denial
            happens); (4) a caller granted only a hypothetical
            Guardian-owned action (never actually created, since none
            exists per W1-AUTH-005) could not substitute for this
            provider-policy grant -- i.e. the mediated check's outcome
            tracks only the real manage-units policy; (5) guardian-
            helper's own root/trusted identity is never sufficient by
            itself -- the check is against the real, resolved original
            caller in every case. The evidence must additionally capture
            and compare, side by side, the native systemd
            CheckAuthorization request (subject, action id, details,
            flags) against guardian-helper's mediated
            CheckAuthorization request for the same operation and
            caller -- any authorization-relevant divergence (subject
            semantics, action id, unit, verb, provider metadata,
            interaction flag) is a failure, not merely a mismatched
            final Authorized/Denied outcome.
```

**ID renumbering note**: an earlier version of this list included
`W1-VM-002b` as a sub-ID inserted between `W1-VM-002` and the old
`W1-VM-003`. An independent review found no precedent anywhere in the
project's accepted G0–G9 normative-ID history for a letter-suffixed
sub-ID, and recommended renumbering before implementation/evidence
artifacts start embedding it in filenames. That renumbering (`W1-VM-002b`
→ `W1-VM-003`, former `W1-VM-003`/`004`/`005` → `W1-VM-004`/`005`/`006`)
is preserved unchanged in this revision. A further independent review
then found a real provider-authorization-detail-fidelity defect
(§7/§50) and required two new IDs, appended sequentially rather than
inserted mid-range: `W1-AUTH-007` and `W1-VM-007`. This list is the sole
authoritative enumeration — do not re-derive IDs from range shorthand
elsewhere in this document or in the independent-review handoff.

**Full enumeration (30 IDs, no duplicates, no gaps, no letter suffixes,
no `P2-*`)**:
```text
W1-MUT-001, W1-MUT-002, W1-MUT-003, W1-MUT-004,
W1-AUTH-001, W1-AUTH-002, W1-AUTH-003, W1-AUTH-004, W1-AUTH-005, W1-AUTH-006, W1-AUTH-007,
W1-TXN-001, W1-TXN-002, W1-TXN-003,
W1-REC-001, W1-REC-002, W1-REC-003, W1-REC-004, W1-REC-005, W1-REC-006, W1-REC-007, W1-REC-008, W1-REC-009,
W1-VM-001, W1-VM-002, W1-VM-003, W1-VM-004, W1-VM-005, W1-VM-006, W1-VM-007
```
(`W1-MUT: 4, W1-AUTH: 7, W1-TXN: 3, W1-REC: 9, W1-VM: 7` = **30 total**.)

# 13. Evidence ladder

```text
Layer 1 (pure Rust): ProviderAuthorizationRequest::SystemdRestart's
  action_id()/details() mapping (all four evidenced fields, derived from
  a fixture RestartCapability, never a literal caller-suppliable input),
  capability_id-to-unit resolution, recovery classification for every
  crash point above (including the corrected W1-REC-003/W1-REC-004 split
  and W1-REC-008's rollback-failure path), idempotency-key logic,
  error-category mapping — no system bus.
Layer 2 (private D-Bus / a real dbus-daemon-backed mock systemd1 service,
  matching guardian-testkit's existing PrivateSessionBus pattern): the
  authorize_provider_request call (action id
  "org.freedesktop.systemd1.manage-units", with its full details map)
  sequenced correctly *before* RestartUnit, RestartUnit call sequencing,
  JobRemoved signal handling, a deterministic mock Authorizer for the
  Denied/AuthenticationUnavailable paths, and a mock capable of asserting
  on the exact details map it received (to catch a future regression to
  empty/partial details).
Layer 3 (mocked hardware): not required — this capability touches no
  hardware device.
Layer 4 (disposable Ubuntu 26.04.1 VM, real systemd, real polkit — using
  systemd's own already-shipped org.freedesktop.systemd1.policy, no
  Guardian-authored .policy fixture needed for this capability's
  authorization *action* — but a real, evidence-only, never-packaged
  detail-sensitive polkit .rules fixture for W1-VM-007 — real
  cups.service or equivalent, at least three real distinct local users:
  one granted manage-units by real OS-level polkit config, one denied,
  and one used for W1-VM-003's pre-existing-grant proof): every W1-VM-*
  ID above, in particular W1-VM-002/W1-VM-003's corrected authorization
  tests (against guardian-helper's own mediated check of the real
  provider action, not a direct-to-systemd call and not a Guardian-owned
  action), W1-VM-006's real rollback-failure reproduction, and
  W1-VM-007's real native-vs-mediated request comparison under a
  detail-sensitive rule. This is where Wave 1's acceptance is actually
  earned — no Layer 5 required.
Layer 5 (physical hardware): explicitly not required to close Wave 1,
  matching §50's acceptance-bar requirement directly.
```

# 14. Scope exclusions (restated from §50, binding on implementation)

Do not, under this handoff: implement I/O Guardian (master-spec Phase
2); implement TDD-contract Phase 2 read-only observability/correlation;
implement any other master-spec capability family; add a client-facing
write UI; extend the Provider Arbitrator; invent a new `GuardianDbusError`
category; add a new `PolkitAction` variant or a new Guardian-authored
`.policy` action for this capability (§7's corrected relay-authorization
rule forbids it for a provider-owned capability that already has a real
action to mediate — `ProviderAuthorizationRequest` is the only sanctioned
representation of it); add any `ProviderAuthorizationRequest` variant
beyond `SystemdRestart`, widen `details()`/`action_id()` to accept an
external parameter, or add a generic `authorize_provider(action_id: &str,
details: HashMap<String, String>, ...)`-shaped interface, without its
own governed gate/review; ship the mediated check with an empty or
partial details map (§7/§50 — fidelity to the evidenced four-field
request is required, not optional); add a `RestartCapability` row beyond
the single governed `cups-restart` row without its own governed
gate/review (§10); accept a caller-supplied unit name, operation, action
id, or detail key/value through `RestartCapability` in any form (§10 —
`capability_id` only); package the evidence-only, detail-sensitive
polkit `.rules` fixture used for `W1-VM-007` as production policy;
restart `guardian-daemon`/`guardian-helper` themselves as part of this
capability's table; touch any G0–G9 provider read logic beyond reusing
it unmodified.

# 15. Non-blocking backlog, explicitly not pulled into this work

Per the publication record (`docs/evidence/g9/G9_MILESTONE.md`): tray
glyph rendering, `PrivateSessionBus`'s unbounded read, the TUI's fixed
~300ms `pkttyagent` wait and imperative cleanup, `StateDirectoryMode`,
the ADR-006 ownership addendum. None of these are prerequisites for Wave
1 and none is touched by it.
