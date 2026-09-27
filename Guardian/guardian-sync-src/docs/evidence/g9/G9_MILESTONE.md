# Guardian Phase 0/1 — G9 Milestone Record

## Project identity

```text
Project display name:  Guardian Plane
Repository slug:       guardian-plane
GitHub repository:     github.com/cliffthelin/guardian-plane
Permanent D-Bus namespace: io.github.cliffthelin.Guardian1
```

## Decision

```text
Gate:               G9 — Clients & Packaging
Governing:          docs/guardian/30_TDD/GUARDIAN_G9_IMPLEMENTATION_HANDOFF.md,
                     docs/guardian/30_TDD/GUARDIAN_G9_INDEPENDENT_REVIEW_HANDOFF.md
Normative IDs:       P1-CLI-001..002, P1-TUI-001, P1-GUI-001..002,
                     P1-IND-001..002, P1-PKG-001..005 (12 total) — ALL PASS
Status:              Accepted — PASS WITH NON-BLOCKING FINDINGS, across
                     three independent review tracks (desktop/indicator
                     slice, packaging/privilege slice, and a final
                     broad gate audit + focused TUI-repair re-audit)
Final validation:    304 passed, 0 failed; cargo fmt --check clean;
                     cargo clippy --workspace --all-targets
                     --all-features -- -D warnings clean
```

This record is written at publication time, after acceptance — it
preserves the actual audit/repair history below rather than collapsing
it into a clean narrative that hides the real rejection and repair
cycle the TUI surface went through.

## Five required surfaces

```text
CLI         — guardian-cli. Human + JSON output for all seven minimum
              commands (status, capabilities/providers, incidents,
              blockers, psi, transactions). Deterministic exit codes
              (0/2/3/64), reproduced against a live and a genuinely-
              stopped daemon.
TUI         — guardian-tui. ratatui (ADR-007), VT-runnable, shares
              guardian-client with CLI/GUI (no parallel D-Bus parsing
              path). Displays connection status, capabilities, and (as
              of the repair below) incidents. Exercises G1's real
              text-polkit authorization path as a verification-only
              test action.
GUI shell   — guardian-gui. GTK4/libadwaita via gtk4-rs (ADR-007). All
              eight contract §32 elements as distinct panes; graceful
              per-pane degrade when the daemon is unavailable.
Indicator   — guardian-indicator. ksni (ADR-006, reused not
              relitigated), real production integration against live
              daemon state, real XDG-autostart session lifecycle.
Debian
  package   — debian/. Real .deb: promoted G7 units/D-Bus/polkit policy
              (ADR-008), correct vendor paths, correct install/remove/
              purge semantics.
```

## Public D-Bus boundary (final)

`Guardian1` remains byte-for-byte the G0 freeze —
`ContractVersion`/`ServiceState` only. Three new, separate interface
majors were added, each read-only by construction (list/getter methods
only, independently confirmed live via introspection):

```text
io.github.cliffthelin.Guardian.Capabilities1  at /io/github/cliffthelin/Guardian1/Capabilities
  ListCapabilities() -> real, live G8 Capability Registry snapshot
  PsiSummary()       -> real G8 PSI reads
  ListBlockers()     -> real logind ListInhibitors projection
io.github.cliffthelin.Guardian.Incidents1     at /io/github/cliffthelin/Guardian1/Incidents
  ListIncidents()    -> real, live, currently-empty list (no incident
                        producer exists in production yet; genuinely
                        queried, never hardcoded)
io.github.cliffthelin.Guardian.Transactions1  at /io/github/cliffthelin/Guardian1/Transactions
  ListTransactions() -> real, live, currently-empty list (daemon holds
                        no transaction store; guardian-helper's own
                        transaction persistence is never read)
```

Explicitly and independently distinguished from G7's own struck
precedent: an earlier `Guardian1.Transactions1` addition was rejected by
G7's independent audit for carrying a write method
(`AttemptProviderDelegatedWrite`) bolted onto `Guardian1` itself. The
current `Transactions1` is a separate interface major, carries no write
method at all, and never touches `Guardian1` — confirmed materially
different, not the same mistake under a reused name.

## Fabricated-write-capability decision

