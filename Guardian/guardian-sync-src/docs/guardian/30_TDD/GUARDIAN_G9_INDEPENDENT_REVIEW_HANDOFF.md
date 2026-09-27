# Guardian Phase 1 Independent Review Handoff
## G9 — Clients & Packaging

# 1. Baseline verification

Confirm independently, before reading anything else in this handoff or
the implementer's completion report:

- Exact `git log -1` HEAD and exact `git status --short` output. G9's
  candidate should sit on top of G8's (by then hopefully tagged)
  baseline as further uncommitted working-tree state, or on top of a
  fresh commit if G8 was tagged in the interim — state which is true.
- No G9 tag exists yet (`git tag -l`).
- Whether G8 itself is tagged at the time of this review. If it is not,
  determine whether G9's candidate depends on any G8 code that is still
  only a candidate (it should not — G9 only *reads* G8's
  `CapabilityRecord`/registry types, never modifies G8 provider code) —
  flag if G9 work required touching any G8 provider file, since that
  would be out of scope for this gate.

# 2. Governing material

- `docs/guardian/30_TDD/GUARDIAN_PHASE_0_1_TDD_CONTRACT.md` §7 (D-Bus
  contract), §21 (boot availability), §30 (indicator decision — already
  closed, G6), §31-34 (client responsibilities/acceptance), §35 (test
  infrastructure), §37 (P1-CLIENTS/P1-PACKAGING), §38 (G9 subsection),
  §39-41.
- `docs/guardian/30_TDD/GUARDIAN_G9_IMPLEMENTATION_HANDOFF.md` (the
  paired implementation handoff this review checks the candidate
  against).
- `docs/adr/ADR-006-guardian-indicator-mechanism.md` (G6's decision —
  the review must confirm G9 reused it, not re-litigated it).
- `docs/evidence/g8/G8_EVIDENCE_REPORT.md` (what real data actually
  exists for G9's clients to render — the review should cross-check the
  GUI/CLI/TUI's rendered content against this, not just against the
  implementer's own claims).
- `docs/adr/ADR-008-guardian-package-filesystem-layout.md` (packaging/
  privilege-topology decisions this candidate must follow exactly).
- `docs/evidence/g9/` (real VM evidence this candidate produced — see
  §15 for an indexed pointer to every file and what it does and does
  not prove).

Treat the implementer's completion report only as navigation, not
evidence. This applies identically to §15 below: it is the
implementer's own index of what was gathered, not a substitute for
independently opening each file and, where practical, independently
reproducing the underlying VM steps.

# 3. Required verdict

Exactly one:

```text
PASS — G9 IMPLEMENTATION ACCEPTED
PASS WITH NON-BLOCKING FINDINGS
FAIL — G9 CLIENT-THINNESS VIOLATED
FAIL — G9 FABRICATED WRITE CAPABILITY
FAIL — G9 INDICATOR DECISION RE-LITIGATED OR REGRESSED
FAIL — G9 PACKAGING EVIDENCE INCOMPLETE
FAIL — G9 REQUIRED EVIDENCE INCOMPLETE
FAIL — G9 PRIOR-GATE REGRESSION
```

# 4. Mechanically re-derive G9's normative scope — do not trust the candidate's own framing

Re-read contract §37's "P1-CLIENTS"/"P1-PACKAGING" subsections and §38's
G9 subsection directly. Confirm independently that the ID set is exactly
`P1-CLI-001..002`, `P1-TUI-001`, `P1-GUI-001..002`, `P1-IND-001..002`,
`P1-PKG-001..005` — 12 IDs. Confirm `P1-DMN-*`/`P1-SEC-*` are G7's (not
re-claimed by G9) and `P0-IND-*` are G6's (not re-claimed by G9). If the
candidate's own matrix claims a different ID set, that is itself a
finding.

# 5. The central-finding audit — the primary audit question

The implementation handoff's own §1 states G9 has **no real write-
capable capability to trigger**, and that any "request transaction" UI
must render this honestly (a real, correctly-empty transaction history;
no fabricated capability with `write_support: true` invented merely to
give a demo something to click).

