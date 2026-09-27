# ADR-007: Guardian GUI/TUI client separation and toolkit selection

- Status: Accepted
- Date: 2026-09-02
- Governing gate: G9 — Clients & Packaging (contract §43 requires this record
  "before Phase 1 completion"; G9 is the last Phase 1 gate per §46)

## Context

Contract §43 requires an `ADR-007 GUI/TUI client separation` decision record
before Phase 1 completion. An independent planning review of the G9
implementation handoff found the handoff's own toolkit-ADR requirement was
based on an incomplete search: it checked only the TDD contract and the
`Client_Surfaces.md` wiki page and concluded "no prior ADR selects one,"
missing that `docs/guardian/00_Project/GUARDIAN_MASTER_SPEC.md`
(AGENTS.md governance rank 4, below the contract, the current gate
handoff, and accepted ADRs) already names a preferred stack in four
places:

> "GUI/TUI/CLI/indicator ... can be Rust (GTK4-rs, Ratatui) for one shared
> language, or a lighter frontend language if that's faster to ship" (line 7)
>
> "`guardian-gui` | GTK4/libadwaita control center (GNOME + Xfce)" (line 32)
>
> "GTK4 shell skeleton, TUI skeleton" listed under Phase 1 (line 206)
>
> GTK4/libadwaita package dependencies listed (line 265)

Per AGENTS.md's source-of-governance order, the master spec's preference
is real context but is **not** itself an accepted architectural decision —
it is explicitly hedged ("or a lighter frontend language if that's faster
to ship") and sits below the contract, the gate handoff, and accepted
ADRs. Following G6's own precedent (ADR-006 was the deliverable of a
real, evidence-based decision gate, accepted **before** any production
indicator code existed — "This ADR does not authorize building the G7+
production indicator... G7 must build its own production indicator
daemon... subject to normal G7 TDD discipline, not by promoting any
spike artifact"), G9's GUI/TUI toolkit choice needs the same kind of
recorded, evidence-grounded decision, not an implementer's ad hoc pick
buried in code.

Unlike G6, this decision does not require a multi-desktop comparative
VM spike: the candidates are well-established, singular per surface (no
genuine multi-way technical uncertainty comparable to G6's three
indicator mechanisms), and the master spec's own hedge ("GTK4-rs,
Ratatui... or a lighter frontend language if that's faster to ship") is
itself evidence that no prior real evaluation was performed — this ADR
performs that evaluation now, narrowly, against Guardian's actual
constraints (thin-client discipline, Rust workspace, no new IPC
mechanism, GNOME 50 + Xfce 4.20 target desktops).

## Decision

**GUI: GTK4 + libadwaita, via `gtk4-rs`.** Rationale:
- Matches the master spec's own stated preference and the reference UI
  ("Resources," Ubuntu 26.04's own Rust/GTK4/libadwaita system monitor)
  the spec explicitly calls out as "a genuinely good UI reference to
  study, not duplicate" — directly relevant since G9's GUI shell
  (contract §32) is itself a system-state dashboard.
- Native on the GNOME 50 target desktop; well-supported on Xfce 4.20
  (GTK4 apps run natively on Xfce; no compatibility shim required).
- One shared language with the rest of the Rust workspace — no FFI
  boundary, no second build toolchain, no new IPC mechanism to reach
  `guardian-daemon` (the same `zbus` client code CLI/TUI use).
- Consistent with G6's own accepted finding that a GTK dependency is an
  acceptable, evidenced cost for a UI surface (G6 rejected the legacy
  GTK3 Ayatana binding for the **indicator** specifically because
  linking full GTK3 merely to build one `GtkMenu` struct was
  disproportionate to that surface's actual need — that reasoning does
  not transfer to the GUI shell itself, whose entire job is to be a
  real desktop application window).

**TUI: `ratatui`.** Rationale:
- Matches the master spec's own stated preference.
- Actively maintained, the de facto standard Rust TUI crate, no
  meaningful competing candidate with a materially different
  cost/benefit profile for Guardian's narrow shell requirements (§33).
- Pure Rust, no external system dependency beyond a terminal — directly
  supports P1-TUI-001's bare-VT requirement.

**Client separation.** GUI and TUI are separate crates
(`guardian-gui`, `guardian-tui`), each depending on a small shared
internal client module (proposed: a `guardian-client` library crate, or
equivalent code reuse inside `guardian-core` if the implementer judges
a new crate premature for the amount of shared code — this ADR does not
mandate crate topology beyond "not duplicated") that wraps the typed
`zbus` proxies to `guardian-daemon`'s public interfaces (ADR-001 naming,
this gate's own `Capabilities1`/read surfaces — see the G9 implementation
handoff §6 for the exact interface list). Neither GUI nor TUI may
construct its own independent D-Bus proxy code, parse Guardian's wire
types a second way, or embed any provider-arbitration or safety logic
that could diverge from the daemon's (contract §31's explicit
prohibition, restated for this ADR).

## Alternatives considered

- **`egui`/`iced` (immediate-mode / Elm-architecture Rust GUI):** both
  are real, capable, pure-Rust alternatives with no GTK dependency.
  Rejected for G9 specifically because neither matches the master
  spec's own reference-UI comparison point ("Resources"), and both
  would require building GNOME/Xfce-native look-and-feel (window
  decorations, HIG conformance, desktop integration) from a much
  lower starting point than `libadwaita` already provides for exactly
  Guardian's two target desktops. Not disqualified in principle for a
  future gate; simply a worse fit for *this* gate's actual acceptance
  criteria (§32's dashboard-shell requirements, not a custom-chrome
  application).
- **A non-Rust frontend** (the master spec's own hedge, "a lighter
  frontend language if that's faster to ship"): rejected for G9. It
  would require a second build toolchain, a second D-Bus client
  implementation (violating the "reuse, don't duplicate" discipline
  applied everywhere else in this project), and loses the compile-time
  guarantees the rest of Guardian relies on for its privilege-adjacent
  code paths — even though GUI/TUI are unprivileged, code-sharing with
  the typed Rust wire model is a real, load-bearing benefit.
- **`cursive` (TUI):** a real alternative to `ratatui`; rejected only
  because `ratatui` is more actively maintained and is the master
  spec's own stated preference, with no offsetting advantage found for
  Guardian's specific, narrow TUI acceptance criteria.

## Evidence

This decision is a documentation-and-precedent record, not a comparative
VM spike (see Context above for why that level of evidence is not
warranted here, unlike G6's genuinely three-way indicator-mechanism
uncertainty). G9's implementation work is expected to produce real
build/test evidence that `gtk4-rs`/`ratatui` compile and run correctly
on both target desktops as part of its own normal TDD discipline
(contract §35 Layer 4), not as a precondition of this ADR.

## Consequences

- `guardian-gui` depends on `gtk4-rs`/`libadwaita`; the `.deb` gains a
  runtime dependency on GTK4/libadwaita (already present on a stock
  Ubuntu 26.04 GNOME image via "Resources" and other system apps; an
  explicit Xfce dependency check belongs in G9's packaging evidence).
- `guardian-tui` depends on `ratatui`; no new system dependency.
- Both are real, separate, independently buildable client binaries
  (matching the G9 implementation handoff's existing "no monolithic
  clients crate" discipline) sharing D-Bus client code, never
  duplicating it.

## Rollback / migration implications

If a future gate finds either choice genuinely insufficient (e.g. a
real Xfce-specific `libadwaita` rendering defect discovered through
real VM evidence, not preference), that gate must supersede this ADR
with real comparative evidence, following the same discipline ADR-006
itself establishes for reversing a client-architecture decision — never
a silent swap.
