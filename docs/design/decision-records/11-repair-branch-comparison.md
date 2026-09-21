# Decision record: comparison against existing host-network repair (`cliffthelin/baseline`, `repair/host-network-reset-to-dhcp`)

Date: 2026-09-21
Investigator: Claude Code
Status: complete, read-only analysis only. **No code copied, no push or modification to `cliffthelin/baseline`, no new QEMU installation, no privileged operation.** The branch was inspected via `git fetch cliff repair/host-network-reset-to-dhcp` (a read-only fetch, confirmed non-interactive, no prompt) and `git show`/`git diff` against the fetched ref — the working tree's checked-out branch (`main`) was never touched.

## 1. What actually exists on the branch

Fetched cleanly. Confirmed both cited commits are real and present: `0368d7a` ("feat: host-network repair vertical slice - reset_interface_to_dhcp") and `8509af6` ("Doc/UI accuracy pass + read-only boot-order environment probe"), on top of `07eda93`. Draft PR #1 confirmed via `gh pr view 1 --repo cliffthelin/baseline`: **DRAFT, not ready to merge, 34/34 unit tests passing**, with two explicitly-named merge blockers (below).

19 files, +2857/-2 lines:

| File | Purpose |
|---|---|
| `baseline/lib/ifnet_config.py` | Pure `/etc/network/interfaces` parser, stanza-rewriter, closure-hasher. No I/O of its own. |
| `baseline/lib/topology.py` | `derive_target()` — walks parsed topology from an observed failing device up to the nearest `inet static` stanza (bridge/bond/VLAN-aware), refusing on ambiguity. |
| `baseline/lib/repair.py` | The full transactional pipeline: standalone-host check, `ifupdown2` capability detection, connection guard, backup, independent rollback arming, atomic write, apply, target-bound verification, event logging. `reset_interface_to_dhcp()` is the entry point. |
| `baseline/lib/repair_rollback.py` | Standalone (stdlib-only) rollback executor — what the armed systemd timer calls; also contains `boot_time_recovery()`, implemented and unit-tested but not wired to any installed unit. |
| `baseline/bin/baseline-repair-rollback` | Thin installed CLI entry point for the above. |
| `baseline/bin/baseline` (diff) | Adds a "Propose Fix" button to the Connection tab, a `RepairProposalModal` (tty1-only authorization surface), and `harness.propose_repair()` wiring. |
| `boot/baseline-repair-env-probe.sh` | Read-only probe for real systemd boot-ordering facts, needed to eventually install the permanent boot-time recovery unit. Makes no config changes. |
| `docs/design/reset-interface-to-dhcp-plan.md` | The full v3 design doc — extremely thorough, already answers most of this comparison's own questions in writing. |
| `tests/unit/test_topology.py`, `test_repair.py`, `test_ifnet_config.py` | 34 tests total, `FakeRunner`-based, no real device/root access. |

## 2/3. Does the Phase-0-installed configuration get accepted, and does it select `vmbr0` correctly?

**Two different Phase 0 fixtures exist (the original reproduction and the one corrected rerun), and the answer differs between them — this is the single most important finding of this comparison.**

### Fixture A: the original, unmodified reproduction (IPv6-only, `fec0::/64`)

```
iface ens3 inet6 manual
auto vmbr0
iface vmbr0 inet6 static
        address fec0::5054:ff:feba:5e12/64
        gateway fe80::2
        bridge-ports ens3
        bridge-stp off
        bridge-fd 0
```

**`derive_target()` would NOT select `vmbr0` here.** `topology.py::_is_static_candidate()` and `ifnet_config.py::rewrite_stanza_to_dhcp()` both explicitly require `stanza.family == "inet"` (IPv4) — this design is scoped to IPv4 static-to-DHCP conversion only, by its own stated intent ("Scope: `inet` stanzas only"). Fixture A's `vmbr0` stanza is `inet6 static`, not `inet static`. Walking the topology from `ens3` or `vmbr0` finds no `inet`-family static candidate anywhere, so `derive_target()` returns `DerivationResult(None, [], "no inet static configuration found...")` — a clean, correct refusal (not a crash, not a wrong selection), but also **not a fix** for this specific broken state. This is a genuine, real gap, not a bug — the existing tool was never designed to touch IPv6 configuration.