**No real write-capable capability exists that corresponds to a
meaningful, real-world Guardian feature — and G9 does not fabricate
one.** Every real `CapabilityRecord` served by `Capabilities1` has
`write_support: false` and honest `Knowledge::Unknown` authorization
ownership, confirmed by direct source grep and by live introspection
across every audit round. `guardian-helper`'s real
`GuardedWrite(interactive: bool) -> u64` (G7, a real, live, polkit-
authorized mutation against `CounterAdapter`) exists but is never called
by any G9 client — it is G7's own evidence fixture proving the Class A
architecture works end to end, not a Guardian feature, and presenting it
as one would itself be fake functionality dressed up as real. No
`RequestTransaction` method exists at all, structural or otherwise —
`Transactions1` is list-only. The TUI's text-polkit test action (added
during the repair below) reuses G1's real, already-accepted
`CheckAuthorization` path purely as a verification mechanism — it never
creates a writable capability, never calls `GuardedWrite`, and every
real daemon capability remained `write_support: false` before and after
exercising it, confirmed live in the VM.

## ADR reuse and new decisions

```text
ADR-006 (indicator mechanism) — reused as given, not relitigated. G9
  built the real production ksni indicator ADR-006 specified; the three-
  candidate comparison was not rerun.
ADR-007 (GUI/TUI client separation, new this gate) — GTK4/libadwaita via
  gtk4-rs for GUI, ratatui for TUI, both decided with real alternatives
  considered (egui/iced, cursive) before implementation began.
ADR-008 (package/service filesystem layout, new this gate) — promoted-
  artifact byte-identity rule (G7 units/policy, modulo ExecStart= only),
  the forbidden-file rule for docs/evidence/g7/50-guardian-g7.rules,
  state-directory/system-user creation, purge-vs-remove semantics, and
  the XDG-autostart session mechanism/vendor path.
```

## Independent audit history (preserved, not collapsed)