Independently verify, from source, not from the report:

- Does any new capability record introduced or exposed by G9 have
  `write_support: true`? Grep for it. There should be **zero** such
  records anywhere G9 touches.
- Does any client-facing "request transaction" code path actually
  invoke a real mutation, or silently no-op and report success? Trace
  it end to end. The only acceptable behaviors are: (a) a typed "no
  write-capable capability exists" response for every real request, or
  (b) the UI affordance simply does not exist yet.
- Does the GUI/TUI/CLI transaction-history view show a real (likely
  empty) list, or does it show fabricated/hardcoded sample data dressed
  up as real? Reject fabricated sample data presented as live state.

This is G9's equivalent of G8's write-scope audit — treat any violation
found here as blocking (`FAIL — G9 FABRICATED WRITE CAPABILITY`).

# 6. Client-thinness audit (§31)

For each of CLI/TUI/GUI/indicator, independently confirm none of them:

- directly writes system configuration;
- calls `sudo` or shells out to a privileged helper directly (bypassing
  `guardian-daemon`);
- directly manipulates `/sys` write controls;
- duplicates provider arbitration logic (re-implements any part of
  what belongs to the Provider Arbitrator);
- implements independent safety logic that differs from daemon policy
  (e.g., a client-side "is this safe to power off" check that
  duplicates or diverges from `validate_power_off_preconditions`-style
  daemon logic).

Grep each client crate for D-Bus proxy construction and confirm every
one only ever talks to `guardian-daemon`'s public interfaces — never to
`guardian-helper`, never to a provider's own D-Bus service directly.

# 7. Public D-Bus surface-expansion audit

- Confirm `Guardian1` itself is byte-for-byte unchanged from G0's frozen
  `ContractVersion`/`ServiceState` — any addition belongs on a separate
  interface major per §7.1's illustrative shape. Reject an
  implementation that bolts new methods directly onto `Guardian1`.
- Confirm the new interface(s) are genuinely read-only — no method on
  them can mutate daemon or provider state. Search for any method that
  isn't a pure getter/lister.
- Confirm `CapabilityRecord`/incident/transaction data serialized over
  the new interface(s) matches G3's/G8's real typed models — not a
  hand-rolled second schema that could drift from the real one (in
  particular: does the exposed capability data still show real
  `write_support: false` and real `Knowledge::Unknown` authorization
  ownership, or does the client-facing serialization quietly drop or
  default those fields to something friendlier-looking?).
- Confirm introspection works (`busctl introspect` or equivalent) and
  matches the documented shape.

# 8. Indicator reuse audit — confirm G6 was not re-litigated

- Confirm the candidate uses `ksni`, per ADR-006, without re-running or
  second-guessing the three-candidate comparison.
- Confirm `guardian-indicator` is real production code (in a real
  workspace member crate), not the disposable `tests/vm/g6-candidate-
  ksni/` prototype copied wholesale — check for a genuine dependency on
  real `guardian-daemon` D-Bus state vs. G6's stub/fixture data.
- Confirm the required §30 test list (icon appears, menu opens, menu
  actions invoke the handler, state/icon update propagates, no X11
  dependency, reconnect after panel/Shell restart, reconnect after
  **daemon** restart — not indicator-process restart, no duplicate
  icon, clean logout/login) is evidenced again for real, against real
  data, not merely cited as "G6 already proved this."
- If the candidate found and reports a genuine defect in the G6
  decision itself, verify that finding independently rather than either
  rubber-stamping it or dismissing it — a correct "G6 was wrong" finding
  here is a real prior-gate regression, not a G9 defect.

