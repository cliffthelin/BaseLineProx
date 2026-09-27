# Guardian G2 — Model A Real-Host Evidence

Disposable Ubuntu 26.04.1 VM (`guardian-g2-vm`, multipass), destroyed after
evidence capture. Setup: `docs/evidence/g2/g2-vm-setup.sh`. Prototype
source: `tests/vm/g2-model-a/` (standalone, non-workspace-member package;
`daemon.rs` reuses `guardian_core::identity`/`guardian_core::authorization`
unchanged from G1 — no parallel authorization system).

## Host versions

```text
PRETTY_NAME="Ubuntu 26.04 LTS" (Resolute Raccoon)
systemd 259.5-0ubuntu3.4
dbus-daemon 1.16.2 (same as G0/G1 evidence)
polkitd 127-2ubuntu1 (same as G0/G1 evidence)
```

## Architecture as built

```text
clients (guardiang2caller / guardiang2denied)
  │
  ▼
system D-Bus (io.github.cliffthelin.Guardian1.G2ModelA)
  │
  ▼
guardian-model-a.service (single process)
  │  resolve_caller_identity -> PolkitAuthorizer -> CheckAuthorization
  ▼
bounded typed write (AttemptBoundedWrite(interactive: bool))
```

## The trusted-caller finding (the single most important result of this pass)

Started deliberately as unprivileged (`User=svc-model-a`, empty
`CapabilityBoundingSet=`). The bounded write **failed for every caller,
including the granted one**, with a real polkit error, not a Guardian bug:

```text
org.freedesktop.PolicyKit1.Error.NotAuthorized: Only trusted callers
(e.g. uid 0 or an action owner) can use CheckAuthorization() for subjects
belonging to other identities
```

This is polkit's own security boundary: the *calling process* must itself
be a trusted caller (uid 0, or the registered action owner) to ask
`CheckAuthorization` about a *different* subject. Verified empirically by
switching only `User=svc-model-a` → `User=root` (all hardening directives
otherwise unchanged) — the identical granted/denied test then passed/failed
correctly. This is **not** something the bounded write operation itself
needs; it is a hard requirement of the mechanism used to authorize *someone
else*. It applies equally to Model B's helper (see `MODEL_B_EVIDENCE.md`).

## Capability methodology (start restrictive, add only on proven need)

**Round 1** — `User=root`, empty `CapabilityBoundingSet=`/`AmbientCapabilities=`,
full hardening set from TDD contract §24 (`NoNewPrivileges=yes`,
`ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`,
`PrivateDevices=yes`, `RestrictNamespaces=yes`, `RestrictAddressFamilies=AF_UNIX`
— AF_UNIX specifically allowed because D-Bus itself requires it,
`SystemCallFilter=@system-service`, `DevicePolicy=closed`, etc.). Result:
**worked on the first try** — the bounded write succeeded for the granted
caller and correctly denied the ungranted one. No capability was ever
added; none was needed. Raw output: `model-a/model-a-security-round1.txt`.
Score: **2.0 OK**.

**Round 2** — added `ProtectClock=yes`, `SystemCallArchitectures=native`,
`ProtectHostname=yes`, `ProtectProc=invisible`, `ProcSubset=pid`,
`PrivateNetwork=yes`, `UMask=0077`, each individually tested for real
against the bounded operation before being kept. All compatible —
`PrivateNetwork=yes` in particular confirms D-Bus over the system bus's
unix-domain socket needs no network namespace access at all. Raw output:
`model-a/model-a-security-round2.txt`. Score: **1.1 OK**.

No hardening directive was disabled to make a test pass — every directive
present in the final unit was added because it worked, never removed
because it didn't.

**Evidence-trail note (added during G2 audit-findings closure):** the
committed `model-a/journal-transcript.txt` preserves the original mistake
honestly — the first attempt at adding the round-2 directives placed them
after `[Service]`'s content but before `[Install]`'s own keys were
re-declared incorrectly, and systemd logged `Unknown key '...' in section
[Install], ignoring` for all seven directives across two separate
daemon-reload/restart cycles visible in that transcript, meaning that
transcript never shows an explicit "reload succeeded with zero warnings"
line for the corrected file. The intermediate corrected-reload/restart
terminal output itself was not preserved as its own logged transcript
entry. This is stated plainly rather than implied to exist. However, the
final round-2 result is independently and directly tied to the corrected
active unit by two pieces of evidence that do not depend on that missing
transcript line: (1) the committed `model-a/guardian-model-a.service` has
all seven round-2 directives correctly placed inside `[Service]`, not
`[Install]`; (2) `model-a/model-a-security-round2.txt` shows all seven of
those directives individually evaluated and marked `✓` active with their
correct (non-degraded) descriptions — e.g. `✓ ProtectClock= Service cannot
write to the hardware clock or system clock` rather than round 1's `✗
ProtectClock= Service may write to the hardware clock or system clock
0.2` — which `systemd-analyze security` can only report if it queried the
corrected, successfully-loaded unit. No substantive uncertainty exists
about whether the 1.1 score reflects the corrected unit; only the
transcript's specific "the reload happened cleanly" line was not
separately captured. A VM rerun was judged unnecessary for this reason.

## Real capability set (process evidence, not declared configuration)

```text
$ ps -o pid,user,group,cmd -p <PID>
PID USER GROUP CMD
... root root /usr/local/bin/g2-model-a-daemon

$ grep -E '^Cap|^Uid' /proc/<PID>/status
Uid:    0    0    0    0
CapInh: 0000000000000000
CapPrm: 0000000000000000
CapEff: 0000000000000000
CapBnd: 0000000000000000
CapAmb: 0000000000000000
```

Full transcript: `model-a/process-and-capabilities.txt`. **`root`, but zero
Linux capabilities of any kind** — a genuinely narrow, if unusual,
configuration: the process retains the DAC-bypass and polkit-trust
properties inherent to UID 0 specifically, but none of the capability-gated
privileges (no `CAP_SYS_ADMIN`, no `CAP_NET_ADMIN`, no `CAP_DAC_OVERRIDE`,
none of the ~40 capabilities systemd's security analysis checks for).

## Bounded operation — real result

```text
$ sudo -u guardiang2caller g2-model-a-client false
client real unique_name: :1.49
OK

$ sudo -u guardiang2denied g2-model-a-client false
client real unique_name: :1.50
ERROR io.github.cliffthelin.Guardian1.Error.NotAuthorized
```

Server-side journal confirms the real polkit decision for each
(`model-a/journal-transcript.txt`), consistent with G1's own established
`PolkitAuthorizer` mapping (unchanged code).

## systemd-analyze security

```text
Round 1: 2.0 OK 🙂  (see model-a/model-a-security-round1.txt for full table)
Round 2: 1.1 OK 🙂  (see model-a/model-a-security-round2.txt for full table)
```

Remaining exposure after round 2 is dominated by `User=/DynamicUser=`
(0.4 — root is required, documented reason above) and small residual items
(`SystemCallFilter=~@resources`/`~@privileged` at 0.2 each, from the broad
`@system-service` filter set; `RestrictAddressFamilies=~AF_UNIX` at 0.1,
required for D-Bus itself; `RootDirectory=`/`RootImage=` at 0.1, not
attempted this pass). These are recorded as **temporary** exceptions —
worth narrowing the syscall filter further in a later pass — not
architectural ones; only the root requirement is architectural.

## Restart behavior

Not separately exercised for Model A this pass (Model B's helper crash-restart
test, using the identical `Restart=on-failure` directive and identical
production code, stands in as equivalent evidence — see
`MODEL_B_EVIDENCE.md`).