### Fixture B: the one corrected rerun (`ipv6=off`, IPv4 fallback)

```
iface ens3 inet manual
auto vmbr0
iface vmbr0 inet static
        address 192.168.100.2/24
        gateway 192.168.100.1
        bridge-ports ens3
        bridge-stp off
        bridge-fd 0
```

**This is accepted and handled exactly as designed.** It is structurally near-identical to the existing `VMBR0_BRIDGE` test fixture in `test_topology.py` (same shape: a physical `inet manual` member, a bridge with `inet static` address/gateway/`bridge-ports`; the only difference is the extra harmless `bridge-stp off`/`bridge-fd 0` lines, which the generic `OPTION_RE`-based option parser accepts into `stanza.options` without issue). `derive_target("vmbr0", cfg)` finds exactly one `inet`-static candidate — `vmbr0` itself, `kind="bridge"`, `physical_devices=["ens3"]` — and `ens3`'s own `inet manual` stanza is correctly never treated as a candidate (its `method` is `"manual"`, not `"static"`), matching the design's explicit statement that a bridge's physical member reading `inet manual` "is correct, not a bug, and is never itself a repair target." `rewrite_stanza_to_dhcp(cfg, "vmbr0")` would replace only the `vmbr0` stanza with a bare `iface vmbr0 inet dhcp` line, leaving `ens3`'s stanza byte-identical.

**Also directly relevant**: this fixture's DNS/route brokenness (confirmed via direct `ping`/`curl` failure in Phase 0) is exactly the class of fault `network.py::check_lifeline()` is meant to catch (`gateway_reachable`/`address_assigned` failing), which is what `reset_interface_to_dhcp()`'s `already_healthy` precondition checks against before proceeding — so this fixture would also correctly pass that gate, not be refused as "not actually broken."

## 4. Which refusal conditions apply on this fresh, standalone image

Walking every refusal code in `repair.py` against the actual Phase 0 environment:

| Refusal | Applies here? | Why |
|---|---|---|
| `cluster_member` | **No** | No `/etc/pve/corosync.conf` or `/etc/corosync/corosync.conf` on a fresh standalone install; `pvecm status` would report no cluster. |
| `unsupported_environment` | **No** | Phase 0 directly confirmed `ifupdown2` (3.3.0-1+pmx12) is installed and is the active/enabled networking implementation. |
| `topology_ambiguous` | **No** | Exactly one bridge, one physical member — unambiguous in both fixtures. |
| `no_static_config` | **Yes, for Fixture A only** | The core finding above — no `inet`-family static stanza exists in the IPv6-only reproduction. |
| `already_healthy` | **No** | Both fixtures fail `check_lifeline()`'s `gateway_reachable`/`address_assigned` checks (confirmed directly via failed ping/curl in Phase 0). |
| `protected_connection_unattended` | **No, if `operator_present=True`** (see §5) | No SSH/`:8006` session exists in a just-installed, never-remotely-accessed fresh image; even if one did, tty1-authorized execution is explicitly allowed to proceed past this guard by design. |
| `backup_unverified` / `rollback_arm_failed` | **Untested, plausible No** | Requires `systemd-run` and normal filesystem write access — both expected to work on a booted, running Proxmox install; not independently re-verified in this read-only pass. |
| `concurrent_config_change` | **No** | Nothing else is modifying `/etc/network/interfaces` between proposal and execution in this scenario. |

**Net result: for Fixture B specifically, no refusal condition blocks the repair. For Fixture A, `no_static_config` blocks it — correctly, not as a bug, but as a real scope gap.**

## 5. Can it execute during the existing first-boot tty1 state machine, after local authorization?

