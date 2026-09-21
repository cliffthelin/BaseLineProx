# Milestone 1 implementation plan — sparse-image installer, image-only

Status: **proposed, awaiting review — no implementation started, no privileged operation performed while preparing this plan.**
Parent: [drive-setup-gui-v2-prd.md](drive-setup-gui-v2-prd.md) §9 (Milestone 1), built on [milestone-0-plan.md](milestone-0-plan.md)'s closed-out evidence (commit `519f367`, accepted).
Author: Claude Code, planning pass only — this document is the deliverable for this turn.

## 0. Canonical repository determination

**Recommendation: `cliffthelin/BaseLineProx` (the `origin` remote) is the canonical repository. Do not continue pushing to `cliffthelin/baseline` (the `cliff` remote) without the user's explicit decision on its status.**

Evidence, from existing repository documentation only, no assumption:

- [`docs/SESSION_HANDOFF.md`](SESSION_HANDOFF.md) (written earlier this project, not by this planning pass) states explicitly, under "What exists and where": **"GitHub: <https://github.com/cliffthelin/BaseLineProx> (public), `main` branch... confirmed to contain everything described below."** This is stated as the project's GitHub location without qualification.
- The same document separately states: **"A second, pre-existing private repo, `cliffthelin/baseline`, unexpectedly received a push from this session too (a `git remote` mix-up — see the git-workflow note below). I don't know its history. Worth checking directly whether it should be archived/deleted or is intentional and predates this session."** This is a direct, documented statement that the `baseline` repo's role is **unresolved and was flagged as a probable accident**, not confirmed as an intended second canonical location.
- The root [`README.md`](../../README.md) links out to a PRD artifact and describes project layout with no reference to either GitHub remote by name — no additional signal either way from it.
- This session (before this planning pass) pushed every Milestone 0 commit to **both** remotes, following a pattern already established earlier in the conversation, not because a canonical-repo decision was made — this plan is the first point where that pattern is actually checked against the project's own documentation, per this turn's explicit instruction.

**This is not ambiguous evidence — it's a documented repo with an explicit "(public)" / "source of truth" designation, versus a second repo explicitly flagged in the project's own notes as "I don't know its history" / "worth checking whether it should be archived."** Recommendation: treat `BaseLineProx` as canonical for all Milestone 1+ work — branches, PRs, issues, releases — and stop pushing to `cliffthelin/baseline` until the user confirms what that repo is for. This plan does not modify either repository's settings, visibility, branch protection, or push configuration — that decision is the user's; this section only stops an unexamined dual-push pattern from continuing by default.

## 1. Hard constraints carried forward from Milestone 0 (still apply)

- No physical block-device writes of any kind.
- No physical-device argument, dormant flag, helper action, or polkit capability accepted or created anywhere in Milestone 1 code — enforced structurally (§5.4 of the PRD), not by convention. This is the single non-negotiable invariant of this entire milestone; see §4 below for how it's tested.
- All experimentation and intermediate artifacts stay under `experiments/`; promoted code moves into `baseline/lib/`, `packaging/baseline-drive-setup/`, and `tests/unit/drive_setup_tests/` only once it has real unit-test coverage per this plan.
- No host system modification: no `apt install` to the development host, no APT source changes, no systemd unit installed on the *development* host (first-boot units are staged *into disk images*, never installed on the machine doing the building).
- Setup-intent signing in Milestone 1 uses **test/synthetic Ed25519 keys only**, generated and held in-memory or in a gitignored workspace for the duration of a build/test run. **Production trust-anchor provisioning (where a real signing key is generated, stored, and rotated for real releases; where a real verification key is baked into a real first-boot image) is explicitly not delivered in Milestone 1** — this is called out again in §7 and §8 below because it's the item most likely to get silently assumed "done" by the time implementation is underway.

## 2. Scope — smallest end-to-end image-only installer path

Per instruction, Milestone 1 is scoped as one continuous, provable pipeline: validate → generate credential → serve answer → prepare ISO → install to sparse image → enforce one-time boot media → verify boot (both firmware paths) and clean shutdown → stage first-boot unit with a synthetic-key-signed setup-intent bundle → prove the tty1 discovery-then-indefinite-confirmation gate → prove diagnostic-package install happens only after that confirmation → produce a build manifest and evidence report → clean up every retained-artifact category per policy.

