# ADR-008: Guardian package/service filesystem layout

- Status: Accepted
- Date: 2026-09-02
- Governing gate: G9 — Clients & Packaging (contract §43 requires this record
  "before Phase 1 completion")

## Context

Contract §43 requires an `ADR-008 Package/service filesystem layout`
decision record before Phase 1 completion; it did not exist when an
independent planning review of the G9 implementation handoff examined
G9's packaging plan and found it insufficient on three concrete points,
each capable of quietly weakening G7's accepted, VM-evidenced privilege
topology if left to implementer discretion:

1. **The only polkit assets anywhere in the repository are G7 evidence
   artifacts**, one of which (`docs/evidence/g7/50-guardian-g7.rules`)
   grants an unconditional `YES` on a privileged Class A write action to
   a hardcoded VM test username (`guardiang7caller`). P1-PKG-002
   requires shipping polkit files in the real package; without an
   explicit decision, the obvious (wrong) implementation move is to
   copy this file into `debian/`.
2. **No packaging source assets exist anywhere** — the only real
   systemd unit files, D-Bus policy, and polkit policy are evidence
   artifacts under `docs/evidence/g7/`, never promoted to package-owned
   source. G7's own milestone confirms this directly: the units "do not
   appear in any packaging file (none exist yet — G9 scope)."
3. **No decision existed for state-directory/system-user creation,
   session-autostart mechanism/vendor path, or purge-vs-remove residual
   state semantics** — each a one-way packaging decision with no
   process for catching a wrong implementer guess before it ships.

## Decision

### 1. Systemd units: promoted from G7's evidenced artifacts, not rewritten

`debian/guardian-daemon.service` and `debian/guardian-helper.service`
**must be byte-identical** (modulo only the `ExecStart=` path, which
changes from the VM evidence path `/usr/local/bin/...` to the real
package path `/usr/bin/...`) to the real, independently-measured units
at `docs/evidence/g7/guardian-daemon.service` and
`docs/evidence/g7/guardian-helper.service`. These are the exact units
G7's independent audit exercised with `systemd-analyze security`
(`guardian-daemon` 0.6 SAFE, `guardian-helper` 1.1 OK) and with real
state-ownership evidence. G9 packaging work must diff the packaged
units against these files as part of its own evidence, and must re-run
`systemd-analyze security` against the installed units in the G9
packaging VM to confirm no regression was introduced in translation.

Confirmed from the evidenced units directly: `guardian-daemon` runs as
`User=guardiand Group=guardiand` with `ReadWritePaths=/var/lib/guardian/daemon`
only (`ProtectSystem=strict`, `ProtectHome=yes`); `guardian-helper` runs
as `User=root Group=root` with `ReadWritePaths=/var/lib/guardian/helper`
only. **Packaging must preserve this exactly — one privilege domain per
binary, never merged.**

### 2. Polkit: ship the real policy; never ship the evidence-only bypass rule

`debian/io.github.cliffthelin.guardian.g7.policy` is promoted from
`docs/evidence/g7/io.github.cliffthelin.guardian.g7.policy` **unchanged**
— its `<defaults>` are `allow_any=no allow_inactive=no allow_active=no`,
a real, safe, deny-by-default production policy requiring an explicit,
separately-administered authorization grant for the bounded Class A
write action. This is the only polkit `.policy` file this package ships
for G7's action; G9 introduces no new privileged action and therefore
ships no new `.policy` file of its own.

**`docs/evidence/g7/50-guardian-g7.rules` MUST NOT be packaged, ever, under
any circumstance.** It exists solely to let G7's own disposable VM
evidence-gathering exercise the bounded write path without a live human
present, by granting blanket authorization to one hardcoded test
username. Shipping it in a real package would grant every real
`guardiang7caller`-named account on every install unconditional access
to the privileged write action, defeating the entire polkit
authorization boundary G1/G2/G7 established. G9's completion report
must explicitly confirm, by filename, that this file was not included
in the built `.deb` (e.g. `dpkg -c` output showing its absence).

### 3. D-Bus policy: promoted from G7's evidenced artifacts

`debian/io.github.cliffthelin.Guardian1.conf` and
`debian/io.github.cliffthelin.GuardianHelper1.conf` are promoted
unchanged from `docs/evidence/g7/`. Vendor location:
`/usr/share/dbus-1/system.d/`.

### 4. State directories and system users

