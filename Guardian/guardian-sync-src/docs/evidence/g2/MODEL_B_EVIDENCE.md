# Guardian G2 — Model B Real-Host Evidence

Same disposable VM session as `MODEL_A_EVIDENCE.md` (`guardian-g2-vm`,
destroyed after capture). Prototype source: `tests/vm/g2-model-b/` — `core.rs`
(unprivileged), `helper.rs` (privileged, reuses G1's identity/authorization
code unchanged, identical to Model A's daemon).

## The relay-topology finding — read this first

The G2 implementation handoff's Model B diagram shows `client → core →
typed privileged IPC → helper`. **This literal topology cannot honor G1's
real-caller-authorization invariant**, and this pass demonstrates why
concretely rather than asserting it:

D-Bus does not forward sender identity through a relay. If `core` received
a client's request and made its *own* D-Bus call to `helper` to relay it,
`helper`'s `resolve_caller_identity` would resolve **`core`'s** identity —
never the original client's — because the sender of that specific message
*is* core's connection. There is no D-Bus mechanism to transparently
proxy the original sender through an intermediary hop. Any design that
tried to work around this by having `core` pass the client's UID/username
as a method argument would be exactly the confused-deputy vulnerability
G1's handoff and this gate's confused-deputy analysis explicitly forbid
(§8/§11 of `GUARDIAN_G2_IMPLEMENTATION_HANDOFF.md`) — a claim forwarded by
an intermediary, trusted without independent verification.

**The safe realization actually built and evidenced this pass:** clients
call the helper **directly** for the bounded write. `core` is never in the
write path at all — it exists only for the unprivileged
monitoring/correlation role and is architecturally incapable of relaying a
privileged write, because it has no code path that does so.

```text
client (write)  ──────────────────────────►  guardian-model-b-helper.service
                                               (privileged, resolves REAL
                                                caller, real CheckAuthorization)

client (read)   ──►  guardian-model-b-core.service
                      (unprivileged, never touches privilege)
```

This is a genuine correction to the handoff's illustrative diagram, not a
deviation from its intent — §7's own text already required "the helper
independently verifies caller authorization via real polkit... or trusts a
claim forwarded by the core" as the thing to test, and this is exactly what
was tested and found: the trust-the-core path is unsafe by construction,
so the direct-call path is what was built and measured.

## Confused-deputy proof — real live introspection, not a code read

```text
$ gdbus introspect --system \
    --dest io.github.cliffthelin.Guardian1.G2ModelBHelper \
    --object-path /io/github/cliffthelin/Guardian1/G2ModelBHelper

interface io.github.cliffthelin.G2ModelBHelper1 {
  methods:
    AttemptBoundedWrite(in  b interactive);
    MutationCount(out u arg_0);
    LastOrderingTrace(out as arg_0);
  ...
```

Full transcript: `model-b/helper-live-introspection.txt`. The entire public
method surface takes exactly one input argument — a boolean. There is no
`uid`, `pid`, `username`, `claimed_identity`, or any other parameter a
relaying process could populate. This is the same structural guarantee G1
established for `AuthorizationRequest`, now confirmed against the *real,
running, D-Bus-introspected* helper rather than only against source code.

## Trusted-caller finding — applies identically to the helper

Exactly as found for Model A (`MODEL_A_EVIDENCE.md`): the helper must run
as `User=root` for the same polkit `CheckAuthorization`-trust reason. This
is **symmetric between models** — it is not a Model A vs. Model B
differentiator. `core` is unaffected: it performs no polkit calls at all
and stays fully unprivileged.

## Capability methodology and real capability sets

Both units started from the same restrictive TDD contract §24 baseline as
Model A (round 1 + round 2 directives identical), tested for real before
being kept. `core` additionally received `PrivateUsers=yes`, which Model A
and the helper did not attempt (root's real-UID-visible-to-polkit
requirement makes user-namespace isolation a risk not worth taking for the
privileged component without further research; `core` has no such
constraint since it never calls polkit).

```text
$ ps -o pid,user,group,cmd -p <core-PID>
... svc-model-b-core svc-model-b-core /usr/local/bin/g2-model-b-core
Uid: 997  997  997  997
CapBnd: 0000000000000000  (all Cap* lines zero)

$ ps -o pid,user,group,cmd -p <helper-PID>
... root root /usr/local/bin/g2-model-b-helper
Uid: 0  0  0  0
CapBnd: 0000000000000000  (all Cap* lines zero, identical to Model A's daemon)
```

Full transcript: `model-b/process-and-capabilities.txt`.

## Bounded operation — real result

```text
$ sudo -u guardiang2caller g2-model-b-client read
OK core-status-ok reads=1

$ sudo -u guardiang2caller g2-model-b-client write false
OK

$ sudo -u guardiang2denied g2-model-b-client write false
ERROR io.github.cliffthelin.Guardian1.Error.NotAuthorized
```

Both the read (via `core`, no authorization needed) and the write (via
`helper`, direct call, real authorization) behave correctly.

## systemd-analyze security

```text
guardian-model-b-core.service:   0.6 SAFE 😀   (model-b/model-b-core-security.txt)
guardian-model-b-helper.service: 1.1 OK  🙂   (model-b/model-b-helper-security.txt)
```

**This is the central quantitative comparison of the whole gate.** The
helper's score is *identical* to Model A's daemon (1.1) — Model B does
**not** reduce the exposure of the privileged component itself; both need
the same root/zero-capability profile for the same polkit reason. What
Model B changes is *how much code* carries that exposure: the helper's
surface is fixed at three narrow methods, while `core` — where Guardian's
actual growth is expected to live per the TDD contract (Capability
Registry, Provider Arbitrator, PSI event engine, Diagnostic Budget, Flight
Recorder, Event/Incident correlation — all read/monitoring-heavy, GP-02
read-by-default) — measures genuinely safer (0.6, including a user
namespace) and never needs to touch privilege at all as it grows.

## Restart behavior — real, not reasoned-about

```text
$ sudo kill -9 <helper-PID>
$ sleep 2 && systemctl is-active guardian-model-b-helper.service
active
$ sudo -u guardiang2caller g2-model-b-client write false
OK
```

Journal (`model-b/journal-transcript.txt`) confirms: `Restart=on-failure`
brought the helper back in ~2 seconds under a new PID and a new D-Bus
unique name; the granted caller's next request succeeded normally. The
helper's **in-memory** `mutation_count`/`ordering_log` reset to zero on
restart — real evidence, not reasoning, that any topology's in-process
state does not survive a crash, which is direct input to the Transaction
Compatibility section of `ADR-002-guardian-privilege-topology.md`: G4 will
need externally persisted transaction records regardless of which topology
is selected, since this loss is a property of process restart, not of
which model owns the process.

`core` restart/crash was not separately exercised this pass — `core`
performs no privileged operation and no transaction-relevant state, so its
crash-recovery profile is a plain stateless-service-restart case already
well covered by systemd's own `Restart=` semantics; re-running the same
kill-and-observe test for it would not add new evidence beyond what was
already confirmed for the helper.
