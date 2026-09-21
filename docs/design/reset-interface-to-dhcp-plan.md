# Implementation plan v3: host-network repair (static → DHCP)

Host-network repair vertical slice — the first bounded action under the
BaselineOS host repair plane (v0.3 design, layer 1). **Approved for
implementation 2026-09-20**, now implemented on branch
`repair/host-network-reset-to-dhcp` (draft PR, not merged). Originally written
against `cliffthelin/baseline` HEAD `07eda93`.

## Current shipped guarantee — read this before the rest of the document

This document describes the full approved design, including pieces that are
**not yet installed**. Do not read any section below as describing what the
running code currently does without checking this list first:

- **Same-boot automatic rollback** (the transient systemd timer, armed before
  any write, independent of the Baseline/TUI/repair-worker process) —
  **shipped and unit-tested.** Survives Baseline crashing, the TUI being
  killed, or the repair worker hanging.
- **Boot-time recovery logic** (`repair_rollback.py::boot_time_recovery()`,
  the function a permanent dormant service would call) — **implemented and
  unit-tested**, but the systemd unit that would run it at boot is **not
  installed**, and `boot/provision.sh` does not deploy or enable one.
- **A reboot during the 120-second same-boot rollback window is NOT yet
  protected.** The permanent recovery service this needs has not been
  validated against a real Proxmox/Debian host's boot ordering — see
  [v3](#revision-note-v2--v3) below for exactly what's blocking it.
- **No physical host has been modified.** Everything above has only ever run
  against a `FakeRunner` in the unit test suite.

If you're reading the UI's repair-proposal screen or this document's own
earlier design sections and they read as though rollback survives a reboot
today, that's the *design target*, not the current guarantee — this section
is the correction.

## Revision note (v2 → v3)

Cliff's third review round, approved for implementation:

1. **Hybrid rollback**, replacing v2's single "install a persistent unit per
   attempt" idea (which the [Open items](#open-items-for-this-review) below
   had already flagged as needing confirmation): a **transient** systemd
   timer (`systemd-run`, never written to disk) for the ordinary 120-second
   same-boot window, plus **one permanent, dormant** recovery service —
   installed once during provisioning, inert until a pending-repair manifest
   exists — for the reboot-during-window case specifically. This avoids
   generating and enabling a new persistent unit on every single repair
   attempt while still covering reboot. See the rewritten
   [Independent rollback](#step-4-in-detail-arming-an-independent-rollback)
   section below.
2. **Standalone-host-only boundary**: refuse outright, action-wide, on any
   evidence of Proxmox cluster membership (`/etc/pve/corosync.conf`,
   `/etc/corosync/corosync.conf`, or `pvecm status` reporting membership) —
   a TCP-connection check can't adequately protect Corosync or the rest of a
   cluster's non-TCP dependencies, and multi-node Proxmox stays out of scope.
3. **Remote-session detection**: confirmed as acceptable — don't try to infer
   which session "belongs to" the operator; treat any live SSH/`:8006`/
   configured-port session as protected, full stop. A future remote Baseline
   interface must carry authenticated session identity explicitly rather than
   this deriving identity from socket inspection.
4. Installing the permanent recovery service is **conditional on proving**
   real Proxmox/Debian systemd boot ordering (after the filesystem holding
   the backup is available, before `networking.service`/ifupdown2's startup
   path consumes the candidate config) — **not** to be implemented
   speculatively if that ordering can't be verified. It couldn't be, from
   this environment (no real Proxmox/Debian host, and `ifupdown2`/
   `deb.debian.org` aren't reachable from this Ubuntu-based session) — so it
   wasn't installed. A read-only environment probe (see
   `boot/baseline-repair-env-probe.sh`) now exists specifically to collect
   the real facts needed to design that service safely, the next time this
   runs against an actual host.

## Revision note (v1 → v2)

Cliff reviewed v1 and required four corrections, all incorporated below:

1. The action targets the **configured Layer-3 interface** Baseline derives
   from topology, not a physical NIC parameter — v1's `nic`-must-be-physical
   precondition was wrong for the standard Proxmox `vmbr0` bridge topology,
   where the static config to fix lives on the bridge, not the NIC.
2. The rollback must be **armed through an independent host mechanism before
   the change is applied**, so it survives Baseline crashing, its repair
   worker hanging, the TUI being killed, or a reboot mid-window — not polled
   from inside the same process that made the change.
3. Post-change verification must be **bound to the repaired interface
   specifically**, not the existing global `check_lifeline()` — a healthy USB
   tether or second NIC could make a still-broken `vmbr0` look fixed.
4. The write must protect the **whole configuration file/closure** `ifreload
   -a` would touch, not just the one stanza being changed, and detect if
   something else edited the config between proposal and execution.

Also incorporated: `ifupdown2` is detected as a capability and the action
refuses cleanly if it's absent, rather than being assumed or silently falling
back to `ifdown`/`ifup`; a wider connection-protection list than "any TCP
connection"; longer backup retention; an expanded test matrix; and an explicit
integration-test requirement before the first real run on the physical
Baseline host. Everything below supersedes v1's equivalent sections.

**Explicitly out of scope, unchanged from v1:** the ADR 0001 `bridge-ports`
naming-a-missing-device symptom is a separate diagnosis and a separate future
bounded action — not folded into this one. Also explicitly out of scope: the
seven Proxmox diagnostic tools Cliff provided separately are a related
provisioning/capability increment, tracked on their own — this plan doesn't
reference or depend on them, and they aren't detailed here since they weren't
shared in this thread.

## Where this lands in the codebase

Unchanged from v1's proposal:

- **New module `baseline/lib/repair.py`** — topology derivation, precondition
  validation, backup, transactional write, execution, verification, and
  event logging for this action.
- **New standalone entry point `baseline/lib/repair_rollback.py`** (new in
  v2) — the independent rollback executor. Deliberately small and
  dependency-light (stdlib only, no Textual/Rich import) so it can run
  correctly even if something in Baseline's main app is broken; this is what
  the armed systemd unit actually calls.
- **`harness.py`** gains `propose_repair(facts)` — same zero-tools
  invocation, a structured-JSON prompt template instead of prose. Unchanged
  from v1.
- **`bin/baseline`** gains a confirmation modal in the existing Chat-tab
  surface. Unchanged from v1.
- **Event log** — `component=repair` records in the existing
  `/var/log/baseline/network.events.jsonl`. Schema expanded in v2 (below).

## Target derivation (replaces v1's `nic` parameter)

The bounded action's signature is now:

```
reset_interface_to_dhcp(target_interface: str, requested_by: str) -> RepairResult
```

`target_interface` is a **logical Layer-3 interface name** (`vmbr0`, a
physical NIC, a bond, or a VLAN device) — whichever one actually carries the
static IPv4 config that's wrong. The harness may propose a `target_interface`
in its JSON output, but Baseline never trusts that proposal as the actual
target; it derives the real target itself, independently, the same way the
management-interface guard already refuses to trust the model's stated
`reasoning` in v1:

1. Find the interface currently owning the failed address/default-route
   attempt — the same device `network.py::_route_default()` already
   identifies, cross-referenced against which device the failing
   `gateway_reachable`/`address_assigned` fact was recorded against.
2. Parse `/etc/network/interfaces` (and any `interfaces.d/*` fragments it
   sources) into a real topology graph: which stanzas are physical, bonded,
   VLAN, or bridged, and for a bridge, its `bridge-ports` membership. A
   physical member of a bridge is expected to read `inet manual` — that's
   correct, not a bug, and is never itself a repair target.
3. Walk from the failing device to the stanza that actually declares the
   static `inet` config needing to change — for the standard `vmbr0` case,
   that's the bridge's own stanza, not its physical member's.
4. If exactly one candidate stanza is found this way, that's
   `target_interface`, regardless of what the harness proposed. If the
   harness proposed something different, that's logged as a discrepancy but
   Baseline's derivation wins.
5. **If more than one credible candidate exists** (e.g. an ambiguous or
   unusual topology), the action refuses outright — no default weighting or
   preference is applied. Baseline instead presents the validated candidates
   to the operator and asks them to pick, through the same Chat-tab
   authorization surface; nothing executes on an automatic choice among
   ambiguous options.

The `bridge-ports`-names-a-missing-device case stays out of scope: if the
topology walk hits that specific problem, the action refuses with that
diagnosis named, and does not attempt to repair it.

## `ifupdown2` capability detection

No longer assumed. Before anything else:

- Confirm `ifreload` is on `PATH` and report its version.
- Confirm the system is actually running `ifupdown2` (not classic `ifupdown`)
  — e.g. via `dpkg -s ifupdown2` succeeding, consistent with how the target
  is Debian/Proxmox VE.
- Confirm the parsed `/etc/network/interfaces` topology matches ifupdown2's
  expected model (stanza syntax, `source`/`source-directory` directives
  Baseline's parser actually understands).
- Any of the above failing → refuse with a distinct, clearly labeled
  `unsupported_environment` result (not folded into the generic precondition-
  refusal path, so an operator or the changelog can tell "this host isn't
  set up the way this action expects" apart from "this host's config is
  broken in a way this action would fix").
- **No fallback to `ifdown`/`ifup`.** Bringing the management bridge fully
  down as part of a fallback path is strictly more disruptive than refusing
  and telling the operator ifupdown2 isn't present.
- The exact reload/validate command and flags are confirmed against the
  *installed* `ifupdown2` version at runtime (its `--help`/version output),
  not hardcoded from assumption, since flag availability can differ across
  versions.

## Preconditions (unchanged in spirit from v1, restated against `target_interface`)

1. `target_interface` exists and was derived per the section above (not
   accepted as a bare model proposal).
2. `network.py::check_lifeline()`, re-run fresh, currently shows a failure
   whose device resolves to this `target_interface` through the topology
   walk (a bridge's failure is attributed to the bridge, even though the
   raw NIC is what actually lost carrier upstream).
3. The relevant physical device(s) underneath `target_interface` have
   carrier.
4. `target_interface`'s stanza is currently static `inet` — already-`dhcp`
   is a no-op refusal, not a success.
5. Exactly one credible target was found (ambiguity refuses, per above).
6. `ifupdown2` capability confirmed present and compatible (above).
7. The backup, hash-verified, must exist before anything else proceeds.

## The transactional pipeline

Cliff's required order, followed exactly:

```
1. discover topology
2. validate candidate (target_interface, single unambiguous match)
3. create and byte-verify backup
4. arm independent rollback  ← before any write
5. write candidate atomically
6. validate syntax (without applying)
7. apply
8. verify lifeline (target-bound, see below)
9. cancel rollback only on success
```

Failure handling, exactly as specified:

- **Write or syntax validation fails, before application:** restore
  immediately from the byte-verified backup, record the failure, and the
  independent rollback (already armed in step 4) is cancelled once that
  restore is itself confirmed — nothing was ever actually applied, so there's
  nothing for the armed mechanism to still be guarding.
- **Application or post-apply verification fails:** the independent rollback
  stays armed and is left to fire on its own; Baseline does not race it by
  also trying to restore inline. Once it fires (or Baseline confirms the
  change is being reverted), the restoration is itself verified before the
  attempt is marked closed.

### Step 4 in detail: arming an independent rollback (hybrid design, v3)

A process-internal poll-and-restore (v1's design) doesn't survive Baseline
crashing, the repair worker hanging, the TUI being killed, or a reboot during
the window — all four are named failure modes to protect against. The v3
hybrid design covers the first three today and is *designed for* the fourth,
pending the boot-ordering proof described in
[Current shipped guarantee](#current-shipped-guarantee--read-this-before-the-rest-of-the-document):

- **Before step 5 writes anything**, Baseline atomically creates the
  verified backup and a narrow, restore-only **pending manifest**
  (`attempt_id`, `target_interface`, `rollback_unit`, `created_at` — see
  `repair.write_pending_manifest`) at
  `/var/lib/baseline/repair/pending/manifest.json`, then arms a genuinely
  **transient** systemd timer (`systemd-run --unit=... --on-active=120
  --collect`, never written to `/etc/systemd/system/`) calling
  `/opt/baseline/bin/baseline-repair-rollback same-boot <attempt-id>`. This
  transient timer is what covers Baseline/TUI/worker crash or hang today —
  systemd itself, not this process, holds it.
- **Shipped, not yet installed:** one **permanent, dormant** recovery
  service — installed once during provisioning (not generated per attempt),
  inert until it finds a pending manifest at boot, calling the same
  standalone `repair_rollback.py::boot_time_recovery()` this transient path
  also uses. This is what would additionally cover a reboot during the
  window. Its logic exists and is unit-tested (`test_boot_time_recovery_*`),
  but no `.service`/`.timer` unit file exists, and `boot/provision.sh`
  doesn't install or enable one — see the v3 revision note above for why,
  and `boot/baseline-repair-env-probe.sh` for the read-only probe that now
  exists to collect what installing it safely would need to know.
- `repair_rollback.py` is deliberately standalone (stdlib only): it restores
  the backup, runs `ifreload -a` (or the confirmed equivalent), and performs
  the same target-bound verification described below, logging its own
  outcome independently of whether the main Baseline process is even
  running.
- **Cancellation** (step 9) means: stop the transient timer
  (`systemctl stop <unit>.timer`) and clear the pending manifest — and this
  happens *only* after the target-bound verification in step 8 independently
  confirms success. A crash between "verification passed" and "cancellation
  ran" fails safe: the rollback fires anyway, restoring known-good config on
  a connection that was actually fine — an unnecessary revert, not a stuck
  broken one.

## Target-bound verification (replaces v1's reliance on global `check_lifeline()`)

Global reachability can be a false positive: a working USB tether or a second
NIC can make a still-broken `vmbr0` look fine. Verification must instead
prove, specifically about `target_interface`:

- It acquired an address via DHCP (not a stale cached address left over from
  before the change).
- It's administratively and operationally up.
- The route table shows the default route (or the relevant route for this
  interface's role) actually associated with `target_interface`, not just
  present somewhere.
- The gateway is reachable **through this specific interface** — reusing
  `network.py`'s existing device-bound probe pattern (`ping -I <dev>`, the
  same technique that already fixed the "wrong interface answered" bug
  documented in `BAREMETAL_BRINGUP_NOTES.md`), not a general, device-agnostic
  reachability check.
- It stays healthy across a short stabilization interval (a second check a
  few seconds after the first), so a lease that binds and then immediately
  drops isn't recorded as success.

On rollback, two distinct outcomes are logged, not conflated:

- **Configuration restoration confirmed** — the original bytes are back
  (hash-verified) and `ifreload -a` completed. This can and should succeed
  even if the interface doesn't come back up, because...
- **Connectivity restored** — the interface reached the same state it was in
  before the repair attempt. This is *not* required to equal "gateway
  reachable" — the original static config may itself have been unreachable
  (that's the whole reason a repair was proposed). Rollback success means
  "we're back to the known state we started from," not "the network now
  works."

## Protecting the full configuration transaction

`ifreload -a` can apply unrelated pending edits elsewhere in
`/etc/network/interfaces`, not just the stanza this action touched. Before
writing:

- Resolve and hash the **complete configuration closure** involved in the
  reload — the main file plus every `source`/`source-directory` fragment
  ifupdown2 would actually read.
- Record that hash at proposal time, again immediately before writing (step
  5), and refuse if it changed — something else (another process, an
  operator editing by hand) touched relevant config in between, and this
  action does not overwrite a change it didn't make or review.
- Write the new stanza atomically (write-temp-then-rename), preserving the
  original file's ownership, mode, and other metadata.
- Prefer a target-scoped reload if the installed `ifupdown2` version supports
  one; otherwise, only proceed with the full `ifreload -a` once the
  closure-hash check above has proven nothing else in scope changed.
- Rollback never overwrites a change made by something else after the repair
  attempt — it restores exactly the bytes it backed up, and if the current
  live file no longer matches what this attempt wrote (someone else changed
  it again since), that's logged as a conflict rather than blindly clobbered.

## Consent and the connection guard

- **Authorization timeout:** 5 minutes, unchanged from v1. No response →
  declined, logged, attempt's backup and rollback descriptor are retained
  per the retention policy (not deleted — an attempt that got this far
  already touched nothing, but the record itself has value).
- **Revalidation immediately before execution:** every precondition,
  including topology derivation and the closure hash, is rerun right before
  step 5. If anything material changed since the operator authorized the
  original proposal, that authorization no longer applies — a **new**
  proposal is presented, requiring fresh authorization, rather than
  proceeding on stale consent.
- **Connection guard**, replacing v1's "any TCP connection" rule: protects
  specific management paths rather than blocking on every connection through
  the device —
  - SSH, including any non-default configured SSH port.
  - Proxmox's web/API port (TCP 8006).
  - Whatever connection can be identified as the operator's own current
    remote management session, if one exists.
  - Any additional operator-configured protected ports.
  An unrelated, transient connection through the interface no longer
  permanently blocks a legitimate repair. When a protected remote session is
  detected, the action refuses **unattended** execution outright. An
  operator physically present on tty1 may explicitly authorize the
  disruption after being shown that the protected session will be lost —
  but a *remote* session is never allowed to authorize severing its own
  access path; that authorization can only come from the local console.

## Backup and audit retention

- Backups are **immutable and timestamped**, one directory per attempt under
  `/var/lib/baseline/repair/<attempt-id>/`.
- Retention: keep at least the **last 10 attempts or 30 days of history,
  whichever preserves more** — not pruned at the start of the next attempt,
  as v1 proposed.
- An incomplete or failed repair's backup is **never overwritten** — it's
  retained under the retention policy like any other attempt, since it's
  exactly the record most likely to matter later.

## Event logging (schema, expanded)

Same `component=repair` JSONL shape as v1, with fields added for the v2
mechanics: `target_interface` (the derived one, plus the harness's original
proposal if different), `topology` (physical/bonded/VLAN/bridged and the
underlying device chain), `backup_hash`, `candidate_hash`, `closure_hash`
(before and immediately-before-write), the systemd unit name backing the
armed rollback, and, on rollback, the two distinct outcomes
(`config_restoration_confirmed` / `connectivity_restored`) rather than one
collapsed flag.

## The AI/Baseline boundary, restated

Unchanged: `--tools ""`, zero tools. The harness may propose an action name
and a candidate `target_interface`; Baseline derives the real target itself
and never executes on the harness's word. Every step of the pipeline above is
Baseline's own code. Authority model unchanged: **AI proposes → Baseline
validates → human/policy authorizes → Baseline executes through a bounded
action → Baseline independently verifies → rollback remains available.**

## Test strategy (expanded)

Unit tests (no real device/root access, same injectable-runner /
injectable-path approach as v1) now need to cover the topology-derivation
logic specifically, not just the static→dhcp stanza rewrite:

- Static address directly on a physical interface (the simple case).
- Standard Proxmox `vmbr0` management-bridge topology (the common case v1
  got wrong).
- A bond plus a bridge on top of it.
- A VLAN interface.
- A topology with multiple credible management-interface candidates →
  confirms refusal, not a guess.
- USB tether or a second NIC masking a still-broken primary target →
  confirms target-bound verification catches what global `check_lifeline()`
  would miss.
- Configuration changed by something else between authorization and
  execution → confirms the closure-hash check refuses/re-proposes rather than
  overwriting.
- Baseline's process killed immediately after step 7 (apply) → confirms the
  independently-armed systemd rollback still fires and restores correctly
  with no Baseline process running at all.
- Rollback restoring the original **broken-but-known** state → confirms
  rollback is judged by "configuration restoration confirmed," not
  "gateway reachable."

**Integration test, required before any run on the physical Baseline host:**
mocked command output can prove the Python logic is internally consistent,
but it cannot prove `ifreload`, real bridge topology, actual DHCP
acquisition, the systemd-based rollback, and a real loss of connectivity
correctly interact with each other. Before the first real application:

- Either an isolated network namespace test harness, or a disposable Proxmox
  VM with console access and a recoverable snapshot to roll back to
  regardless of what the test does to its networking.
- This integration test runs and passes before the action is ever tried
  against the physical Baseline host.

## Open items for this review (v2 — resolved in v3, kept for history)

Both items below were resolved by Cliff's third review round (see
[Revision note (v2 → v3)](#revision-note-v2--v3)): (1) → the hybrid design
(transient same-boot timer + one permanent dormant service, not a
per-attempt persistent unit); (2) → confirmed as acceptable, don't try to
infer the operator's specific session.

1. ~~**"Transient" vs. persistent rollback unit.**~~ Resolved: hybrid design,
   see above.
2. ~~**Detecting "the operator's current remote management session."**~~
   Resolved: treat any live protected-port session as protected, don't infer
   whose it is; a future remote interface carries identity explicitly.

## Required merge blockers (v3)

The plan is approved and implemented, but two things must still happen
before the branch is mergeable — see the draft PR for the authoritative,
current status of each:

1. **Validate and install the dormant boot-recovery service** against an
   actual disposable Proxmox environment — the boot-ordering proof v3's
   revision note makes installing it conditional on. `boot/baseline-repair-
   env-probe.sh` (read-only, makes no configuration changes) collects the
   facts needed to design it safely: Proxmox/Debian versions, the installed
   `ifupdown2` version, `networking.service`'s actual unit contents, the
   `network-pre.target`/`network.target`/local-filesystem ordering, where the
   pending manifest and backup would actually live and whether `/var` is on
   the root filesystem or separately mounted, and the current interfaces
   closure — with addresses/identifiers not needed for ordering analysis
   redacted.
2. **Pass the real ifupdown2/bridge/DHCP/systemd integration test** — see
   [Test strategy](#test-strategy-expanded) above; the unit suite proves the
   Python logic is internally consistent, not that real `ifreload`/bridge
   topology/DHCP acquisition/the systemd rollback interact correctly. Full
   scenario list: successful DHCP conversion + rollback cancellation; DHCP
   failure + same-boot timed rollback; Baseline killed immediately after
   application + rollback still fires; a reboot immediately after
   application + boot-time restoration (blocked on item 1); USB/secondary
   connectivity not masking target-interface failure; a concurrent
   configuration change causing refusal; and standard `vmbr0`, bond+bridge,
   and VLAN topologies.

No code will be written for either blocker speculatively; both wait on real
results from an actual Proxmox/Debian environment.
