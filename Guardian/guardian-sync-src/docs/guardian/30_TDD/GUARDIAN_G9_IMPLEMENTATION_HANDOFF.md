# Guardian Phase 1 Implementation Handoff
## G9 — Clients & Packaging

Baseline: HEAD `3384ed7ededdce8067d6e8615f4e0a7dc5799d2a` ("docs: define
G9 clients & packaging gate"). **G8 is closed**: independently accepted,
committed at `acee16c`, tagged `phase0-g8-initial-providers`, and
published (`git rev-parse origin/main` includes both commits). G9's own
scope does not touch G8's provider code.

**Repair note (this revision):** an independent planning review of the
prior revision of this handoff returned `FAIL — G9 PUBLIC API PLAN
AMBIGUOUS`, with two further blockers on packaging/privilege and
toolkit/session-autostart that would independently have failed on their
own. All three are repaired below, grounded in two new decision
records this repair adds: `docs/adr/ADR-007-guardian-gui-tui-client-separation.md`
(GUI = GTK4/libadwaita via `gtk4-rs`, TUI = `ratatui`, both decided now
rather than left to implementer discretion) and
`docs/adr/ADR-008-guardian-package-filesystem-layout.md` (which promoted
G7 artifacts are packaged verbatim, which one file — the G7 evidence-
only polkit bypass rule — must never be packaged, and the exact
session-autostart mechanism and vendor path). The review's other
findings (write-capability adjudication, five-surface set, G6/indicator
reuse, `Guardian1` freeze, dropping `RequestTransaction`, incident/
transaction scope) were confirmed sound and are unchanged.

# 1. The central planning finding — read this before anything else

**G9 has nothing real to write yet, and must not invent something to
write just to give its clients a demo.**

Mechanically checked against every prior gate's own disposition — and
corrected once already by an independent planning review that found the
first draft of this finding overstated its own premise:

- G8 is **read-only by explicit, audited, re-verified construction** —
  contract §26/§27/§28 defer `UDisks2.PowerOff()`,
  `AccountsService.SetSession()`, and all systemd/logind mutation to
  later phases. Every `CapabilityRecord` G8 populates has
  `write_support: false`. This part of the finding is unqualified: no
  G8-registered capability is writable.
- **Correction — a real write path does exist, and the finding must not
  imply otherwise.** `guardian-helper` (G7, tagged
  `phase0-g7-production-daemon`) exposes a real, live, callable
  production D-Bus method, `GuardianHelper1.GuardedWrite(interactive:
  bool) -> u64`, driving the complete real G4 transaction lifecycle
  (Snapshot→Validate→Authorize→Apply→Observe→Confirm/Rollback) against
  `CounterAdapter` — a real, persistent, idempotent, polkit-authorized
  mutation (it increments a real counter file on disk). This is not a
  disposable prototype; it ships in production `guardian-helper` today.
  An independent planning review of this handoff found and required this
  correction.
- The reason G9 still must not wire a client-facing "request
  transaction" affordance to `GuardedWrite` is **not** that no real
  write path exists — it is that `GuardedWrite`/`CounterAdapter` is, in
  G7's own milestone's words, "the sole Class A privileged mutation
  this evidence build exposes": a fixture built to prove the Class A
  architecture works end-to-end for G7's own audit, not a capability
  that corresponds to any real Guardian feature a user would recognize,
  and it is not represented anywhere in G8's Capability Registry.
  Presenting "increment an internal evidence counter" as a real Guardian
  capability in the GUI/CLI would itself be exactly the kind of fake
  functionality masquerading as a working feature AGENTS.md's "No
  placeholders" section forbids — just approached from the opposite
  direction than the danger this finding originally warned about.

So the precise, corrected premise is: **no real write-capable capability
exists that corresponds to a meaningful, real-world Guardian feature.**
When contract §31 says clients MAY "request transactions" and §32/§33
require the GUI/TUI to demonstrate "transaction history," the honest
Phase-1 reality is: **there is no real, user-meaningful transaction to
request, and the transaction history view will show a real, correctly-
rendered empty list.** G9's job is to build the **real, structurally
complete, honestly-empty** client-facing wiring for this — not to
fabricate a toy write-capable capability ("Guardian can toggle a dummy
setting!") merely so the demo has something to click, and not to wire a
"request transaction" button to `GuardedWrite` either, since that would
surface an internal test fixture as if it were a real feature. If the
implementer finds themselves adding *any* new capability with
`write_support: true`, or any client-facing call into `GuardedWrite`, to
make a client feature look alive, stop — that is out of G9's scope and
belongs to whichever future wave gate actually earns a real capability
through the full Snapshot→Confirm discipline against a real provider.

**Concretely: `Transactions1` (§6 below) must be read-only/list-only
this gate.** Do not add a `RequestTransaction` method at all, structural
or otherwise — there is nothing real for it to front yet, and a method
that can only ever return "no write-capable capability exists" is
scope this gate does not need and a signature a future gate would
inherit before any real capability existed to shape it.

This reframes every "client acceptance" requirement in §31-34 as an
**honest-rendering** requirement, not a **feature-completeness**
requirement: the GUI/TUI/CLI must correctly show "0 transactions," "0
incidents" (unless G3's incident model has real incidents from some
other real source — check before assuming empty), real capability/
provider state from G8, and a real daemon-connectivity signal. That is
the actual, evidence-grounded Phase-1 client surface.

# 2. Mission

Build the five required Phase 1 client/packaging surfaces (§38 G9
subsection) as **thin** clients (§31) over the existing, unchanged
daemon/provider/transaction stack, adding only the minimum new
`Guardian1`-adjacent D-Bus surface (§7.1/§7.2's illustrative
`Capabilities1`/`Incidents1`/`Transactions1` shape) required for those
clients to have real data to render — nothing else. G9 does **not**
implement any new provider, any new write capability, any Phase 2
correlation feature, or any polish beyond "shell" (§32's own words).

# 3. Normative IDs — exact, mechanically re-derived matrix

Re-derived directly from contract §37 "P1-CLIENTS" and "P1-PACKAGING"
subsections (the prompt's own suggested ID list was cross-checked
against this and matches exactly — 12 IDs, not more, not fewer):

| ID | Requirement (verbatim intent) |
|---|---|
| P1-CLI-001 | CLI structured output parses as valid JSON |
| P1-CLI-002 | CLI returns deterministic exit/error behavior when daemon is unavailable |
| P1-TUI-001 | TUI starts without a graphical session (VT) |
| P1-GUI-001 | GUI renders available/degraded/unavailable providers |
| P1-GUI-002 | GUI renders transaction records from daemon state |
| P1-IND-001 | Indicator renders healthy state |
| P1-IND-002 | Indicator renders offline/degraded state without hanging |
| P1-PKG-001 | Fresh Ubuntu 26.04.1 VM install succeeds |
| P1-PKG-002 | Installed service/D-Bus/polkit files are in correct vendor locations |
| P1-PKG-003 | Uninstall removes package-owned files without deleting user/admin state unless explicitly purging |
| P1-PKG-004 | Purge semantics are documented and tested |
| P1-PKG-005 | Guardian does not modify another package's files during normal install |

**Not G9's IDs, mechanically excluded:** `P1-DMN-*` and `P1-SEC-*` are
explicitly assigned to G7 (already closed) by §38's own G7 subsection —
G9 must not re-litigate or re-prove them, only avoid regressing them.
`P0-IND-001..003` are G6's (already closed, `phase0-g6-indicator-
decision`, ADR-006) — G9 reuses that decision, see §8 below. `P1-SYS/
PSI/LGI/UDS/UPW/ACC-*` are G8's.

§34's "minimum commands equivalent to: `guardian status`, `capabilities`,
`providers`, `incidents`, `blockers`, `psi`, `transactions`" is binding
even though it has no dedicated `P1-CLI-0NN` ID per command — treat it as
part of P1-CLI-001's "structured output" requirement (each command's
JSON mode must itself be valid JSON) plus a general CLI-completeness
check the completion report must state explicitly.

# 4. Client/packaging surface set — deliberately minimal

Exactly five, matching §38's G9 subsection precisely:

1. **CLI** — `guardian` binary, human + JSON output modes.
2. **TUI** — terminal shell, VT-runnable, no desktop dependency.
3. **GUI shell** — §32's explicit "shell, not the finished Guardian
   dashboard."
4. **Indicator** — `ksni`-based (G6/ADR-006), real production
   integration (not the disposable spike).
5. **Debian package** — `.deb`, correct vendor paths, install/uninstall/
   purge.

Do not add: a web UI, a mobile client, a plugin system, a themeing
engine, localization infrastructure, or any client beyond these five.
Do not add Snap/Flatpak/AppImage packaging — only the Debian package
§38/§39 name.

# 5. Component roles (unchanged from G7/G8 — restated for this gate's context)

- `guardian-daemon` (unprivileged, Class C) — gains the new read-only
  `Capabilities1`/`Incidents1`/`Transactions1` D-Bus surface (§6 below).
  Still never proxies to `GuardianHelper1`; G9 adds no new caller of the
  helper.
- `guardian-helper` (privileged) — **untouched**. No G9 client ever
  talks to it directly (§31: "Clients MUST NOT ... call `sudo`" — the
  helper is `guardian-daemon`'s exclusive privileged-mutation path, and
  G9 clients only ever talk to `guardian-daemon`).
- `guardian-core` — gains no new logic for this gate beyond whatever
  small, honestly-typed view models the new D-Bus surface needs to
  serialize G3/G4/G8's existing types (see §6.3) — never a duplicate of
  the Capability Registry, event/incident model, or transaction engine.
- New crates this gate: `guardian-cli`, `guardian-tui`, `guardian-gui`,
  `guardian-indicator`, plus packaging metadata (`debian/` or
  equivalent) at the workspace root. Each is a genuinely separate,
  independently buildable client binary — never one monolithic "clients"
  crate with feature flags standing in for real separation, matching
  this project's own established "no giant generic framework" discipline
  applied to client architecture instead of provider architecture.

## 5.1 Toolkit selection — resolved by ADR-007

**Repaired.** The prior draft's search for an existing toolkit decision
checked only the contract and `Client_Surfaces.md`, missing that
`docs/guardian/00_Project/GUARDIAN_MASTER_SPEC.md` (governance rank 4)
already names GTK4/libadwaita and `ratatui` — real context, but not
itself an accepted architectural decision (it is explicitly hedged).
Per contract §43, this decision belongs in the named record
`ADR-007 GUI/TUI client separation`, not an unnumbered ad hoc ADR.

**`docs/adr/ADR-007-guardian-gui-tui-client-separation.md` is now
accepted, written as part of this repair.** GUI = GTK4 + libadwaita via
`gtk4-rs`; TUI = `ratatui`. Both chosen with real alternatives
considered (`egui`/`iced` for GUI, `cursive` for TUI) and grounded in
the master spec's own reference-UI comparison point and Guardian's
thin-client/single-toolchain discipline — read the ADR for full
reasoning. G9 implementation MUST follow this decision, not re-open it;
if real implementation evidence finds either choice genuinely
insufficient, that is a finding for a future gate to supersede with
real comparative evidence, not a mid-implementation swap.

# 6. Public D-Bus surface expansion — the actual new production work

This is the largest genuinely new production surface since G0, and the
part most likely to attract scope creep. Ground every design choice in
§7.1's illustrative shape and §7.2's illustrative object hierarchy —
"illustrative" means the exact interface/method names are not binding,
but the **shape** (separate interface majors per concern, stable
introspectable object hierarchy) is.

## 6.1 What must exist — fixed now, not left to implementer discretion

An independent planning review found the prior draft left the exact
interface/object/member list, and the justification for each interface,
to the implementer ("or equivalently-shaped naming the implementer
selects," "or a small fourth [interface]"). Per §7.3 these are one-way
doors (removal/renaming requires a new interface major), so this
repair fixes the list now, citing ADR-001's own naming precedent and
distinguishing this proposal from the one prior-gate precedent that
matters: **G7's own independent audit struck an earlier
`Guardian1.Transactions1` addition as "an unjustified permanent
production API addition"** (`docs/evidence/g7/G7_MILESTONE.md`,
Round 1 finding). That removed interface carried a *write* method
(`AttemptProviderDelegatedWrite`); the one below carries none — but the
name recurring means this handoff must explicitly justify why minting
it now is different, not silently reuse a name a prior audit rejected.

**Exactly three interfaces, fixed:**

- **`io.github.cliffthelin.Guardian.Capabilities1`** at
  `/io/github/cliffthelin/Guardian1/Capabilities` (ADR-001's own
  worked example, cited verbatim). One method,
  `ListCapabilities() -> a(...)`, serializing the real, live G8
  Capability Registry snapshot directly (§6.3). **Justification:**
  P1-GUI-001/P1-CLI-001 require rendering real capability state; no
  weaker alternative exists since this is the only real store G9 needs
  to expose. Also carries the read-only PSI summary (§32) as a second
  method, `PsiSummary() -> (...)`, reusing G8's real `providers::psi`
  reads directly — folded in here rather than minting a fourth
  interface, since PSI is itself one of G8's six capability domains.
- **`io.github.cliffthelin.Guardian.Incidents1`** at
  `/io/github/cliffthelin/Guardian1/Incidents`. One method,
  `ListIncidents() -> a(...)`, serializing G3's real `Incident` type
  (§6.3). **Finding, not an exercise for the implementer:** mechanically
  checked directly (`grep -rn 'Incident {' crates/*/src/`) —
  **nothing in production anywhere constructs an `Incident`.** No
  incident producer or persistence path exists in this codebase as of
  G9's start. `ListIncidents()` therefore returns a real, live, always-
  empty list in this gate — genuinely queried, not hardcoded, so a
  future gate that does add a producer needs no interface change, only
  a populated backing store. **Do not build an incident store to make
  this list non-empty** — that is Phase 2 correlation scope (§47) and
  explicitly out of bounds for G9.
- **`io.github.cliffthelin.Guardian.Transactions1`** at
  `/io/github/cliffthelin/Guardian1/Transactions`. One method,
  `ListTransactions() -> a(...)`, list-only, no write/request method of
  any kind (§6.2). **Finding, not an exercise:** the daemon binary
  today has zero transaction persistence — `grep -rn 'transactions_dir'
  crates/` shows this exists only in `guardian-helper`, under
  `root:root` ownership. `ListTransactions()` serves the **daemon's
  own** transaction state (real, live, currently empty), never
  helper's. **Two paths are explicitly forbidden, by name, for
  populating this interface, because either would breach G7's
  independently-evidenced privilege separation:**
  1. `guardian-daemon` reading `/var/lib/guardian/helper/` in any form
     (the directory's real mode is `0750 root:root`; G7's own VM
     evidence proved `guardiand` cannot read it — this must remain
     true after G9);
  2. `guardian-daemon` constructing any new proxy/call into
     `GuardianHelper1` to read transaction data (§5 already forbids
     writing to it; this extends the same prohibition to reads).

  If a future gate needs real cross-process transaction visibility, it
  must design that deliberately (e.g. a narrow, explicitly-authorized
  read-only helper method, evidenced the way `GuardedWrite` itself was)
  — G9 does not improvise it to make an empty list look more populated.

## 6.2 What must not exist

- Any method that mutates anything (no `RequestTransaction`-that-
  actually-does-something, no capability toggle, no provider control).
  **Do not add a `RequestTransaction` method at all this gate, not even
  structurally.** An independent planning review of this handoff
  rejected the earlier draft's "MAY exist structurally, must return a
  typed no-capability result" allowance: there is nothing real for such
  a method to front, it is scope this gate does not need, and it would
  hand a future gate a method signature designed before any real
  capability existed to shape it. `Transactions1` is list-only (§6.1).
  This also forecloses any client-facing call into `guardian-helper`'s
  real `GuardedWrite` method (§1) — that method is a G7 evidence
  fixture, not a Guardian feature, and no G9 surface may call it.
- Any expansion of `Guardian1` itself beyond what G0 froze
  (`ContractVersion`/`ServiceState`) — new capability/incident/
  transaction surfaces belong on their own separate interface majors
  per §7.1's own illustrative shape, not bolted onto `Guardian1`.
- Any generic/dynamic method-name dispatch, any "call any provider
  method" broker — the same forbidden-shortcuts discipline (§40) that
  governed every provider adapter in G8 applies identically here to the
  client-facing surface.

## 6.3 Serialization discipline

Reuse `guardian-provider-api`'s existing typed `CapabilityRecord`,
`Knowledge<T>`, `Availability`, `Health`, etc. directly in the D-Bus
signature (via `zbus`'s typed `Type`/`Serialize` derives) rather than
hand-rolling a second, parallel wire schema — the same "reuse the
existing model, do not fork it" discipline G8 applied to `psi.rs`
applies here to G3's/G8's own data models.

# 7. Per-surface acceptance contracts

## 7.1 CLI (§34)

Minimum commands: `status`, `capabilities`, `providers`, `incidents`,
`blockers`, `psi`, `transactions`. Every command supports a
machine-readable (JSON) mode; JSON output must be genuinely valid JSON
(P1-CLI-001) — do not hand-format JSON strings, use a real serializer.
Daemon-offline behavior (P1-CLI-002) must be a real, deterministic,
documented exit code + message, exercised against a genuinely-stopped
daemon, not simulated.

## 7.2 TUI (§33)

Must run from a bare VT (no `DISPLAY`/`WAYLAND_DISPLAY`, no desktop
session) — prove this with real evidence, not an assumption that a
terminal-only crate "should" work headless. Displays the same
capability/incident data as the GUI "at a basic level" — reuse the same
D-Bus client code the CLI/GUI use, never a third independent parsing
path. Must "exercise text polkit in a test action" — this reuses G1's
already-accepted text-polkit path; G9 does not redesign authorization,
only calls into it from a new client.

## 7.3 GUI shell (§32)

Explicitly a shell: daemon connection state, overall Guardian state,
capabilities list, provider ownership details, incidents list, current
system blockers, read-only PSI summary, transaction history view,
graceful provider-unavailable state. No visual polish requirement. Do
not build more than this list.

## 7.4 Indicator (§30's required tests, now exercised for real — see §8)

Icon appears; menu opens; menu actions invoke the client-side handler;
state/icon update propagates; no X11 dependency; reconnect after panel/
Shell restart; reconnect after daemon restart; daemon-unavailable shows
degraded state; no duplicate icon; clean logout/login lifecycle. These
are the *same* required behaviors G6 already spike-tested — G9's job is
proving them again against **real** `guardian-daemon` data (not G6's
disposable stub), which is exactly why `P1-IND-001`/`002` exist as
separate IDs from G6's `P0-IND-*`.

## 7.5 Packaging (§38 P1-PKG-*) — resolved by ADR-008

**Repaired.** `docs/adr/ADR-008-guardian-package-filesystem-layout.md`
is now accepted and is the binding source of truth for every packaged
file. Implementation must follow it exactly, in particular:

- `debian/guardian-daemon.service`/`guardian-helper.service` are
  promoted **byte-identical** (modulo `ExecStart=` path) from
  `docs/evidence/g7/guardian-{daemon,helper}.service` — the exact units
  G7's independent audit measured with `systemd-analyze security`. Do
  not hand-write fresh units.
- `debian/io.github.cliffthelin.guardian.g7.policy` is promoted
  unchanged from `docs/evidence/g7/` (safe `allow_*=no` defaults).
  **`docs/evidence/g7/50-guardian-g7.rules` MUST NEVER be packaged** —
  it is a VM-evidence-only bypass rule granting a hardcoded test
  account unconditional access to the privileged write action. The
  completion report must show `dpkg -c` output confirming its absence.
- `debian/io.github.cliffthelin.{Guardian1,GuardianHelper1}.conf`
  promoted unchanged from `docs/evidence/g7/` to
  `/usr/share/dbus-1/system.d/`.
- State directories/system-user creation, purge-vs-remove semantics,
  and the session-autostart mechanism/vendor path (§8/§9 below) are
  all fixed in ADR-008 — do not re-decide any of them here.

**Preserve G7's disjoint-ownership/privilege separation in the package
itself.** The `.deb` MUST install each binary with the correct systemd
unit `User=`/`Group=` and correct filesystem ownership per binary, and
MUST NOT merge, share, or weaken this separation for packaging
convenience — verify this with real, post-install `ls -l`/
`systemctl show`/`systemd-analyze security` evidence in the VM
(re-measuring, not merely re-installing the same units and assuming),
not by assuming the promoted unit files alone are sufficient proof.

# 8. Indicator reuse discipline — do not re-litigate G6

G6 already selected `ksni` (direct Rust SNI + canonical DBusMenu) with
real, repaired, twice-audited evidence (ADR-006, `docs/evidence/g6/`).
G9 MUST:

- Reuse that decision as given — no re-running the three-candidate
  comparison, no re-opening "should we reconsider Ayatana GTK3."
- Build `guardian-indicator` as **real production code** using `ksni`,
  informed by (but not copy-pasted wholesale from) the disposable
  `tests/vm/g6-candidate-ksni/` prototype — that prototype was
  explicitly never meant to be merged into production, matching every
  other gate's disposable-prototype precedent (G2 Model A/B, G7 Class B).
- Wire the indicator to **real** `guardian-daemon` state via the new
  D-Bus surface (§6), not to G6's stub/fixture data.

If real G9 evidence finds a genuine defect in the G6 decision itself
(not just "the prototype needs production hardening," but "the decision
was actually wrong") — stop and report it as a prior-gate regression
finding, do not silently re-decide.

**Documented discrepancy (found by independent planning review, recorded
per AGENTS.md's source-drift rule rather than silently resolved):**
ADR-006 itself states "G7 must build its own production indicator
daemon using `ksni`." This conflicts with contract §38's explicit
assignment of `P1-IND-001..002` to G9, not G7. Per AGENTS.md's
governance order, the TDD contract ranks above ADRs — **G9, not G7,
owns building the production indicator**; ADR-006's "G7+" phrasing
predates the contract's final gate assignment and should be read
informally, not literally. This handoff does not attempt to silently
rewrite ADR-006 (per AGENTS.md: "Do not rewrite historical accepted ADR
rationale to hide an earlier decision; supersede it") — a short
addendum to ADR-006 noting this gate-ownership correction should be
added alongside G9's implementation, not before.

**Forward constraint from ADR-006, restated because the handoff must
not let it go unstated:** "The production indicator must be launched
via proper desktop session autostart (cleaned up by `systemd-logind` on
logout), not as a detached background process" — ADR-006's own words,
recorded after a real Xfce stale-registration defect
(`G6_LOGOUT_LOGIN_LIFECYCLE_EVIDENCE.md`) caused by exactly this
mistake. **Repaired — mechanism decided, not left open.** Per
ADR-008 §5, `guardian-indicator` MUST be launched via a real XDG
autostart `.desktop` entry at `/etc/xdg/autostart/guardian-indicator.desktop`
— not a systemd `--user` unit (rejected in ADR-008 precisely because
GNOME's and Xfce's `graphical-session.target` integration are not
equivalent, the exact per-desktop discrepancy ADR-006's own evidence
history warns about). This applies identically in production packaging
and VM evidence gathering — never via a detached SSH background process
(`nohup ... &`) during evidence collection, which would look passing
without proving real session lifecycle behavior. VM evidence must
include a real logout with real process inspection confirming no
orphaned indicator process survives (ADR-008 §5).

# 9. Forward constraints from prior gates — confirm, do not close

Restate and re-verify, do not silently claim closed:

- **G4 FC-3** (Flight Recorder / transaction persistence independence) —
  unchanged; G9 reads transaction history, never writes to its
  persistence layer.
- **G5 FC-2** (RecorderPolicy runtime wiring) — remains open; G9 adds no
  spill/retention sink.
- **G7 SafeToResume/idempotency** — deferred; G9 introduces no new write
  path, so nothing new to prove here.
- **G8's own forward constraints** (single-writer not yet triggered,
  `Knowledge::Unknown` for unevidenced authorization ownership,
  `write_support: false` on every real capability) — G9's new
  `Capabilities1` surface must **honestly reflect** these, not paper
  over them with a friendlier-looking client-side default. If the GUI
  shows a capability, it must show its real `write_support: false` and
  real `Knowledge::Unknown` authorization ownership, not omit them.

# 10. Testing ladder (§35, mapped to G9)

```text
Layer 1 (pure Rust): CLI JSON-serialization correctness, TUI/GUI view-
  model construction from typed CapabilityRecord/Incident/Transaction
  data, indicator menu-model construction, D-Bus surface's typed
  request/response (de)serialization. No system bus.
Layer 2 (private D-Bus / dbusmock or a private guardian-daemon test
  instance): daemon-offline CLI/TUI/GUI behavior, malformed/partial
  Capabilities1 responses, indicator daemon-restart-while-alive
  reconnect (reusing G6's own corrected methodology — the daemon
  restarts, the indicator process does not).
Layer 3 (mocked hardware): not newly required by G9's own scope — G8
  already owns UDisks/hardware mocking; G9 clients only render what G8
  already reports.
Layer 4 (disposable Ubuntu 26.04.1 VM): real GNOME 50/Wayland and real
  Xfce 4.20 indicator rendering (§30's required tests, now against real
  daemon data); real VT-only TUI session; real fresh-VM package
  install/uninstall/purge; real daemon-online and genuinely-stopped-
  daemon CLI/TUI/GUI runs.
```

# 11. Real-VM evidence plan

A fresh disposable VM (or two, if GNOME and Xfce cannot coexist cleanly
in one) must produce, at minimum:

- Real `.deb` build and real `apt install ./guardian*.deb` (or
  equivalent) on a clean Ubuntu 26.04.1 image.
- Real vendor-path verification (`dpkg -L`, direct filesystem checks).
- Real uninstall, then real purge, each checked against what user/admin
  state should and should not survive.
- Real indicator icon/menu evidence on GNOME 50/Wayland, real indicator
  icon/menu evidence on Xfce 4.20 (screenshots or equivalent structured
  evidence — text-only D-Bus introspection is not sufficient proof an
  icon visually appeared).
- Real daemon-restart-while-indicator-alive reconnect, on both desktops.
- Real CLI/TUI/GUI runs against a live daemon, and again against a
  genuinely-stopped daemon, capturing real exit codes/messages/rendered
  states.
- Real VT-only TUI session (no desktop, no `DISPLAY`).

Do not fabricate VM evidence; do not present host-generated output as
guest evidence (the same requirement the G8 independent audit enforced).

# 12. Scope boundary — explicit exclusions

Do not implement, in this gate:

- Any new provider or provider capability (G8's set is closed for this
  phase; new providers are a future-wave concern).
- Any real write-capable transaction (§1's central finding).
- Any Phase 2 correlation/observability feature (§47: Phase 2 is a
  separate future planning input, explicitly gated behind Phase 1's
  full exit criteria, which include G9 itself).
- Snap/Flatpak/AppImage or any packaging format beyond the Debian
  package §38/§39 name.
- Visual polish beyond "shell" (§32).
- A redesign of G1's authorization flow, G4's transaction engine, or
  G6's indicator-mechanism decision — G9 consumes all three as given.

# 13. Completion states

Exactly one of:

```text
G9 CANDIDATE — CLIENTS & PACKAGING READY FOR INDEPENDENT AUDIT
G9 PARTIAL — REQUIRED CLIENT/PACKAGING EVIDENCE INCOMPLETE
G9 BLOCKED — PRIOR-GATE REGRESSION DISCOVERED
G9 BLOCKED — CONTRACT/INTERFACE INSUFFICIENT
G9 BLOCKED — WRITE-CAPABLE SCOPE REQUIRED BY NORMATIVE CONTRACT
```

# 14. Completion report requirements

Must include, at minimum: git state; every changed/new file with any
unreported/unexpected/prior-gate-production file flagged explicitly;
the 12-ID normative matrix (production path | automated test | mock
evidence | VM evidence | result) for every ID in §3; the new D-Bus
surface's exact final shape (interface names, object paths, method/
property list) with an explicit statement of what is and is not
populated with real data; the §1 central-finding disposition restated
(confirm no fabricated write capability was introduced); indicator
reuse-not-relitigation confirmation; packaging install/uninstall/purge
evidence; the five-provider... **five-surface** resilience matrix
(daemon online/offline × each of CLI/TUI/GUI/indicator); forward-
constraint confirmations (§9); full `cargo fmt --check`/clippy/`cargo
test --workspace` validation with exact before/after counts; explicit
confirmation that `Guardian1` itself remains exactly `ContractVersion`/
`ServiceState`, with all new surface on separate interface majors; and
one of the completion-state strings in §13.

Do not commit. Do not push. Do not tag G9. Do not begin any Phase 2
work. Do not push until an independent audit accepts the candidate.
