# Milestone 1 implementation plan — sparse-image installer, image-only

Status: **v2 provisionally approved — Phase 0 only. The rest of Milestone 1 (Gates B–F, all four module boundaries) remains unapproved pending Phase 0's outcome.** No implementation started, no privileged operation performed while preparing this plan.
Parent: [drive-setup-gui-v2-prd.md](drive-setup-gui-v2-prd.md) §9 (Milestone 1), built on [milestone-0-plan.md](milestone-0-plan.md)'s closed-out evidence (commit `519f367`, accepted).
Author: Claude Code, planning pass only — this document is the deliverable for this turn.

## Revision note (why this version exists)

The first version of this plan (commit `771b4c4`) was reviewed and **not approved**. The core objection: it treated destination networking as a "zero-cost discovered-fact check" folded into a Phase 7 end-to-end proof — but networking is the only genuinely unresolved uncertainty in the core image pipeline (Milestone 0 only ever observed IPv6-only behavior inside QEMU/SLIRP and explicitly scoped that finding to the test environment, never resolved it). Discovering a networking failure at the end of a nine-module build would invalidate work built on top of an untested assumption. This version moves that investigation to **Phase 0, before any production module is written**, and cuts everything else down to what one usable vertical slice actually needs — no storage ancestry, no MD RAID/LUKS, no generalized key management, no single expensive end-of-pipeline test standing in for incremental verification. Four cohesive module boundaries instead of nine, and six named gates instead of one big proof at the end.

## 0. Canonical repository — unchanged from v1

**`cliffthelin/BaseLineProx` (the `origin` remote) remains the sole canonical repository**, per `docs/SESSION_HANDOFF.md`'s explicit documentation (see v1's §0 for the full evidence, unchanged by this revision). This plan pushes to `origin` only. No push to `cliff` (`cliffthelin/baseline`) happens unless the user explicitly says otherwise.

## 1. Hard constraints carried forward from Milestone 0 (unchanged)

- No physical block-device writes of any kind.
- No physical-device argument, dormant flag, helper action, or polkit capability accepted or created anywhere in Milestone 1 code — enforced structurally, not by convention.
- All experimentation stays under `experiments/`; promoted code moves into `baseline/lib/`, `packaging/baseline-drive-setup/`, and `tests/unit/drive_setup_tests/` only with real test coverage.
- No host system modification: no `apt install` to the development host, no APT source changes, no systemd unit installed on the development host.
- Setup-intent signing uses a **single synthetic Ed25519 test key per run, generated fresh each time, discarded after** — no key management subsystem, no rotation, no revocation list, no persistence of any key across runs. Production trust-anchor provisioning remains explicitly out of scope (§7).

## 2. Scope — one demonstrable vertical slice, not a platform

Per review, Milestone 1 is now exactly this chain, and nothing beyond it:

1. Verified source artifacts (ISO + assistant package, via the existing GPG/hash chain already proven in Investigation 1/2 — reused, not rebuilt).
2. Safe ephemeral credential generation (argv-free, per Investigation 2/3).
3. Pinned, single-use answer delivery (per Investigation 2/3's accepted design).
4. Guarded ISO preparation and cleanup (never trusting exit codes, per Investigation 2's confirmed finding).
5. Sparse-image-only installation.
6. Explicit installer-success verification (the literal `Finished: 'ok'` signal, per Investigation 3's own corrected mistake — never inferred).
7. Disk-first reboot and fresh-OVMF verification (`once=d` mandatory, per Investigation 4's confirmed defect).
8. **Resolved destination networking** — new in this revision, and the actual gating concern; see Phase 0.
9. tty1 discovery and indefinite local authorization (the corrected state machine from Investigation 6).
10. Authorized installation of the five diagnostic packages, confirmed to persist after reboot.
11. A machine-readable manifest and a concise evidence report.

Everything not in this list is removed or deferred — see §6.

## 3. Phase 0: destination-network resolution (runs first, before any production module is written)

**Why this comes first**: every later phase either runs inside a QEMU guest reachable by the answer server (steps 2–7) or depends on the *installed* system being reachable for anything beyond a local console session (step 9's tty1 flow doesn't strictly need network, but the diagnostic-package install and any real Milestone 2 work eventually will). Milestone 0 observed IPv6-only `fec0::/64` addressing throughout every QEMU session but never investigated *why*, and explicitly scoped the finding to the test environment rather than resolving it. That gap is closed here, first, cheaply, using only the disposable sparse-image/QEMU environment and existing non-interactive permissions — no new privilege, no host change.

**Procedure**:

1. **Reproduce once.** Regenerate one fresh sparse-image install using the exact proven pipeline from Investigation 3 (`run_final.sh`, unmodified) and confirm the `fec0::/64`-only result reproduces, on this specific run, before investigating further — not assumed still true from a prior investigation's evidence.
2. **Capture, don't infer, every layer of evidence**:
   - The answer file's actual `[network]` section as generated (`source = "from-dhcp"` per Investigation 1's fixture — confirm this is still what Milestone 1's credential/answer modules would actually produce).
   - The installer-generated network configuration on the installed disk (`/etc/network/interfaces` or equivalent, inspected via a disposable QEMU guest boot with the target disk attached — never by mounting the sparse file directly on the host, consistent with every Milestone 0 investigation's "no loop device against anything but a controlled fixture" discipline; here there is no fixture, so no loop device at all — boot and inspect from inside the guest).
   - The kernel command line the installed system actually boots with (`/proc/cmdline` inside the guest).
   - DHCP lease state, interface state (`ip addr`, `ip link`), routes (`ip route`, `ip -6 route`), and DNS configuration (`/etc/resolv.conf` or `resolvectl status`) — captured from inside the running guest, not assumed from configuration files alone.
   - Which networking implementation is actually active and enabled — `systemctl status systemd-networkd`, `systemctl status NetworkManager`, presence/absence of `ifupdown`/`ifupdown2`, checked directly rather than presumed. This directly answers the review's correction: the test identifies what's actually running, it does not presume NetworkManager (or any other specific implementation) is the relevant one.
3. **Determine the source, by elimination against direct evidence, not by guessing**: does the IPv6-only behavior originate in (a) the answer file's own `from-dhcp` request never asking for IPv4 explicitly, (b) `proxmox-auto-install-assistant`'s installer environment itself, (c) QEMU SLIRP's DHCP server behavior specifically (SLIRP is known to serve both v4 and v6, so this needs its own direct check — e.g. does a `tcpdump`/`dhclient`-visible DHCPv4 offer even reach the guest), (d) whichever networking implementation §3.2's last check identified as active, or (e) some first-boot transformation applied after install. Each of these produces a distinguishable evidence signature; the goal is to land on one, evidenced answer, not a plausible-sounding guess.
4. **Test only the smallest plausible correction** implied by step 3's finding — e.g. if SLIRP itself is the limiting factor, confirm whether a plain `-netdev user` without additional flags actually offers IPv4 in a trivial standalone QEMU boot (unrelated to the installer) as a control case; if it's the installed system's own active networking implementation, test the smallest configuration change that implementation would need (e.g. one interface-config line), not a rewrite of the networking stack. No speculative multi-option matrix — one hypothesis, one smallest test, evaluated on direct evidence.
5. **Prove usable networking after a fresh boot**, with every one of these five properties independently confirmed, not inferred from any subset:
   - An assigned address (v4 or intentionally-chosen v6 — see below).
   - A correct default route.
   - DNS resolution (an actual resolved lookup, not just `resolv.conf` contents).
   - Outbound HTTPS reachability (an actual successful TLS connection to something, not just a route existing).
   - **Persistence across reboot** — the same five checks repeated after a clean reboot of the same installed disk, not just the first boot.
6. **If networking cannot be corrected safely within this phase's scope, define a fail-closed detection and stop condition, and do not build the remaining pipeline around broken networking.** Concretely: if step 4's smallest correction doesn't produce a passing step 5, Phase 0 ends with an explicit, evidence-backed `networking_unresolved` result, a precise description of what was tried and what remains broken, and **Gate A does not pass**. **`networking_unresolved` is a blocking outcome, not an alternative completion criterion** — it is a valid and legitimate investigation result (matching Investigation 8's precedent that "no sufficiently strong mechanism found" is a valid, honest conclusion, not a failure to hide), but it does not satisfy Gate A under any framing. If Phase 0 ends this way, **no later-phase module gets written** and the decision to either (a) accept IPv6-only operation as intentional (if that's genuinely sufficient for Baseline's actual needs — a real question for the user, not this investigation to decide unilaterally) or (b) escalate with real diagnostic capability (which may require authorization this phase is instructed to avoid) is handed back explicitly rather than absorbed silently or treated as "close enough" to proceed on.

**Authorization discipline for this phase specifically**: every step above uses only a disposable sparse image, QEMU, and already-confirmed non-interactive permissions. If any specific diagnostic step would require sudo, pkexec, polkit, a keyring, or any interactive prompt, that specific step is skipped and recorded as unavailable evidence — Phase 0 continues with whatever it can determine from the rest, and reports the gap plainly rather than working around it.

## 4. Module boundaries — four cohesive boundaries, not nine

| Boundary | File(s) | Responsibility | Promoted from |
|---|---|---|---|
| **1. Artifact acquisition and verification** | `baseline/lib/drive_setup_acquire.py` | Reproduces Investigation 1/2's exact GPG-signed-`Release` → hash-pinned-`Packages` → hash-pinned-`.deb`/ISO chain against cached fixture metadata; extracts the assistant binary without touching the host package database. | Investigation 1/2's verification commands, not previously written as reusable code — this is the one genuinely new module in this boundary. |
| **2. Answer delivery and ISO preparation** | `baseline/lib/drive_setup_answer.py` | One cohesive module covering: argv-free one-time credential generation and hashing; the ephemeral single-use, TTL-bounded, hardware-fact-checked HTTPS answer server; the postcondition-based wrapper around `prepare-iso` that never trusts exit codes and owns staging-directory cleanup on every path; and workspace/path validation ensuring every target resolves to a controlled regular file. These four concerns are tightly coupled in practice (the credential feeds the answer content, the wrapper/workspace guard the call that consumes it) and are combined into one boundary rather than four separate files. | `experiments/m0-inv3/credential.py`, `answer_server.py`, `wrapper.py`, `workspace.py` — consolidated. |
| **3. Image installation and boot verification** | `baseline/lib/drive_setup_install.py` | QEMU invocation construction (sparse-file-only, `guestfwd`-isolated networking, mandatory `-boot order=c,once=d`), screendump-based explicit-success detection, legacy-BIOS and fresh-OVMF-NVRAM boot verification, and the Phase-0-resolved networking configuration applied and re-checked against the same five properties. | New orchestration, reusing QEMU-invocation and screendump patterns from `experiments/m0-inv3/run_e2e_install.py` and Investigation 4's commands. |
| **4. First-boot setup and evidence** | `baseline/lib/firstboot_statemachine.py` (promoted, unchanged from its corrected version) + `baseline/lib/setup_intent.py` (promoted, minimal — see §7) | The proven propose → indefinite-`CONFIRM` → apply → verify → commit state machine and tty1 ownership; minimal setup-intent canonical-format signing/verification with a synthetic per-run key; the diagnostic-package install step gated behind confirmation; the manifest (§8) and evidence-report generation. | `experiments/m0-inv6/firstboot_statemachine.py` (corrected version only) + `experiments/m0-inv9/setup_intent.py` (near-verbatim, already minimal). |

Two files under one boundary (#4) rather than one, because the state machine and the setup-intent verifier are both "first-boot trust and confirmation" concerns that were already separately proven and don't benefit from forced merging — the boundary is conceptual (owned by one area of responsibility), not a literal one-file-per-boundary rule.

**Explicitly not promoted or built in Milestone 1**: `storage_ancestry.py`, any MD RAID/LUKS fixture code, any exclusive-access/`O_EXCL`/automount-handling code, any production key-provisioning/rotation code, `pinned_client.py`/`preflight.py` (kept as test-only infrastructure, not shipped), `vnc_type.py` (test-harness only). See §6 for the reasoning behind each.

## 5. Gate sequence

Each gate is a stop/go checkpoint with its own evidence. **A failed gate stops progress into later phases and produces a written evidence note — it does not trigger a compensating framework, a fallback design, or scope expansion to "solve" the failure at the same time it's discovered.** That decision goes back to the user, the same way Investigation 8's genuinely-unresolved outcome was reported plainly rather than forced into a false "solved."

| Gate | Condition | Tied to |
|---|---|---|
| **A** | Networking proven — all five properties in Phase 0 step 5 confirmed, including post-reboot persistence — **before any of the four modules in §4 are implemented.** | Phase 0 |
| **B** | Prepared ISO verified without booting — `inspect-iso` output and a raw byte scan confirm fetch mode, URL, cert fingerprint, and the absence of forbidden strings (plaintext password, hash, full answer content in HTTP mode), matching Investigation 2/3's postcondition set. | Boundary 1 + 2 |
| **C** | Installation reaches explicit success — the literal `Finished: 'ok'`/`Installation done` sequence captured via screendump, never inferred from QEMU exit code or partition structure alone. | Boundary 3 (install half) |
| **D** | Fresh boot has usable networking — Phase 0's five-property check re-run against the actual installed image (not the Phase 0 investigation image), under fresh OVMF NVRAM, confirming Phase 0's finding generalizes to the real Milestone 1 pipeline's own output. | Boundary 3 (boot half) |
| **E** | First boot waits for real local approval — the 40-second-idle-no-change plus post-`CONFIRM` apply/verify/commit evidence, reproduced with the same discipline Investigation 6 used after its own correction. | Boundary 4 (state machine) |
| **F** | Packages persist after reboot — the five diagnostic tools installed only after Gate E's confirmation, `iperf3` confirmed disabled/inactive immediately after install **and again after a full reboot**, matching Investigation 5's already-proven check. | Boundary 4 (package step) |

Gates run in order; B–F do not start implementation until A passes, per the review's core instruction. Within B–F, each gate's own module can be developed and unit-tested incrementally (TDD, per this project's standing rule) — the gates are integration checkpoints, not a ban on incremental work within a boundary.

## 6. Removed or deferred scope, and why

| Item | Disposition | Reasoning |
|---|---|---|
| MD RAID / LUKS-on-LVM validation | **Deferred, likely to Milestone 3 timing, not Milestone 1** | Not needed for an image-only installer that never resolves live-host storage ancestry against anything but the disposable image it itself created — this concern only exists once physical-device selection (excluding a currently-mounted host device's ancestry) is in scope, which is Milestone 3, not Milestone 1. |
| Storage-ancestry productionization (`storage_ancestry.py`) | **Deferred entirely, not part of Milestone 1** | Same reasoning — physical-device support is structurally absent through Milestone 1, so there is no live host device whose ancestry ever needs excluding. Investigation 7's module and its real-tool-validation gap both move to whichever milestone actually needs live-ancestry exclusion (Milestone 3). |
| Physical-device exclusivity (`O_EXCL`, `flock`, monitoring) | **Deferred to Milestone 3, unchanged from Investigation 8's own conclusion** | Investigation 8 already deferred this; nothing in Milestone 1's image-only scope requires it. |
| Automount/disconnect handling | **Deferred to Milestone 3** | Same reasoning — only relevant once a real removable/physical device exists in scope. |
| Production key provisioning or rotation | **Deferred, explicitly out of scope for Milestone 1** | See §7 — Milestone 1 uses one synthetic per-run key, never a managed key lifecycle. |
| Any module required only for physical-drive support | **Deferred to Milestone 3** | Consistent with §5.4's structural-absence requirement — nothing in this list gets built even partially. |
| A single expensive end-to-end proof standing in for incremental verification (v1's Phase 7) | **Replaced by the six-gate sequence in §5** | The review's point: one big proof at the end creates a second "learn too late" failure mode structurally identical to the networking one this revision exists to fix. Gates B–F each produce their own evidence as work proceeds, not one terminal checkpoint. |

## 7. Setup-intent: minimal, not a subsystem

Per review, Milestone 1's setup-intent handling stays deliberately small:

- **Canonical format**: unchanged from Investigation 9's promoted `setup_intent.py` — sorted-key, compact-separator JSON with strict duplicate-key rejection at parse time.
- **Synthetic signing key**: exactly one Ed25519 keypair generated fresh per build/test run, held in memory or a gitignored temp path, discarded at the end of the run. No key ever persists across runs, no key is ever committed, no key ever stands in for a production trust anchor.
- **Strict verification**: the same fail-closed `verify_intent()` chain proven with 16/16 synthetic tests in Investigation 9 — schema allowlist, expiry, target-match, action-set membership, existence-based replay ledger — reused essentially unchanged.
- **Local authorization**: verification success is a precondition for *proposing* the confirmed action on tty1 (Gate E), never itself an execution trigger — unchanged from Investigation 9's own stated principle.
- **Honest integrity-only labeling**: Milestone 1's bundle verification key is stored beside the bundle (no independent provisioning channel exists yet), so it is documented, in the manifest and evidence report, as an **integrity/corruption check**, not authentication — exactly the distinction Investigation 9 established. No language in Milestone 1's code, tests, or evidence report claims more than this.
- **What is explicitly not built**: key rotation, multiple trusted keys, a revocation list, remote/out-of-band key distribution, or any persistence layer for keys — a "key-management subsystem" in miniature is exactly what this section exists to prevent, per the review's direct instruction.

## 8. Manifest and evidence report (unchanged in spirit from v1, reduced in content)

Machine-readable JSON manifest per completed run, network fields promoted from Phase 0's afterthought status to first-class:

```json
{
  "schema": "baseline.m1-build-manifest.v1",
  "run_id": "<uuid>",
  "started_at": "<ISO8601>",
  "completed_at": "<ISO8601>",
  "source_iso": {"sha256": "...", "verified_via": "gpg-signed-release-chain"},
  "gate_results": {
    "A_networking_proven": "pass | fail | networking_unresolved",
    "B_iso_verified": "pass | fail",
    "C_install_success": "pass | fail | indeterminate",
    "D_fresh_boot_networking": "pass | fail",
    "E_firstboot_confirmation_gate": "pass | fail",
    "F_packages_persist_after_reboot": "pass | fail"
  },
  "networking": {"addressing": "ipv4 | ipv6 | dual", "source_of_behavior": "answer-file | installer | slirp | <networking-impl> | first-boot", "correction_applied": "none | <description>"},
  "setup_intent": {"key_type": "synthetic-per-run", "label": "integrity-only"},
  "artifact_retention": {"credentials_purged": true, "temp_isos_deleted": true, "test_key_discarded": true}
}
```

The evidence report is the same Markdown-narrative counterpart as v1, but organized by gate (A–F) rather than by phase, each gate's section carrying its own pass/fail and linked evidence — this directly supports "a failed gate stops later phases and produces evidence" rather than requiring a full run to see any result.

## 9. Artifact retention rules (unchanged from v1)

| Category | Retention |
|---|---|
| Ephemeral one-time install credentials (plaintext) | Never written to disk — process memory only. |
| Password hash | Exists only inside the answer file / prepared ISO / installed disk's own shadow file — not separately retained. |
| Answer files | Deleted immediately after the one QEMU session that consumes them. |
| Prepared ISOs | Deleted after the one install that used them — never reused. |
| Synthetic setup-intent key | Discarded at the end of each run — never checked in, never reused. |
| Disposable sparse install images | Deleted after their evidence is captured, unless explicitly reused within the same gate sequence (e.g. the same image serving Gates C and D). |
| Build manifest + evidence report | Retained — no secret fields by construction. |
| Phase 0's own investigation artifacts | Deleted after Phase 0's findings are recorded, same discipline as every Milestone 0 investigation. |

## 10. Dependency and privilege boundaries (unchanged from v1, trimmed)

- No new host packages — the extracted assistant binary plus already-present `xorriso`, `qemu-system-x86_64`, `ovmf` are sufficient.
- No new Python dependencies beyond `cryptography` (setup-intent) and stdlib.
- No privileged operation on the development host — every QEMU session runs unprivileged against workspace-local files; `pkexec` is never invoked, since the physical-device capability remains structurally absent.
- Setup-intent keys are synthetic, per-run, and discarded (§7) — no keyring, credential manager, or system secret store is touched.

## 11. Criteria for declaring Milestone 1 complete (revised, reduced)

1. Gate A passes, with Phase 0's evidence recorded, **before** any of the four §4 modules exist as production code — or, if networking cannot be safely corrected, an explicit `networking_unresolved` result is recorded and handed back to the user rather than built around.
2. Gates B through F each pass with their own recorded evidence, in order.
3. All four module boundaries in §4 exist under `baseline/lib/` with tests written first (TDD) and passing. **Coverage is a floor, not proof**: ≥80% line coverage is a minimum sanity check, but a module is considered actually verified by its behavioral tests and its gate's own evidence (§5), not by the coverage percentage alone — a well-covered module that hasn't passed its gate's real evidence check is not "done," and a module with thin coverage but strong, specific behavioral tests targeting its fail-closed conditions (§4 of v1's invariants, carried forward conceptually) is the higher bar to meet, not the percentage.
4. The manifest (§8) and evidence report have been generated from at least one real run and reviewed.
5. §9's retention rules are verified on at least one full run — no leftover credential-bearing artifact.
6. Setup-intent's manifest/evidence-report language states "integrity-only" plainly, per §7 — no overclaim.
7. Nothing has been pushed to `cliffthelin/baseline`.
8. A short closeout note (matching this session's decision-record honesty standard) states what passed, what didn't, and what's explicitly carried into Milestone 2 or Milestone 3 — including, if applicable, an unresolved networking result, which would itself be a valid and important Milestone 1 finding rather than a failure to hide.

---

This revised plan is the deliverable for this turn. No code has been written, no privileged interface invoked, no package installed, and no authorization request triggered while preparing it. Awaiting review before any implementation phase — including Phase 0 — begins.