This intentionally pulls one proof-integration exercise forward from what the PRD's §9 originally scoped as Milestone 2 (a real QEMU first-boot pass reaching package installation) so that Milestone 1 is a genuinely *end-to-end* proof, not merely "image gets created." **This does not silently expand Milestone 1's production scope**: the PRD's Milestone 2 remains responsible for the *transactional* mechanisms (firewall apply/rollback, SSH/tether application, handoff restore) — Milestone 1's first-boot proof only exercises the state machine's discovery → propose → indefinite-confirm → apply(diagnostics) → verify → commit shape already built and proven in Investigation 6, with the five diagnostic packages standing in as the one real "apply" action, not the full set of Milestone 2 consequential actions. This distinction is restated in §9 (non-goals) so it isn't lost between this plan and the PRD.

## 3. Deliverables and module boundaries

All new library modules follow the existing flat-under-`baseline/lib/` convention already used by `hardware.py`, `network.py`, `harness.py`, `handoff.py`, `providers.py`, `tether.py`, `netpref.py` — no new package nesting introduced without a reason the existing layout doesn't already provide.

| Module | Promoted from | Responsibility |
|---|---|---|
| `baseline/lib/drive_setup_credential.py` | `experiments/m0-inv3/credential.py` | Argv-free one-time credential generation (`secrets.token_urlsafe`) and SHA-512-crypt hashing via `openssl passwd -6 -salt <salt> -stdin`, never via a CLI positional argument. |
| `baseline/lib/drive_setup_answer_server.py` | `experiments/m0-inv3/answer_server.py` | Ephemeral, single-use, TTL-bounded HTTPS answer service with `dmi.system.name`/MAC hardware-fact matching against the operator-confirmed target identity. Fixes the one known gap from Investigation 3: `logging.basicConfig` must actually be configured so request timestamps are captured, not silently dropped. |
| `baseline/lib/drive_setup_wrapper.py` | `experiments/m0-inv3/wrapper.py` | Postcondition-based wrapper around every `proxmox-auto-install-assistant` subcommand invocation — never trusts `$?`; owns staging-directory cleanup on every exit path. |
| `baseline/lib/drive_setup_workspace.py` | `experiments/m0-inv3/workspace.py` | Workspace creation and path validation — asserts every target path is a regular file resolving inside a helper-controlled workspace directory, never a caller-supplied or block-device-shaped path. |
| `baseline/lib/drive_setup_iso.py` | New (orchestration layer) | Ties acquisition verification (GPG/hash chain, reusing the exact commands proven in Investigation 1/2) + credential generation + answer-server startup + `prepare-iso` invocation (via the wrapper) into one `prepare_install_iso(...)` entry point. This is new code, not a promotion — Milestone 0 never built an orchestrator, only the individual proven pieces. |
| `baseline/lib/drive_setup_boot.py` | New, reusing patterns from `experiments/m0-inv3/run_e2e_install.py` and `experiments/m0-inv4` boot commands | QEMU invocation construction (sparse-file-only `-drive`, `guestfwd`-isolated networking, mandatory `-boot order=c,once=d`), screendump-based completion-signal detection (the literal `Finished: 'ok'` / `Installation done` sequence — never inferred from exit code or partition-table state alone, per Investigation 3's own corrected mistake), and `system_powerdown`-based clean-shutdown verification. |
| `baseline/lib/storage_ancestry.py` | `experiments/m0-inv7/storage_ancestry.py` (near-verbatim) | Read-only sysfs/LVM/MD/ZFS ancestry resolution — promoted essentially unchanged; Investigation 7's design was already read-only and dependency-free. |
| `baseline/lib/setup_intent.py` | `experiments/m0-inv9/setup_intent.py` (near-verbatim) | Canonical serialization, strict duplicate-key rejection, Ed25519 sign/verify, fail-closed policy chain, durable existence-based consumed-intent ledger. Promoted essentially unchanged — Investigation 9's module was already dependency-minimal (`cryptography` + stdlib) and structured for this. Signing keys used by Milestone 1's own build/test process are synthetic/test keys only (§1). |
| `baseline/lib/firstboot_statemachine.py` | `experiments/m0-inv6/firstboot_statemachine.py` (post-correction version) | The corrected propose → **indefinite literal-`CONFIRM`** → apply → verify → commit state machine, durable journal (fsync-file + fsync-dir + atomic rename), tty1 ownership. Promoted from the corrected version only — the original auto-confirm draft is not promoted under any circumstance. |
| `packaging/baseline-drive-setup/usr/lib/baseline-drive-setup/baseline-firstboot.service` | `experiments/m0-inv6/baseline-firstboot.service` | Systemd unit staged *into built images*, mirroring `boot/baseline.service`'s tty1-ownership pattern. Never installed on the development host. |
| `packaging/baseline-drive-setup/usr/lib/baseline-drive-setup/baseline-drive-prep-helper` | Existing v1 helper, extended | Gains `automated-install` subcommand per PRD §5.5. Extension only — the existing structural-absence-of-physical-device-argument property (already true of v1, since it only ever expressed image-file targets) must be preserved and is the subject of a new static surface test (§4). |
| `tests/unit/drive_setup_tests/` | New, per PRD §8.1 naming | One test module per library module above, TDD-first per this project's standing testing rule (write test → red → minimal implementation → green → refactor → verify ≥80% coverage), AAA structure. |

**Not promoted, deliberately**: `experiments/m0-inv3/pinned_client.py`, `preflight.py` (test/attack-simulation infrastructure used to *validate* the answer server's own pinning behavior — stays as test-only tooling under `tests/unit/drive_setup_tests/` or `tests/integration/`, never ships in the production package), `experiments/m0-inv6/vnc_type.py` (QEMU-monitor test-harness helper — becomes shared test infrastructure under `tests/integration/`, not a `baseline/lib/` module, since production code never drives QEMU by screen-scraping keystrokes).

## 4. Invariants and fail-closed conditions

These are the properties Milestone 1 must hold structurally, each with the test that proves it:

1. **No physical-device code path exists.** `tests/unit/drive_setup_tests/test_backend_surface.py` statically enumerates every accepted subcommand/argument shape of both the Python library and the bash helper and asserts none of them can resolve to a block-device path — a static assertion over the schema, not a runtime behavioral probe. This test must exist and pass **before** any other Milestone 1 module is considered mergeable, since every other deliverable depends on this boundary holding.
2. **Every destructive-looking operation targets only a workspace-controlled regular file.** `drive_setup_workspace.py`'s path-resolution check runs before any path is referenced in a QEMU argv or wrapper call; tested with a symlink-to-block-device fixture and a `/dev/*`-shaped string fixture, both rejected.
3. **No tool exit code is trusted.** Every wrapper call around `validate-answer`/`prepare-iso` parses stdout for the literal `Error:` prefix and independently verifies the resulting artifact's existence/type/size, per Investigation 2/3's direct finding that both subcommands return 0 on every tested failure mode. Tested with an induced failure (unwritable output path) exactly reproducing Investigation 2's finding.
4. **No secret crosses argv, environment, logs, or debug output.** `drive_setup_credential.py`'s hash generation uses the proven stdin-pipe `subprocess.run([...], input=..., shell=False)` pattern exclusively; `validate-answer -d` (debug mode) is never invoked by any Milestone 1 code path, full stop — enforced by a grep-based static check over the module source in CI, not just a runtime assertion, since the risk is a *future* accidental addition of a debug flag.
5. **Every wrapper-managed temporary artifact is accounted for on every exit path.** Success, induced-failure, and interrupted-process (SIGKILL mid-run) cases are all tested; a leftover credential-bearing temp file (Investigation 2's confirmed real defect) must not survive any of the three.
6. **Answer-server replay/TTL/hardware-fact binding holds against the real client, not only the synthetic test matrix.** At least one real end-to-end QEMU install (reusing Investigation 3's proven pipeline) must exercise a real post-consumption replay attempt and observe the real `403 already consumed` response, not only a synthetic client hitting the server's HTTP surface.
7. **Installer media is one-time boot media.** Every QEMU invocation constructed by `drive_setup_boot.py` uses `-boot order=c,once=d` — tested by a fixture asserting the constructed argv always contains this exact flag when an installer ISO is attached, and a real-boot integration test reproducing Investigation 4's finding (reboot after install must not re-enter the installer).
8. **Installer completion is only ever established from the installer's own explicit self-reported signal.** `drive_setup_boot.py`'s completion detector must match the literal `Finished: 'ok'` / `Installation done` sequence via periodic screendump — QEMU exit code, partition-table structure, and disk usage are permitted as *corroborating* signals in the build manifest but never as the sole basis for an `install_success_confirmed` classification. An install that doesn't reach this signal within a bounded timeout is reported `install_outcome_indeterminate`, never inferred as success or failure.
9. **Setup-intent verification is fail-closed with no default-permit branch.** `setup_intent.py`'s `verify_intent()` (promoted near-verbatim) is re-run against its existing 16-scenario synthetic test suite as a regression gate; any Milestone 1 code that constructs or consumes a bundle must go through this function, never a bespoke check.
10. **The first-boot confirmation gate has no timeout, no default, and does not treat EOF as confirmation.** `firstboot_statemachine.py`'s promoted CONFIRM-gate is re-verified with the same discipline Investigation 6 used (a 40-second-idle screenshot showing no state change, a post-CONFIRM apply/verify/commit screenshot) — this is the one property from Milestone 0 that a regression here would be most severe, given the project's own prior real defect in exactly this area.
11. **Diagnostic packages install only after the confirmation gate, never before or unattended.** The end-to-end QEMU proof (§2) must show, on screen, that no `apt-get install` for the five tools runs until the literal `CONFIRM` has been entered — reusing Investigation 5's evidence that `DEBIAN_FRONTEND=noninteractive` package installation triggers no `sensors-detect`/SMART self-test, now gated behind the confirmation step rather than run unconditionally.
12. **Consumed-intent replay protection is existence-based, not content-based**, per Investigation 9 — carried forward unchanged into the promoted module; no Milestone 1 code may add a "try to parse and see if it's still valid" fallback path that would reintroduce the fail-open risk Investigation 9's test 9b specifically closed.

## 5. Milestone sequence with fast acceptance tests

Each phase below is TDD-first (write the test, watch it fail, implement minimally, verify green, refactor, confirm ≥80% coverage on the modules touched) per this project's standing testing rule, and each phase's acceptance test is meant to be fast enough to run routinely, not a full end-to-end QEMU pass every time — the full pipeline integration test (Phase 7) is the expensive one, run less frequently.

1. **Acquisition/verification module** (`drive_setup_iso.py`'s verification half). Acceptance: reproduces Investigation 1/2's exact GPG→hash chain against a **cached, checked-in-as-fixture** copy of the real signed metadata (not a live network fetch on every test run) — a tampered fixture must fail verification.
2. **Credential generation** (`drive_setup_credential.py`). Acceptance: `test_secret_handling.py` asserts no code path places a password/hash into `subprocess` argv (inspectable via mocking `subprocess.run` and asserting on the call's `args`/`input` split), and that the generated hash round-trips through a synthetic `crypt`-compatible verifier.
3. **Answer server** (`drive_setup_answer_server.py`). Acceptance: re-run of Investigation 3's 10-scenario matrix as real `tests/unit/` coverage (not experiment-local), plus the logging gap fix verified (a request produces a timestamped log line).
4. **Wrapper + workspace** (`drive_setup_wrapper.py`, `drive_setup_workspace.py`). Acceptance: success path, induced-failure path (unwritable output), and an interrupted-process path (SIGKILL mid-`prepare-iso`) all leave zero leftover credential-bearing files, verified by a canary-content grep over the workspace directory tree after each.
5. **Orchestration + workspace-scoped install** (`drive_setup_iso.py` full, `drive_setup_boot.py`'s install half). Acceptance: one real sparse-image install via QEMU, reaching `install_success_confirmed` per invariant 8, with the resulting image's partition/LVM structure statically verified (`fdisk -l`/`blkid -p` on the file directly, no loop device).
6. **Boot verification** (`drive_setup_boot.py`'s boot half). Acceptance: reproduces Investigation 4 — legacy-BIOS reboot-to-disk, fresh-OVMF-NVRAM boot to login, and a `system_powerdown`-based clean-shutdown check, all against a freshly-generated image from Phase 5 (not a stored one), plus the `once=d` regression fixture from invariant 7.
7. **Full pipeline integration proof** (all modules together, including staged `firstboot_statemachine.py` + a synthetic-key-signed `setup_intent.py` bundle). Acceptance: one continuous run — acquire, generate credential, serve answer, prepare ISO, install, verify boot both firmware paths, boot again with first-boot unit staged, observe tty1 discovery-then-wait, type `CONFIRM`, observe the five diagnostic packages install and `iperf3` end up disabled/inactive (per Investigation 5's finding), observe completion marker set, observe clean shutdown. This is the expensive test — run before declaring Milestone 1 complete and on-demand thereafter, not on every commit.
8. **Manifest + evidence report generator.** Acceptance: given a completed Phase 7 run's captured state (screendumps, logs, checksums, timing), produces one machine-readable JSON manifest (schema below) and one human-readable Markdown evidence report, both without requiring re-running the pipeline.
9. **Retention/cleanup pass.** Acceptance: after a full Phase 7 run plus manifest generation, a scripted retention check (§7) confirms every ephemeral-credential, answer-file, temporary-ISO, test-key, and disposable-image category has been handled per its stated policy — this is itself a test, not a manual step.

## 6. Build manifest schema (machine-readable deliverable, item 11)

A JSON document per completed Milestone 1 pipeline run, written to a retained (non-secret) location:

```json
{
  "schema": "baseline.m1-build-manifest.v1",
  "run_id": "<uuid>",
  "started_at": "<ISO8601>",
  "completed_at": "<ISO8601>",
  "source_iso": {"sha256": "...", "size_bytes": 0, "verified_via": "gpg-signed-release-chain"},
  "assistant_version": "9.2.x",
  "fetch_mode": "http",
  "answer_server": {"tls_cert_fingerprint": "...", "session_consumed_once": true, "hardware_fact_match": true},
  "install_outcome": "install_success_confirmed | install_outcome_indeterminate | install_failed",
  "boot_verification": {"legacy_bios_reboot_to_disk": "boot_success", "fresh_uefi_nvram": "boot_success", "clean_shutdown": "confirmed | not_captured"},
  "partition_structure": {"table": "gpt", "partitions": ["bios-boot", "esp", "lvm"]},
  "firstboot_proof": {
    "setup_intent_key": "synthetic-test-key",
    "confirmation_gate_no_timeout_verified": true,
    "diagnostic_packages_installed_after_confirmation": true,
    "iperf3_state": "disabled/inactive"
  },
  "artifact_retention": {"credentials_purged": true, "temp_isos_deleted": true, "test_keys_discarded": true, "disposable_image_retained": false}
}
```

The human-readable evidence report is the Markdown narrative counterpart — screenshots referenced by path, the exact commands run, and the same invariant-by-invariant checklist as §4, each marked pass/fail with a link to the specific test or captured evidence, in the same style this session's decision records already use.

## 7. Artifact retention rules (item 12)

Consistent with the discipline already established across Milestone 0's nine investigations:

| Category | Retention |
|---|---|
| Ephemeral one-time install credentials (plaintext) | Never written to disk at all — process memory only, per `drive_setup_credential.py`'s design; nothing to retain or destroy. |
| Password hash | Exists only inside the answer file / prepared ISO / installed disk image's own shadow file — not separately retained by tooling. |
| Answer files | Deleted immediately after the one QEMU session that consumes them completes (success or failure) — never retained across runs. |
| Prepared ISOs | Deleted after the one install that used them, or after a failed run's postcondition check confirms the artifact was inspected — never reused across installs (Investigation 2's finding: a fixed one-time credential makes reuse unsafe). |
| Test/synthetic Ed25519 keys (setup-intent) | Discarded at the end of each test/build run; **never checked into the repository, never reused across runs, never treated as a stand-in for a real provisioned key.** A fresh keypair every run is the default, not an optimization. |
| Disposable sparse install images | Deleted after their evidence (manifest, screenshots, static verification output) is captured, **unless** explicitly held for the next phase's reuse within the same pipeline run (e.g. Phase 5's image feeding Phase 6/7) — never retained past the run that produced them without a stated reason. |
| Build manifest (JSON) + evidence report (Markdown) | Retained — these contain no secret material by construction (the schema in §6 has no credential fields) and are the actual Milestone 1 deliverable. |
| Screendumps/logs referenced by the evidence report | Retained only for the specific run(s) cited in a currently-relevant evidence report; superseded runs' large binary artifacts (PPM/PNG dumps, full serial logs) may be pruned once a corrected/final report supersedes them, mirroring how Investigation 3's original indeterminate-run artifacts were handled. |
| `experiments/` workspace contents generally | Gitignored, never committed, cleaned opportunistically — this was already the rule through Milestone 0 and doesn't change. |

## 8. Dependency and privilege boundaries

- **No new host packages.** The extracted `proxmox-auto-install-assistant` binary and the already-present `xorriso`, `qemu-system-x86_64`, `ovmf` packages are sufficient, per Investigation 1's direct confirmation — Milestone 1 adds no `apt install` requirement.
- **No new Python dependencies beyond what Milestone 0 already confirmed present**: `cryptography` (setup-intent signing), stdlib only for everything else. If a genuine new dependency need emerges during implementation, it must be justified in that phase's own commit, not assumed here.
- **No privileged operation of any kind runs on the development host.** Every QEMU session runs as the unprivileged invoking user against workspace-local files; `pkexec` is never invoked by Milestone 1 code, since the shipped helper's physical-device capability remains structurally absent (§1/§4 invariant 1) and the existing image-backed helper action doesn't require new privilege beyond what v1 already has.
- **Setup-intent signing keys are test/synthetic only** (§1, §7) — no real key generation, storage, or rotation infrastructure is built in Milestone 1. This is a hard boundary, not a simplification of convenience: building real key-lifecycle plumbing prematurely, before the verification-side logic has been used in anger, risks exactly the kind of "signed implies more than it does" overclaim Investigation 9 was created to catch.
- **No credential manager, keyring, or system secret store is touched.** The one-time install credential lives in process memory only; test/synthetic setup-intent keys live in memory or a gitignored temp path for the duration of one run.

## 9. Explicit non-goals for Milestone 1

- Real setup-intent trust-anchor provisioning (real signing-key generation/storage/rotation, real independently-provisioned verification key baked into a real released first-boot image) — explicitly deferred, not delivered, per §1/§8.
- The transactional firewall apply/rollback mechanism (PRD §5.10) — Milestone 2 scope, untouched here; Milestone 1's first-boot proof (§2) only exercises the discovery→confirm→apply(diagnostics)→verify→commit shape, not a real firewall transaction.
- SSH preconfiguration application, tether preconfiguration application, and handoff-packet transactional restore (PRD §5.11–§5.13) — all Milestone 2 scope.
- Any physical-device code path, argument, flag, or polkit action — structurally excluded, not merely unimplemented (§4 invariant 1).
- Real MD RAID and LUKS-on-LVM storage-ancestry validation against actual `mdadm`/`cryptsetup` output — see §10, this belongs to Milestone 1 but as an explicitly scoped, separately-tracked sub-task, not assumed complete because Investigation 7's synthetic tests already pass.
- Resolving the NetworkManager-presence assumption — see §11, tracked but not blocking.
- Any change to either GitHub repository's settings, visibility, or push configuration — §0 is a recommendation, not an action taken.
- A production release build pipeline, CI wiring, or packaging beyond what's needed to prove the modules in §3 work — Milestone 1 produces tested library modules and one proof-integration run, not a shipped release artifact.

## 10. Where MD RAID / LUKS-on-LVM validation belongs

Investigation 7 left this explicitly open: 12/12 synthetic tests pass for both fixture shapes, but neither has real-tool-output validation (`mdadm`/`cryptsetup` were absent from the Milestone 0 test image). This belongs in **Milestone 1, Phase 4 or 5** (alongside the wrapper/orchestration work, since it needs the same "install `mdadm`/`cryptsetup` inside a disposable QEMU guest, not the development host" pattern Investigation 5/7 already used successfully) — **as its own explicitly-tracked sub-task, not folded silently into "storage ancestry is done."** Concretely: build the same loop-backed MD RAID1 and LUKS-on-LVM fixtures Investigation 7 already scripted (`experiments/m0-inv7/fixture_test.sh` already has the MD RAID portion half-built) inside a disposable QEMU guest with `mdadm`/`cryptsetup` installed via the normal (non-offline, per §5.8's own decision) package mechanism, capture the real `mdadm --detail`/`cryptsetup luksDump` output, and confirm it matches the synthetic model exactly the way LVM and ZFS already did. This does not block Phases 1–3 or 6–9 of this plan and can run in parallel with them; it does block calling `storage_ancestry.py` "fully real-tool-validated" in the Milestone 1 completion report (§12).

## 11. Treatment of the unresolved NetworkManager assumption

PRD §5.12 assumes Proxmox's base install omits NetworkManager, and §11's open-risks list confirms this was never actually investigated at Milestone 0 — it's an unverified assumption, not a finding. Milestone 1 does not need to resolve this to complete its own scope (§2's proof exercise doesn't exercise §5.12's tether-preconfiguration code, which is Milestone 2 work), but it **must not be silently assumed true by any Milestone 1 code** that happens to touch networking. Concrete handling: add one direct, cheap check to Phase 6 or 7's QEMU proof run — after reaching the installed system's login/first-boot state, confirm via a simple discovered-fact query (already within `firstboot_statemachine.py`'s fact-discovery step, which runs unattended and has no side effects per invariant 10) whether `NetworkManager.service` exists/is enabled on the real installed Proxmox system. This costs nothing extra (the QEMU session already exists for Phase 7 regardless) and converts an unverified assumption into either a confirmed fact or a correctly-flagged remaining unknown before Milestone 2 code starts depending on it. If it's not confirmed by the time Milestone 2 begins, Milestone 2's plan must treat §5.12 as still unresolved, not inherit Milestone 1's silence as tacit confirmation.

## 12. Criteria for declaring Milestone 1 complete

All of the following, each with evidence recorded the same way Milestone 0's decision records did (not just a checkbox):

1. Every module in §3's table exists under `baseline/lib/` or `tests/unit/drive_setup_tests/` with tests written first (TDD, red→green→refactor) and passing.
2. ≥80% coverage on every module listed in PRD §8.6, verified by the project's coverage tool, not estimated.
3. All twelve invariants in §4 have a passing, named test — no invariant is "true by inspection" without an automated check.
4. Phase 7's full pipeline integration proof has run at least once successfully, with its manifest (§6) and evidence report generated and reviewed.
5. §10's MD RAID/LUKS real-tool validation sub-task is either complete (with evidence matching LVM/ZFS's standard) or explicitly still open and stated as a named carry-forward into Milestone 2 — not silently dropped.
6. §11's NetworkManager check has run at least once during Phase 7 and its result (confirmed present, confirmed absent, or inconclusive) is recorded in the evidence report — not left as an unexamined assumption.
7. §7's retention rules have been verified by the Phase 9 automated check on at least one full run — no leftover credential-bearing or secret-bearing artifact found.
8. `test_backend_surface.py` (invariant 1) passes and is confirmed to cover both the Python library's and the bash helper's full accepted-argument surface — this is re-verified explicitly at completion, not just once during Phase 1.
9. A short closeout document (mirroring this session's decision-record style) is written summarizing what was proven, what was partially proven, and what's carried into Milestone 2 — matching the honesty standard Milestone 0's ledger set, not a "Milestone 1: done" one-liner.
10. Nothing has been pushed to `cliffthelin/baseline` since this plan's acceptance unless the user has explicitly resolved §0's ambiguity in its favor.

## 13. Repository/commit workflow for Milestone 1 work

Per §0's recommendation: all Milestone 1 commits target `origin` (`cliffthelin/BaseLineProx`) only, using the existing non-interactive credentials already confirmed working in this session. No push to `cliff` (`cliffthelin/baseline`) happens as part of implementing this plan unless the user says otherwise. If any git operation would prompt for authentication or authorization, it is skipped and the local commit is preserved, exactly as this session's standing practice already requires.

---

This plan is the deliverable for this turn. No code has been written, no privileged interface invoked, no package installed, and no authorization request triggered while preparing it. Awaiting review before any implementation phase begins.