- `/var/lib/guardian/daemon/` — owner `guardiand:guardiand`, mode
  `0750` — created via `systemd-tmpfiles`/`StateDirectory=guardian/daemon`
  (already declared in the promoted unit) or explicitly in `postinst`
  if the package needs it to exist before first service start. The
  `guardiand` system user/group is created in `postinst` via
  `adduser --system --group --no-create-home --home /var/lib/guardian/daemon guardiand`
  (Debian policy §9.2.2's standard idiom for a service account) — never
  granted a login shell, never added to any privileged group.
- `/var/lib/guardian/helper/` — owner `root:root`, mode `0750` —
  created the same way via the helper's own `StateDirectory=guardian/helper`.
  No new system user is created for the helper; it runs as `root`
  per G2's accepted privilege-topology decision (ADR-002), unchanged
  by G9.

### 5. Session autostart: XDG autostart `.desktop` entry, not a systemd `--user` unit

**Decision: `guardian-indicator` launches via a real XDG autostart
`.desktop` entry**, vendor path `/etc/xdg/autostart/guardian-indicator.desktop`
(the XDG Base Directory / Desktop Application Autostart Specification's
standard system-wide vendor location — distinct from
`/etc/xdg/autostart/` vs. a per-user `~/.config/autostart/`, which
remains available for a user's own override/disable, per the spec's own
mechanism).

Rejected alternative: a systemd `--user` unit with
`WantedBy=graphical-session.target`. Both GNOME 50 and Xfce 4.20
nominally support `graphical-session.target`, but their session-manager
integration is not equivalent (GNOME's session manager actively
coordinates `graphical-session.target` readiness; Xfce's systemd
integration is comparatively thin), and this is exactly the class of
per-desktop discrepancy ADR-006's own evidence history warns about (the
real Xfce stale-registration defect recorded in
`G6_LOGOUT_LOGIN_LIFECYCLE_EVIDENCE.md`). XDG autostart `.desktop`
entries are the older, simpler, universally-supported freedesktop
mechanism, honored identically by every major desktop environment's own
session-startup code (not systemd's), which is precisely the property
G9 needs across two different desktops with two different levels of
systemd session integration.

**Lifecycle**: the `.desktop` entry is launched by the desktop session's
own startup sequence at login and is not restarted automatically by
systemd; ADR-006's forward constraint ("cleaned up by `systemd-logind`
on logout, not a detached background process") is satisfied because a
session-launched autostart process is a normal child of the user's
login session and is terminated by the session manager/`systemd-logind`
at logout via the ordinary session-cgroup teardown path — never a
`nohup`-style detached process outside any session's process group.
G9's VM evidence must prove this directly (real logout, real process
inspection confirming no orphaned indicator process survives), not
assume it from the mechanism choice alone.

### 6. Purge vs. remove semantics (P1-PKG-003/004)

- **Remove** (`apt remove`): deletes package-owned files (binaries,
  units, D-Bus/polkit policy, the autostart `.desktop` entry). Preserves
  `/var/lib/guardian/{daemon,helper}/` and their contents, and preserves
  the `guardiand` system user (removing a system user on plain `remove`
  is not standard Debian practice and would be surprising/destructive
  if the package is reinstalled later).
- **Purge** (`apt purge`): additionally deletes
  `/var/lib/guardian/{daemon,helper}/` and their contents, and removes
  the `guardiand` system user via `deluser --system guardiand` in
  `postrm purge`. Never deletes anything outside Guardian's own package-
  owned paths (P1-PKG-005's no-vendor-file-mutation rule applies
  identically to removal/purge as to install).

## Alternatives considered

- **Hand-writing fresh unit/policy files for G9** instead of promoting
  G7's evidenced artifacts: rejected — this is exactly the silent-
  divergence risk the independent review flagged; re-deriving from
  scratch with no re-measurement would let the packaged units regress
  G7's accepted hardening with no test catching it, since P1-SEC-* is
  G7's own already-closed scope and G9 is only obligated to "avoid
  regressing" it, not re-prove it independently.
- **Shipping the `.rules` bypass file "for now, to make evidence-
  gathering easier"**: rejected outright — see Decision §2. There is no
  scenario in which shipping this file in a real package is acceptable.
- **A single shared state directory for both processes**: rejected —
  directly contradicts G7's accepted disjoint-ownership model and its
  VM-evidenced invariant that `guardiand` cannot read helper's state.

## Evidence

This ADR's own claims about the promoted units/policy are grounded
directly in the real files at `docs/evidence/g7/*.service`,
`*.conf`, `*.policy`, `*.rules`, and in `docs/evidence/g7/G7_MILESTONE.md`'s
"Persistent state — disjoint ownership" section, all re-read directly
while writing this record. G9's own implementation work must produce
fresh packaging-VM evidence (real `.deb` install, `dpkg -L`, `ls -l`,
`systemctl show`, `systemd-analyze security`, `dpkg -c` confirming the
`.rules` file's absence, real logout/session-teardown process
inspection) — this ADR fixes the plan; it does not substitute for that
evidence.

## Consequences

G9's packaging implementation has a fixed, unambiguous source of truth
for every promoted file, a named, forbidden asset, and a decided
autostart mechanism — removing the three concrete ways a "harmless
packaging convenience" could have weakened G7's accepted privilege
topology.

## Rollback / migration implications

If a future gate needs a genuinely new privileged action, it follows
G7's own precedent in full (a new, real, evidenced `.policy` action with
safe defaults, never a test-only bypass rule promoted to production) and
supersedes the relevant part of this ADR explicitly, rather than
quietly adding a second `.rules` file.