**Not without integration work — these are currently two separate tty1 owners.** The existing repair action's authorization surface (`RepairProposalModal`) is wired into **Baseline's normal running-state Textual TUI** (`baseline/bin/baseline`, the Connection tab's "Propose Fix" button) — the same app that owns tty1 during Baseline's ordinary operation per `boot/baseline.service`. The Milestone 0 first-boot state machine (`experiments/m0-inv6/firstboot_statemachine.py`, not yet promoted to `baseline/lib/`) is a **different, purpose-built, minimal state machine** for the drive-setup GUI's specific propose→indefinite-`CONFIRM`→apply→verify→commit flow — it does not run Baseline's main Textual app loop at all.

The authorization *model* is compatible — both are "no remote path, only a physically-present tty1 operator, no timeout/default" — and `reset_interface_to_dhcp()`'s `operator_present: bool` parameter is exactly the hook a first-boot integration would need (it's already designed to be set "only by the TUI's own local confirmation flow, never settable remotely," which describes the first-boot state machine's CONFIRM-gate equally well as it describes the normal-run modal). But **no code currently connects them.** Integrating requires either: (a) having the first-boot state machine call `repair.reset_interface_to_dhcp()` directly as one of its own bounded actions once a `CONFIRM` is received (straightforward — the function signature and `Runner` abstraction are already decoupled from the TUI that authorizes it), or (b) treating "first boot" as an early instance of Baseline's normal running app rather than a separate state machine at all (a larger architectural question, out of scope for this comparison).

## 6. Dependencies preventing direct reuse

- **Privilege**: `RealRunner` writes directly to `/etc/network/interfaces`, calls `ifreload`, and runs `systemd-run` — this requires the calling process to already be running with root privilege. True for Baseline's normal deployment (`boot/baseline.service` runs as root) and true for how Investigation 6 ran the first-boot state machine prototype inside a QEMU guest (also root) — **not a blocker**, but a dependency worth stating explicitly since the drive-setup GUI's own separate helper model (pkexec-per-action, structurally-absent-physical-device through Milestone 2) is a *different* privilege pattern than "the whole process already runs as root."
- **`boot/provision.sh` drift**: the branch's diff to `provision.sh` **removes** `handoff.py` and `baseline-setup-wizard` deployment lines and the `gnupg` package install — these removals appear to predate work already merged to `main` since this branch's base commit (`07eda93`); merging or cherry-picking this branch's `provision.sh` changes as-is would silently regress those unrelated deployments. This needs a rebase/manual merge, not a blocker to the *logic* being reusable, but a real integration cost.
- **`harness.propose_repair()`**: adds a new harness call shape (structured JSON proposal) — needs to exist in whatever `harness.py` Milestone 1 code ultimately uses; not yet checked against `handoff.py`/other `main`-only additions for conflicts.
- **No dependency on anything drive-setup-specific**: `ifnet_config.py`, `topology.py`, `repair.py`'s core pipeline, and `repair_rollback.py` import only `network.py` (already in `baseline/lib/` on `main`) and stdlib — genuinely portable.

## 7. Actual blockers vs. previously-known limitations

**Previously known, already documented on the branch itself (not new findings from this comparison)**:
- The permanent boot-time recovery service (covering a reboot *during* the 120-second same-boot rollback window) is implemented and unit-tested as a function (`repair_rollback.py::boot_time_recovery()`) but **not installed as a systemd unit** — explicitly gated on real Proxmox/Debian boot-ordering verification the branch's own author couldn't perform (no reachable Proxmox/Debian host from that session). `boot/baseline-repair-env-probe.sh` exists specifically to collect that evidence next time this runs against a real target.
- The real `ifupdown2`/bridge/DHCP/systemd integration test (vs. real infrastructure, not `FakeRunner`) has not been run — explicitly named as PR #1's second merge blocker.

**Genuinely new, found by this comparison**:
- The IPv4-only scoping (`family == "inet"` required) means the tool **cannot touch Fixture A's actual reproduced broken state** (IPv6-only static config) at all — it would cleanly refuse (`no_static_config`), not silently do nothing dangerous, but this is a real functional gap against the literal Phase 0 finding, not merely an "already known limitation."
- The first-boot tty1 integration (§5) does not exist yet — this is new integration work, not a limitation carried over from the branch's own stated blockers.
- A minor, likely-inconsequential parsing gap: `read_interfaces_config()`'s handling of a plain `source /path/*` directive (as opposed to `source-directory /path`) does not glob-expand — it treats the literal string (including the `*`) as a file path, which raises `OSError`, silently caught and treated as an empty file. Phase 0's captured `/etc/network/interfaces` ends with exactly this form: `source /etc/network/interfaces.d/*`. This did not affect Fixture A/B's analysis above (no fragment files were confirmed to exist in that directory — not independently verified either way in Phase 0), but it is a real, generalizable parsing gap worth a dedicated test and fix before relying on this in production, independent of whether it happens to matter for this exact fixture.

## 8. Test comparison against the Phase 0 fixture — only the missing tests

Existing `test_topology.py` fixtures are structurally strong (`VMBR0_BRIDGE`, bond+bridge, VLAN, ambiguous, physical-only, unknown-device — 8 tests) and `test_ifnet_config.py`/`test_repair.py` cover the transactional pipeline thoroughly (34 tests total, per the draft PR). Comparing directly against what Phase 0 actually captured, the **only** gaps specific to this exact configuration are:

1. **No test for an `inet6`-family static stanza specifically** (as opposed to merely "no stanza at all," which `test_no_static_config_anywhere_refuses` already covers). A test using Fixture A's literal shape (`inet6 static` present, no `inet static` anywhere) would directly confirm `derive_target()` refuses via `no_static_config` rather than, say, mistaking `inet6 static` for a candidate through some untested code path. This is the single most valuable missing test given this comparison's findings.
2. **No test using the exact real-installer-generated fixture shape** (Fixture B, byte-for-byte from Phase 0's actual captured file, including `bridge-stp off`/`bridge-fd 0` and the trailing `source /etc/network/interfaces.d/*` line) — existing fixtures are hand-constructed approximations; a regression test built from genuine captured evidence is stronger and would have caught the `source`-glob gap below directly.
3. **No test for the `source /path/*` (glob-form `source`, not `source-directory`) directive** — the gap identified in §7. A test asserting either correct glob expansion (if fixed) or an explicit, loud failure mode (if left as a known limitation) is needed before this is relied on in production, since Proxmox's automated installer is now confirmed (Phase 0) to generate exactly this directive form.

No other gaps were found specific to this configuration — the ambiguous-topology, connection-guard, rollback, and backup-retention test coverage is already thorough and not implicated by anything Phase 0 observed.

## Result

The existing implementation is real, substantially complete, well-tested (34/34), and its design already anticipates almost everything the Phase 0 investigation needed — including, notably, the exact standard Proxmox `vmbr0`-bridge topology this investigation's own fixture uses. **It would handle Phase 0's Fixture B (the IPv4-fallback configuration) correctly, out of the box, once its dependencies are integrated. It would correctly and safely refuse (not mishandle) Fixture A (the actual, unmodified, originally-reproduced IPv6-only configuration) — because it was never scoped to touch IPv6, not because of a defect.**

This is a materially better foundation than building new repair logic from scratch, and duplicating it would have been a real waste of already-reviewed, already-tested work.

## Whether another installation experiment is still necessary

**Not to validate the existing repair logic against Fixture B** — this comparison, done entirely by reading code and design documentation, is sufficient to establish that it would work as designed; a redundant QEMU rerun would prove nothing this analysis hasn't already shown with equal confidence via direct code inspection.

**A real installation/boot experiment does remain necessary later, but for a different purpose**: to validate the **redefined Gate A** (see the plan revision) — running the existing repair action for real, inside a fresh disposable image carrying the actual reproduced broken state, end-to-end through a first-boot tty1 authorization gate, is still an empirical claim that needs empirical proof, not something a read-only code comparison can establish on its own. That experiment is exactly what the revised Gate A now specifies, and it has not been run yet — this comparison is the analysis that must precede it, not a substitute for it.