```text
Desktop/indicator slice review (§30, independent)
  Mechanically re-derived all 10 required indicator tests from contract
  §30 directly. Found 9 of 10 fully closed with real evidence: DBusMenu
  layout genuinely queryable (real GetLayout call returning the real
  live status item + Quit); the real "Quit" Event("clicked") call
  genuinely terminated the real indicator process; the same indicator
  process survived a real daemon stop/start cycle, transitioning
  Degraded -> Daemon Unavailable -> Degraded on the same PID; the same
  indicator process survived a real Xfce panel replacement (xfce4-panel
  -r), re-registering with the new watcher with exactly one SNI item,
  no duplicate; GNOME/Wayland's lack of an in-place Shell-restart
  operation was independently confirmed as a genuine platform
  constraint (org.kde.StatusNotifierWatcher is owned by gnome-shell
  itself on Wayland), not a gap in evidence. A real cold-boot
  StatusNotifierWatcher startup race was discovered during evidence
  gathering (guardian-indicator's first tray.spawn() attempt failed on
  a genuine fresh GDM-autologin boot because the watcher had not yet
  registered) and repaired with a bounded, logged retry (15 attempts,
  2s apart) — verified against the same real cold-boot reproduction
  that found it. One item remained open: no legible visual screenshot
  of the tray icon glyph on either desktop (protocol-level SNI state is
  correct and live on both; the flat-color render was independently
  attributed to the desktop's own systray-plugin compositing in this
  VM, corroborated by two unrelated third-party SNI items rendering
  identically blank).
  Verdict: PASS WITH NON-BLOCKING FINDINGS.

Packaging/privilege slice review (independent), round 1
  Independently re-measured systemd-analyze security against the
  installed units (0.6 SAFE daemon / 1.1 OK helper, matching G7's
  claimed scores exactly, no regression); independently re-extracted
  the built .deb and confirmed docs/evidence/g7/50-guardian-g7.rules is
  absent by content, not merely by filename; independently reproduced a
  full install/remove/purge cycle. Found one real, reproducible defect:
  /etc/xdg/autostart/guardian-indicator.desktop survived `dpkg -r`
  because debhelper automatically classified any file staged under
  /etc/ at build time as a Debian conffile, which dpkg then preserves
  on remove — contradicting ADR-008 Decision 6's explicit text.
  Verdict: PASS WITH NON-BLOCKING FINDINGS (the conffile defect named
  as the one repair-worthy finding).

Packaging repair + focused re-review (independent)
  Repair: the .desktop file is no longer staged under /etc/ at build
  time at all; it is installed to a package-owned, non-/etc vendor path
  and copied into /etc/xdg/autostart/ by postinst, removed by postrm on
  both remove and purge. The runtime-installed path is unchanged.
  Focused re-review independently reproduced install -> remove ->
  purge, install -> remove -> install (reinstall), and the upgrade path
  (old postrm's `upgrade` argument correctly does not delete the file
  mid-upgrade); independently confirmed no `conffiles` entry exists in
  the rebuilt .deb's control archive at all; inspected maintainer-
  script argument-completeness, idempotency, and self-healing directly.
  Verdict: PASS WITH NON-BLOCKING FINDINGS.

Final broad gate audit (independent)
  Covered all 12 normative IDs, the five-surface set, the central
  fabricated-write-capability question, the public D-Bus surface,
  client thinness/authority boundary, CLI/TUI/GUI audits, indicator and
  packaging regression spot-checks, ADR compliance, empty-state
  semantics, cross-client consistency, capability-presentation
  consistency, prior-gate regression, and scope discipline.
  Independently re-verified all 12 IDs live; independently re-
  reproduced the full install/remove/purge cycle from scratch;
  independently confirmed Guardian1's freeze and the Transactions1
  distinction from G7's struck precedent; independently reproduced
  fmt/clippy/292-test baseline exactly. One blocking finding: contract
  §33 states unconditionally that the Phase 1 TUI MUST display the
  same capability/incident data as the GUI at a basic level and MUST
  exercise text polkit in a test action. The G9 implementation
  handoff's own §7.2 explicitly commits to both; neither existed
  anywhere in guardian-tui's 199-line source at the time — not
  partially done, entirely absent.
  Verdict: FAIL — G9 NORMATIVE REQUIREMENTS INCOMPLETE.
  Exact next action: "Repair G9 and request another focused audit."

TUI repair (narrow, bounded)
  Added exactly the two missing items, nothing else: an incidents pane
  reusing the identical typed connection.incidents() call the GUI
  already uses; a text-polkit test action ('a' key) reusing G1's
  already-accepted PolkitAuthorizer directly against PolkitAction::Read
  (one of contract §9's four guardian.test.* actions — no new action,
  no new D-Bus method, no new privileged capability). Real interactive
  terminal authentication is obtained by spawning pkttyagent bound to
  the TUI's own process for the duration of the check only; no sudo, no
  shell, ever. 12 new tests added (10 pure rendering/mapping tests plus
  2 real-private-D-Bus-bus tests proving identity resolution against a
  genuine connection, mirroring G1's own Layer 1 discipline). Real VM
  evidence: an evidence-only polkit fixture (mirroring G1's own
  established g1-layer2-vm-setup.sh idiom, never packaged) with a
  granted and a denied real local user; the real packaged
  /usr/bin/guardian-tui (confirmed via dpkg -S) was driven through a
  real pseudo-terminal with real keystrokes, producing a real live
  AUTHORIZED result (with a real pkttyagent process observed spawned
  and cleaned up around it) and a real live DENIED result; the daemon's
  real capabilities were re-queried after and remained all
  write_support: false. Test count: 292 -> 304.

Focused TUI-repair re-audit (independent)
  Did not trust the repair's own report. Independently re-derived
  contract §33's text directly; independently confirmed guardian-tui
  and guardian-gui call the identical connection.incidents() path;
  independently re-drove the real installed /usr/bin/guardian-tui
  through the reviewer's own PTY harness (not the retained
  transcripts), sampling the process tree every 100ms, observing
  pkttyagent appear and disappear within ~100-200ms in both the
  authorized and denied runs with no sudo/shell ever appearing;
  independently re-queried live capability state before and after both
  runs, confirming no write_support flip; independently re-extracted
  the built .deb and confirmed the evidence-only polkit fixture is not
  packaged and G7's real polkit policy is untouched; independently
  reproduced fmt/clippy/304-test validation.
  Verdict: PASS WITH NON-BLOCKING FINDINGS.
  Exact next action: "Return to final G9 gate acceptance/publication."
```

## Non-blocking findings carried forward (forward/hardening items, not defects)

None of the items below were adjudicated as gate-blocking by the
independent reviewers who found them; they are recorded here so they
remain visible rather than silently dropped at publication.

