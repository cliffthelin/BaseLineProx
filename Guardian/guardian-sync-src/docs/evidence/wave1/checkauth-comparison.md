# W1-VM-007: native vs. mediated `CheckAuthorization` comparison

Captured via `sudo busctl monitor --system org.freedesktop.PolicyKit1` in
`guardian-g9` (Ubuntu 26.04 LTS, polkitd 127-2ubuntu1) while triggering, in
separate runs:

- **Native**: `sudo -u wave1allowed systemctl restart cups.service`
  (raw capture: `native_checkauth.txt`)
- **Mediated**: `sudo -u wave1allowed busctl call --system
  io.github.cliffthelin.GuardianHelper1 ... RestartCapability sb
  'cups-restart' false` (raw capture: `mediated_checkauth.txt`)

Both were captured against the real, evidence-only,
detail-sensitive `60-wave1-evidence.rules` fixture (granting `wave1allowed`
`manage-units` only when `unit == "cups.service" && verb == "restart"`).

## Field-by-field comparison

| Field | Native (`systemctl restart`) | Mediated (`guardian-helper`) | Match |
|---|---|---|---|
| `Sender` (process issuing `CheckAuthorization`) | `:1.3` (systemd/PID 1 itself) | `:1.76` (`guardian-helper`, root) | Different processes, both root-trusted callers — expected per ADR-002's trusted-caller pattern; systemd relays the same way Guardian does |
| Subject kind | `system-bus-name` | `system-bus-name` | Identical |
| Subject name | `:1.98` (the real `wave1allowed` `systemctl` connection) | `:1.103` (the real `wave1allowed` `busctl` connection) | Both are the **real original caller's own bus name**, never the relaying process's — identical semantics |
| `action_id` | `org.freedesktop.systemd1.manage-units` | `org.freedesktop.systemd1.manage-units` | **Identical** |
| detail `unit` | `cups.service` | `cups.service` | **Identical** |
| detail `verb` | `restart` | `restart` | **Identical** |
| detail `polkit.gettext_domain` | `systemd` | `systemd` | **Identical** |
| detail `polkit.message` | `Authentication is required to restart '$(unit)'.` (literal, **unsubstituted** `$(unit)` placeholder) | `Authentication is required to restart 'cups.service'.` (interpolated) | **Differs** — see finding below |
| `flags` | `1` (`ALLOW_USER_INTERACTION`, since `systemctl restart` allows interactive auth) | `0` (no interaction, since the evidence call passed `interactive=false`) | Differs, but this is the **caller-controlled** interactive flag, not an authorization-relevant divergence — Guardian's own `RestartCapability(capability_id, interactive)` exposes the identical choice a direct caller has |
| `cancellation_id` | `""` | `""` | Identical |

## Finding: `polkit.message` value mismatch (contract discrepancy — reported per §7/§50's binding rule)

The accepted handoff (§7, §10, §12/W1-AUTH-007) states the evidenced
`polkit.message` value is:

```
Authentication is required to restart '<unit>'.
```

with the unit name **interpolated** (its own worked example: `'cups.service'`
directly). The implementation here follows that literally —
`ProviderAuthorizationRequest::details()`
(`crates/guardian-core/src/authorization.rs`) constructs the message via
`format!("Authentication is required to restart '{}'.",
capability.unit_name())`, producing exactly
`"Authentication is required to restart 'cups.service'."`.