**A specific finding to independently re-verify, not take on faith:**
the implementer reports that on a genuinely fresh boot → GDM autologin
→ real `gnome-session` autostart of the packaged
`/etc/xdg/autostart/guardian-indicator.desktop` entry, `guardian-
indicator`'s first `tray.spawn()` call failed with
`Watcher(ServiceUnknown("org.kde.StatusNotifierWatcher"))` — GNOME's
watcher-providing extension had not yet registered on the session bus
when the indicator autostarted in parallel with the rest of the
session's autostart apps. The claim is that the *original* code exited
immediately (`std::process::exit(1)`) on any `tray.spawn()` failure,
meaning the real packaged indicator would have been silently absent
after every real cold-boot GNOME login, and that this was repaired in
`crates/guardian-indicator/src/main.rs` (`spawn_tray_with_retry`) with
a bounded retry: 15 attempts, 2 seconds apart, each attempt logged to
stderr, exiting only after genuinely exhausting all 15. Independently
confirm all of the following, not just that the retry code exists:

- The retry bound is real and finite (not an infinite silent loop) —
  read the function, don't take "bounded" on faith.
- The claimed real evidence
  (`docs/evidence/g9/gnome-evidence-log.txt`) actually shows attempt 1
  failing with this exact error and a later attempt succeeding, sourced
  from a real `journalctl -b` capture, not authored prose.
- The fix was verified against the *same* reproduction that found the
  bug (fresh VM reboot → real GDM autologin → real autostart of the
  actual installed `.deb`'s indicator binary), not merely a unit test
  or a manually-launched process where the watcher was already up —
  neither of those would have caught this race in the first place, and
  neither would prove the fix.
- This defect could plausibly recur on Xfce or any other desktop whose
  watcher-providing component starts late relative to session
  autostart; confirm the fix is desktop-agnostic (a generic retry
  around `tray.spawn()`, not a GNOME-specific special case) rather than
  papering over one desktop's timing without protecting the others.

# 9. Per-surface acceptance validation

- **CLI**: real JSON-mode output for every one of the seven minimum
  commands, independently parsed with a real JSON parser (not eyeballed
  formatting). Real, deterministic daemon-offline exit code/message,
  reproduced independently (stop the real daemon, run the real CLI).
- **TUI**: reproduce a real VT-only session (no `DISPLAY`, no
  `WAYLAND_DISPLAY`) and confirm real startup.
- **GUI**: confirm every §32-listed element is genuinely rendered from
  real daemon state (daemon connection state, overall Guardian state,
  capabilities list, provider ownership, incidents list, blockers,
  PSI summary, transaction history, graceful provider-unavailable
  state) — not a static mockup.
- **Packaging**: reproduce (or closely audit if reproduction is
  impractical within review budget) real install on a clean VM, real
  vendor-path placement, real uninstall/purge behavior, and confirm no
  other package's files were touched during install.

# 10. Forward-constraint audit

Confirm G9 did not silently close: G4 FC-3, G5 FC-2, G7 SafeToResume/
idempotency, or any of G8's forward constraints (single-writer,
`Knowledge::Unknown` authorization ownership, `write_support: false`).
None of these should even be *touchable* by a read-only client layer —
verify that's actually true in the code, not merely asserted.

# 11. Real-VM evidence audit

**This §30 slice of the real-VM evidence audit has been performed** by
a genuinely independent reviewer, verdict `PASS WITH NON-BLOCKING
FINDINGS` — see §15's reconciled count and findings for the outcome.
The checklist below is preserved as the procedure that review actually
followed (and as the standing procedure for any future re-review, e.g.
if a later packaging change breaks autostart/session behavior); it is
not a still-open task list.