```text
- Tray-icon visual glyph rendering: no legible screenshot of the
  indicator's icon glyph exists on either required desktop. Protocol-
  level SNI state (registration, live IconName/Title) is correct and
  live on both GNOME 50/Wayland and Xfce 4.20. Independently attributed
  to the desktop's own systray-plugin SNI-icon compositing in this VM
  (corroborated by two unrelated third-party SNI items rendering
  identically blank in the same environment), not to guardian-
  indicator. Contract §30 requires a functioning indicator test suite,
  not pixel-perfect rendering proof.
- guardian-testkit's PrivateSessionBus::launch performs an unbounded
  BufReader::read_line() waiting for dbus-daemon's startup address
  line, with no timeout. Confirmed test-only (no production binary
  depends on this pattern); plausibly explains one transient
  cargo test --release hang observed once during a dpkg-buildpackage
  run (never reproduced since, standalone and full-suite runs both
  pass reliably). Good candidate for a post-G9 test-infrastructure
  cleanup, not remediated as part of G9 itself.
- guardian-tui's text-polkit test action waits a fixed ~300ms after
  spawning pkttyagent before issuing the authorization check, with no
  synchronous "ready" signal from the agent — an inherently racy idiom,
  not observed to fail in any reproduction so far.
- guardian-tui's pkttyagent cleanup is imperative (explicit kill()/
  wait() after the check returns) rather than RAII/Drop-guarded. No
  current code path skips it (no unwrap/expect/early-return exists
  between spawn and cleanup), but a future edit introducing a panic or
  early return in that span could leak the process.
- StateDirectoryMode is not set on either promoted systemd unit;
  /var/lib/guardian/{daemon,helper} end up at runtime mode 0755 rather
  than ADR-008 §4's stated 0750, once the daemon/helper have run.
  Inherited unchanged from already-accepted G7 behavior (G7's own real
  evidence measured 0755 for the same directories) — not a G9
  regression. No privilege-boundary issue: ownership is correct
  throughout, and cross-process data access is independently denied at
  the file level (0600/0700 modes) regardless of the parent
  directory's own listing permission.
- The packaged runtime autostart file
  (/etc/xdg/autostart/guardian-indicator.desktop) is maintained by
  postinst/postrm rather than by dpkg's own conffile tracking — a
  deliberate, independently-reviewed consequence of the packaging
  repair (dpkg's automatic /etc-file conffile detection has no per-file
  opt-out in the debhelper version this project targets). `dpkg -L`/
  `dpkg -S` do not know about the runtime copy; any local admin edit to
  it is overwritten on the next `dpkg --configure`. The supported
  per-user override remains the standard XDG mechanism
  (~/.config/autostart/ or a Hidden=true override), not editing the
  vendor /etc copy directly.
- The G9 implementation handoff's own §8 states a short addendum
  should be added to ADR-006 noting a gate-ownership correction
  (contract §38 assigns the production indicator to G9, not G7, despite
  ADR-006's own "G7 must build its own production indicator daemon"
  phrasing). That addendum was never added — ADR-006 remains
  unmodified. Documentation-only: the underlying gate-ownership
  question is correctly resolved in practice (G9 did build the
  production indicator), and no implementation decision depends on the
  addendum existing.
```

## Evidence index (referenced, not duplicated here)

```text
docs/guardian/30_TDD/GUARDIAN_G9_IMPLEMENTATION_HANDOFF.md
docs/guardian/30_TDD/GUARDIAN_G9_INDEPENDENT_REVIEW_HANDOFF.md
docs/adr/ADR-006-guardian-indicator-mechanism.md (reused, unmodified)
docs/adr/ADR-007-guardian-gui-tui-client-separation.md (new this gate)
docs/adr/ADR-008-guardian-package-filesystem-layout.md (new this gate)
docs/evidence/g9/ (full evidence set — CLI online/offline transcripts,
  D-Bus introspection captures, systemd-analyze security captures,
  Xfce/GNOME screenshots, menu-interaction/daemon-restart/panel-restart
  logs, deb-install-remove-purge-log.txt (original conffile finding
  preserved alongside the repair narrative), broad-audit-tui-repair-
  history.txt, tui-repair/ (incidents/text-polkit real VM evidence),
  guardian_0.1.0-1_amd64.deb (final accepted build))
crates/guardian-cli/, guardian-tui/, guardian-gui/, guardian-indicator/,
  guardian-client/ (five new production crates)
crates/guardian-daemon/src/dbus_surface.rs (new read-only D-Bus surface)
debian/ (packaging source: control, rules, postinst, postrm,
  guardian.install, promoted units/D-Bus policy/polkit policy, XDG
  autostart entry)
```