**Real, independently re-captured evidence in this fresh disposable Ubuntu
26.04.1 VM shows systemd's own native request does not interpolate this
field at all** — it sends the literal, unsubstituted template string
`"Authentication is required to restart '$(unit)'."`, with `$(unit)` as a
literal four-character-plus-parens substring, not a resolved value. This is
a real, mechanically observed divergence between the accepted contract's
evidenced value and this implementation's independent re-verification of
that same value against real Ubuntu 26.04.1 systemd/polkit — exactly the
class of discrepancy §7/§50 require stopping and reporting on ("If real
Ubuntu 26.04.1/systemd evidence during implementation shows additional
**or different** authorization details for this exact operation beyond
what's already evidenced in the handoff, STOP and report the contract
discrepancy — do not silently discard or invent provider context").

This finding is reported here rather than resolved unilaterally. Two
observations relevant to whichever governed resolution is chosen:

1. **No authorization-relevant impact observed.** Every fixture rule in
   this evidence run branches only on `action.lookup("unit")`/
   `action.lookup("verb")`; none branches on `polkit.message`. The four
   comparison points above that *are* authorization-relevant (`action_id`,
   `unit`, `verb`, subject semantics) are all exact matches. The handoff's
   own §7 text independently anticipated this possibility: "`unit`/`verb`
   are clearly authorization-sensitive, and `polkit.message`/
   `polkit.gettext_domain` are more presentation-oriented."
2. **The mismatch is a real fact about systemd's own D-Bus behavior**, not
   an implementation defect in the reproduction logic — systemd itself does
   not interpolate `$(unit)` into the wire value of `polkit.message`; the
   substitution is a presentation-layer behavior of `pkexec`/polkit
   authentication-agent UI reading the raw template, not something the
   `CheckAuthorization` caller (systemd) performs itself before sending it.
   The handoff's own worked example appears to have assumed the
   interpolated (agent-rendered) value was what actually crosses the wire;
   it is not.

No code change was made in response to this finding beyond what is already
disclosed — implementation followed the handoff's literal evidenced value
and does not unilaterally switch to reproducing the literal
`'$(unit)'` template, since either choice is a governed contract
interpretation, not an implementation judgment call.

---

## Resolution (repair pass, governed decision applied)

**The project owner adjudicated this conflict explicitly: the runtime
capture is authoritative.** Guardian's `ProviderAuthorizationRequest` has
been corrected to reproduce the literal, unsubstituted `$(unit)` template
rather than pre-interpolating the unit name — matching real Ubuntu
26.04.1 systemd's own native wire behavior established above, not the
handoff's earlier (agent-rendered, not wire-level) worked example.

**Correction note**: earlier Wave 1 evidence/planning (the accepted
handoff's §7/§10/§12 worked example, and this implementation's original
`ProviderAuthorizationRequest::details()`) recorded the interpolated form
`"Authentication is required to restart 'cups.service'."` as the evidenced
`polkit.message` value. This fresh runtime capture establishes that real
systemd never puts the interpolated value on the wire — the literal
template `"Authentication is required to restart '$(unit)'."` is what
`CheckAuthorization` actually carries; substitution is a presentation-layer
behavior of the polkit authentication-agent UI, not something the
`CheckAuthorization` caller performs. This correction note is added
alongside the original finding above, which is preserved unmodified —
nothing here erases or rewrites the original discovery or its reasoning.

### Code change

`crates/guardian-core/src/authorization.rs`,
`ProviderAuthorizationRequest::details()`: the `polkit.message` value is now
the fixed literal string `"Authentication is required to restart
'$(unit)'."`, no longer `format!("Authentication is required to restart
'{}'.", capability.unit_name())`. This is the *only* line that changed —
`unit`, `verb`, and `polkit.gettext_domain` are unaffected, since the
comparison above already found those three (plus `action_id` and subject
semantics) to be exact matches.

### Real VM re-evidence (W1-VM-007 re-run against the corrected binary)

Re-ran the identical native-vs-mediated capture methodology above against
`guardian-g9`, rebuilt with the corrected `authorization.rs`. Mediated
capture: `docs/evidence/wave1/mediated_checkauth_fixed.txt`.

| Field | Native (`systemctl restart`, unchanged from above) | Mediated (corrected `guardian-helper`) | Match |
|---|---|---|---|
| `action_id` | `org.freedesktop.systemd1.manage-units` | `org.freedesktop.systemd1.manage-units` | **Identical** |
| detail `unit` | `cups.service` | `cups.service` | **Identical** |
| detail `verb` | `restart` | `restart` | **Identical** |
| detail `polkit.gettext_domain` | `systemd` | `systemd` | **Identical** |
| detail `polkit.message` | `Authentication is required to restart '$(unit)'.` | `Authentication is required to restart '$(unit)'.` | **Identical (was: differs)** |
| Subject kind | `system-bus-name` | `system-bus-name` | Identical |
| Subject name | real original caller's own bus name | real original caller's own bus name (`:1.361`, the `wave1allowed` connection) | Identical semantics |
| `flags`/`cancellation_id` | caller-controlled / `""` | caller-controlled / `""` | Unchanged from above — not authorization-relevant |

Captured mediated request (from `mediated_checkauth_fixed.txt`):

```
STRING "org.freedesktop.systemd1.manage-units";
ARRAY "{ss}" {
        DICT_ENTRY "ss" {
                STRING "polkit.message";
                STRING "Authentication is required to restart '$(unit)'.";
        };
        DICT_ENTRY "ss" {
                STRING "polkit.gettext_domain";
                STRING "systemd";
        };
        DICT_ENTRY "ss" {
                STRING "unit";
                STRING "cups.service";
        };
        DICT_ENTRY "ss" {
                STRING "verb";
                STRING "restart";
        };
};
```

**Semantic equality is now exact across every field this comparison
tracks.** The one previously-reported discrepancy is closed; no other
field changed. `crates/guardian-core/tests/wave1_authorization_contract.rs`
was updated to assert the corrected literal template (and to no longer
assert that `polkit.message` varies with the unit name, since it is now
systemd's own fixed wire text).