- Confirm indicator evidence includes real visual proof (screenshots or
  equivalent) on both GNOME 50/Wayland and Xfce 4.20, not text-only
  D-Bus introspection presented as if it proved visual rendering. **Be
  precise about what the candidate's own screenshots actually show**:
  `docs/evidence/g9/xfce-guardian-tray.png` and
  `docs/evidence/g9/gnome-guardian-gui.png` show the GUI shell window
  rendering real daemon data, not a visibly legible tray icon glyph in
  either desktop's panel — the implementer's own evidence log
  (`session-teardown-log.txt`, `gnome-evidence-log.txt`) states this
  gap directly rather than claiming the screenshots prove icon
  appearance. Treat "icon appears" (§30's first required test) as
  **proven only at the D-Bus/SNI-registration level** (real
  `org.kde.StatusNotifierItem-<pid>-N` name owned, real `IconName`/
  `Title` properties reflecting live daemon state, confirmed on both
  desktops) and **not yet proven visually** — do not accept a claim
  that this is fully closed without independently obtaining an actual
  legible panel screenshot, or explicitly downgrade the verdict to
  reflect the gap.
- Confirm packaging evidence used a genuinely fresh Ubuntu 26.04.1
  image, not a VM already carrying prior gates' leftover state.
- Confirm daemon-restart-while-indicator-alive evidence is the
  genuinely correct scenario (daemon process restarts, indicator
  process does not) — this exact confusion was a real defect G6's own
  audit history caught once already; check it was not repeated here.
  **Now evidenced**: `docs/evidence/g9/daemon-restart-reconnect-log.txt`
  records a real `systemctl stop`/`start guardian-daemon` cycle against
  a live `guardian-indicator` (same PID throughout, verified via `ps`),
  with the item's real `Title`/`IconName` properties queried via D-Bus
  before and after — confirm independently that the PID really did not
  change and that the property values really did transition
  Degraded→Unavailable→Degraded, not merely that the log narrates this.
- Confirm every VM artifact is attributable to the exact final source
  digest of the candidate under review (same discipline the G8 audit
  required) — reject evidence that cannot be tied to the reviewed
  source.
- **Cross-check the full §30 required-test list item by item against
  what was actually gathered** (see §15's index — updated with a second
  evidence batch). "Menu opens" and "menu actions invoke the
  client-side handler" are now evidenced via real `com.canonical.
  dbusmenu.GetLayout`/`Event` D-Bus calls against the real item
  (`menu-interaction-log.txt`) — independently confirm the `Event`
  call on the real "Quit" item ID actually terminated the real process
  (not merely that the log says so). "Reconnect after panel/Shell
  restart" and "no duplicate icon" are now evidenced on Xfce (real
  `xfce4-panel -r`, confirmed via the watcher's D-Bus-owning PID
  changing while the indicator's own PID and item name did not —
  `panel-restart-and-icon-render-log.txt`); the equivalent test is not
  meaningful on GNOME/Wayland, where the watcher is owned by
  `gnome-shell` itself and there is no in-place Shell-restart operation
  independent of ending the session (see `gnome-shell-restart-
  constraint-note.txt` — verify this claim independently, e.g. confirm
  `GetConnectionUnixProcessID` for `org.kde.StatusNotifierWatcher`
  really does resolve to the `gnome-shell` process on a real GNOME
  session, rather than accepting the platform-limitation claim on
  faith). **Still genuinely open, on both desktops**: a legible visual
  screenshot of the tray icon glyph itself. `xfce-panel-with-icon.png`/
  `xfce-tray-zoom.png` show the systray slot rendering as a flat color
  block, not a recognizable glyph, despite the candidate independently
  confirming (via `Gtk.IconTheme.get_default().has_icon()`) that every
  icon name `guardian-indicator` ever sets resolves correctly at the
  toolkit level — the implementer attributes the blank render to
  Xfce's own systray-plugin SNI-icon compositing in a minimal,
  software-rendered VM, not to `guardian-indicator`. Independently form
  a judgment on this attribution rather than accepting it uncritically
  — if practical, reproduce with hardware-accelerated rendering or a
  different systray implementation to see whether the icon renders
  correctly there, which would confirm the attribution; if that is not
  practical within review budget, treat "icon appears" as proven at
  the D-Bus/SNI level only, exactly as this handoff's earlier note
  already establishes.

# 12. Regression audit

Run the full workspace test suite and confirm the pre-G9 baseline count
is preserved (no G0-G8 test was weakened, skipped, or deleted to make
G9 pass). Confirm no G8 provider file was modified by this gate (G9's
own scope should not require touching `crates/guardian-core/src/
providers/*`).

# 13. Validation

```text
cargo fmt --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

Report the exact before/after test counts and confirm they match the
candidate's own claim.

# 14. Required report

1. Git/baseline state;
2. exhaustive changed-file reconciliation (reported vs. actual, flagging
   any G8-provider-file or prior-gate-production-file touch);
3. independently re-derived 12-ID matrix;
4. central-finding (§5) audit — fabricated-write-capability check;
5. client-thinness audit (§6);
6. public D-Bus surface-expansion audit (§7);
7. indicator reuse audit (§8);
8. per-surface acceptance validation (§9);
9. forward-constraint audit (§10);
10. real-VM evidence audit (§11);
11. regression audit (§12);
12. validation (§13);
13. blocking findings;
14. non-blocking findings;
15. exact next action.

# 15. Evidence index for this candidate (navigational only — verify independently, per §2)

Real VM evidence was gathered across three passes on one disposable
Ubuntu 26.04.1 `multipass` VM: Xfce 4.20 (`lightdm` autologin) first,
then GNOME 50.1/Mutter/GDM (Wayland, `gdm3` autologin, after installing
`ubuntu-desktop-minimal`) for the GNOME-specific evidence and the
cold-boot indicator race, then back to the same Xfce configuration for
the panel-restart/menu-interaction/daemon-restart-reconnect tests that
are more meaningfully exercised on a desktop where the panel is an
ordinary child process. Between passes the daemon/helper services and
the installed `.deb` were not reinstalled from scratch each time —
independently confirm from the logs below which specific evidence was
gathered against which VM state, rather than assuming every file
reflects an identical, single VM snapshot. All files below live under
`docs/evidence/g9/`.

| File | What it is | What it proves |
|---|---|---|
| `g9-daemon-security.txt`, `g9-helper-security.txt` | Real `systemd-analyze security` output against the *installed packaged* units | Packaging preserved G7's exact hardening scores (0.6 SAFE / 1.1 OK) — no regression from promotion into `debian/` |
| `g9-capabilities-introspect.txt`, `g9-incidents-introspect.txt`, `g9-transactions-introspect.txt` | Real `gdbus introspect` against the live daemon | The three new interfaces exist at the documented object paths with the documented method/signature shape |
| `g9-cli-*-online.txt`, `g9-cli-*-online.json` | Real CLI output against a live daemon | Every minimum CLI command (§34) produces real, live data; `--json` is genuinely valid JSON |
| `g9-cli-status-offline.json` | Real CLI output with the daemon stopped | P1-CLI-002's deterministic offline behavior, both plain and JSON |
| `tui-online2.txt`, `tui-offline.txt` | Raw captured terminal escape sequences from a real pty (`script`), daemon up and daemon down | P1-TUI-001 — real VT-only rendering, no `DISPLAY`/`WAYLAND_DISPLAY`; honest degradation offline |
| `xfce-guardian-session.png`, `xfce-guardian-tray.png` | Screenshots from the real Xfce session | GUI shell renders live daemon data under Xfce. **Does not** show a legible tray icon glyph — see §11's caveat |
| `gnome-guardian-gui.png` | Screenshot captured via an Xwayland compatibility shim (`GDK_BACKEND=x11` against Mutter's own Xwayland instance, window-ID-targeted `import`, since GNOME Shell's own screenshot D-Bus API refused the request even from inside the session's own cgroup) | GUI shell renders live daemon data under real GNOME 50/Wayland |
| `session-teardown-log.txt` | Real `loginctl terminate-session` against a real `lightdm`-autologin session with the indicator autostarted via the real `/etc/xdg/autostart` entry | `guardian-indicator` is cleanly killed by real session teardown, no orphan (Xfce) |
| `gnome-evidence-log.txt` | Narrative log covering GUI/indicator behavior under GNOME, the cold-boot `StatusNotifierWatcher` race discovery and fix (see §8), and a second real `loginctl terminate-session` teardown test | Same teardown proof on GNOME; documents the race/fix with the exact `journalctl` line the implementer observed |
| `deb-install-remove-purge-log.txt` | Narrative log of a real `dpkg-buildpackage` build, two real bugs found and fixed while actually building/installing (missing `dh_installsystemd --name=` per unit; `policykit-1` not installable on 26.04, needed `polkitd \| policykit-1`), then real `dpkg -i` → `dpkg -r` → `dpkg -P` | P1-PKG-001..005 exercised for real, including the ADR-008 `.rules`-file-absence check via `dpkg -c` |
| `guardian_0.1.0-1_amd64.deb` | The actual built package | Reviewers can `dpkg -c`/`dpkg -x` this directly rather than trust the narrative log |
| `menu-interaction-log.txt` | Real `com.canonical.dbusmenu.GetLayout`/`Event` calls against the real item's real `/MenuBar` object | "Menu opens" and "menu actions invoke the client-side handler" — the real "Quit" item's real `Event("clicked")` call genuinely terminated the real process |
| `daemon-restart-reconnect-log.txt` | Real `systemctl stop`/`start guardian-daemon` against a live indicator, with `Title`/`IconName` queried via D-Bus before/after, PID checked throughout | Daemon-restart-while-indicator-alive reconnect, and daemon-unavailable-shows-degraded-state, both against the real production binary |
| `panel-restart-and-icon-render-log.txt` | Real `xfce4-panel -r`, watcher-owning-PID and item-name checked before/after; also documents the icon-glyph render investigation | Reconnect-after-panel-restart and no-duplicate-icon, both real; also the honest, independently-checked (`Gtk.IconTheme.has_icon()`) attribution of the blank tray-glyph render to Xfce's own systray plugin, not to `guardian-indicator` |
| `gnome-shell-restart-constraint-note.txt` | Direct D-Bus check of which process owns `org.kde.StatusNotifierWatcher` under real GNOME/Wayland | Explains why "Shell restart" is not a meaningful in-place test on Wayland (`gnome-shell` itself owns the watcher; no in-place Shell restart exists on Wayland) — reviewer should independently verify this claim, not accept it as given |
| `xfce-panel-with-icon.png`, `xfce-tray-zoom.png` | Screenshots of the real Xfce panel with the real systray plugin loaded | The systray slot exists and is live, but does **not** show a legible icon glyph — direct evidence of the render gap documented above |

**§30 focused independent review — completed, `PASS WITH NON-BLOCKING
FINDINGS`.** A genuinely independent review (fresh reviewer, no memory
of this implementation) performed exactly this §30 slice as its own
review and mechanically re-derived the count directly from §30's text:
**9 of 10 required indicator tests are fully closed; exactly 1 remains
open**, and that one item is non-blocking. Two clarifications from that
review, since an earlier draft of this section miscounted by treating
the GNOME/Shell-restart platform limitation as a second open item
rather than a closed-with-legitimate-asymmetric-evidence item:

- "Reconnect after panel/Shell restart" is **closed** — proven for
  real on Xfce (`panel-restart-and-icon-render-log.txt`), and correctly
  N/A as an *independent* in-place test on GNOME/Wayland (there is no
  in-place Shell-restart operation on Wayland distinct from ending the
  session — independently re-confirmed live in the VM by the reviewer,
  not merely accepted from the implementer's note). Requiring an
  impossible GNOME-specific repetition of this test would be requiring
  the impossible, not identifying a real gap.
- The **one genuinely open item is the tray icon's visual glyph
  render** (D-Bus/SNI-level registration, live state, menu structure,
  menu-action invocation, daemon-restart reconnect, and panel-restart
  reconnect are all proven for real on both required desktops). The
  independent reviewer did not accept the implementer's "this is a
  desktop rendering limitation, not a Guardian defect" attribution on
  faith — it re-entered the live VM, took its own fresh screenshot, and
  additionally checked two unrelated real SNI items already registered
  on the same Xfce systray (Ubuntu's own `update-notifier` applets):
  both also render as flat, non-legible slots. That independently-
  gathered corroboration is what elevated the finding from "implementer
  says it's not us" to a defensible attribution, and the reviewer
  adjudicated the glyph criterion `PASS WITH NON-BLOCKING FINDING`
  under §30's actual text, which requires a functioning indicator test
  suite, not pixel-perfect rendering proof.

Everything else in §30's required-test list has real evidence behind
it; nothing was quietly claimed as satisfied without a pointer to the
file that backs it.

Then STOP. Do not modify the candidate. Do not commit. Do not push. Do
not tag G9. Do not begin any Phase 2 work.
