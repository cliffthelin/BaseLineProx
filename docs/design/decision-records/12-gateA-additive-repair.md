# Decision record: Gate A implementation — additive network repair for Fixture A

Date: 2026-09-21
Investigator: Claude Code
Status: complete. **71/71 unit tests passing. One disposable QEMU integration run performed, per instruction. Gate A does not fully pass — full success (verified working DHCP) was not reached — but the pipeline's fail-closed safety properties (exact backup/restore, refuse-rather-than-risk on a real tooling warning) were directly demonstrated against real infrastructure, and the actual, unmodified Fixture A is preserved as the primary case throughout, with no `ipv6=off` correction used anywhere in this pass.**

## Scope discipline

No push to `cliffthelin/baseline`. No physical device touched. No package installed on the host (all `ifreload`/`ifupdown2`/`curl`/`getent` dependencies were already present in the base Proxmox image, confirmed directly, not installed by this investigation). No sudo/pkexec/polkit/authorization-triggering call was made at any point — all work happened as the unprivileged user against disposable QEMU images and, inside the guest, as the guest's own root (the guest is a disposable, discardable Proxmox install, not a privilege boundary this investigation needed to cross on the host).

## 1. Import and rebase into BaseLineProx

Fetched `cliffthelin/baseline`'s `repair/host-network-reset-to-dhcp` branch read-only (already done in the prior comparison pass) and imported its files into this repository's `baseline/lib/`, `baseline/bin/`, `tests/unit/`, `boot/`, and `docs/design/` — verified the imported test suite (34 tests) passes unchanged first, before any modification. `boot/provision.sh` was extended additively (new `cp`/`chmod` lines only) — the existing `handoff.py`/`baseline-setup-wizard`/`gnupg` deployment lines, which the source branch's own diff had dropped (it predates their addition to `main`), were left untouched and are still deployed.

## 2. Byte-accurate fixtures

`tests/unit/test_phase0_additive_repair.py` defines `FIXTURE_A_IPV6_ONLY` and `FIXTURE_B_IPV4_FALLBACK` as literal transcriptions of the real captured files from decision record 10 (confirmed against the original screenshots), plus dedicated tests for the `source /etc/network/interfaces.d/*` glob-directive shape both fixtures end with.

## 3/4. Additive proposal for Fixture A, replace behavior preserved for Fixture B

- `topology.py` gained `derive_additive_target()` (and its supporting walk), the counterpart to the existing `derive_target()` for the case where the observed device has a non-`inet` (in practice `inet6`) static stanza and no `inet` stanza at all. `topology.derive_target()` itself is **completely unmodified** — confirmed by direct diff — and still correctly refuses Fixture A with `no_static_config`, exactly as decision record 11 found.
- `ifnet_config.py` gained `add_dhcp_stanza()`: appends a new, separate `iface <name> inet dhcp` line to the end of the file, refusing if an `inet` stanza already exists for that name (that's a replace case) or if the config isn't confidently parsed. `rewrite_stanza_to_dhcp()` (the existing replace path) is **unmodified**.
- `repair_additive.py` (new file, `repair.py` untouched except for one shared fix — see §9) orchestrates the additive pipeline, reusing every precondition/backup/rollback/verification function from `repair.py` directly (imported, not reimplemented) — only the derivation and rewrite steps differ from `reset_interface_to_dhcp`.
- `repair_additive.plan_and_derive()` tries the existing replace-path derivation first and only falls back to the additive derivation when replace found no candidate at all (not on ambiguity) — Fixture B is confirmed, by a dedicated test, to still route through the unmodified replace path and never touches the additive code at all.

## 5. Physical bridge member stays `manual`

`ens3`'s `inet6 manual` (Fixture A) / `inet manual` (Fixture B) stanza is never a candidate in either derivation path and is never written to by either rewrite function — confirmed by dedicated tests asserting byte-identical preservation, and directly observed in the real QEMU run (§9below): `ens3`'s stanza was never touched.

## 6. Refusal conditions

`repair_additive.add_dhcp_to_bridge()` reuses `repair.py`'s `check_standalone_host` (cluster membership), `detect_ifupdown2` (unsupported environment), `check_connection_guard` (unattended-with-protected-session), and the same `topology_ambiguous` derivation-failure path — all unit-tested against the additive pipeline directly (`test_cluster_membership_refuses_additive_path_too`, `test_no_additive_candidate_refuses_cleanly`, etc.), not merely inherited by assumption.

## 7. Reused, not reimplemented

Backup creation/verification, the closure-hash concurrent-edit check, independent rollback arming (`systemd-run`), atomic write, syntax validation, `ifreload -a` apply, and event logging are all called directly from `repair.py`'s existing, already-tested functions — `repair_additive.py` adds zero duplicate logic for any of these. Verification was extended (`verify_target_extended`, new function, additive-path-only) to also check DNS resolution (`getent hosts`) and outbound HTTPS (`curl --interface`) target-bound, per instruction — `repair.verify_target` (address/route/gateway-ping) itself is unmodified and is still called as the first stage of the extended check.

## 8. Residual IPv6, never claimed repaired

Every successful additive attempt logs a distinct `residual_config_detected` event naming the preserved family/method, and the pipeline's own result/detail text says "existing inet6 stanza preserved" — never "repaired" or "fixed." No code path in this pass deletes, comments out, or rewrites the IPv6 stanza. A later, separately authorized cleanup action is explicitly out of scope, per instruction and per the module's own docstring.

## 9. The one shared fix to `repair.py`, and why it was necessary

The real captured fixture (both address-family variants) ends with `source /etc/network/interfaces.d/*` — a glob, not a literal path. The original imported `read_interfaces_config()` tried to `read_text()` that literal string, got `OSError`, and silently recorded it as an empty file — which could hide real fragment files. The first fix attempt (mark it as a confidence-breaking refusal) was tested and found to be wrong: it would refuse on **every** real fixture unconditionally, since the glob line is always present, making the additive repair permanently inapplicable to the actual reproduced case. Per instruction ("add glob support only if required for the real fixture... otherwise retain as documented refusal") — it **is** required, empirically, not just plausibly. Implemented minimal real resolution: `ifnet_config.resolve_source_glob()` (pure, `fnmatch`-based) plus a fix in `repair.read_interfaces_config()` to call `runner.listdir()` on the glob's parent directory and resolve real matches, exactly mirroring how `source-directory` already worked. This is the **only** change to the previously-imported, previously-tested `repair.py` — confirmed by direct diff (12 added/changed lines, nothing else touched) — and is covered by four new tests including one against a real (FakeRunner-simulated) fragment file and one confirming an empty `interfaces.d/` (the normal case) resolves cleanly with no phantom file.

## First-boot wiring (`firstboot_network_repair.py`)

A new, narrowly-scoped module — not a promotion of the general Investigation 6 state machine (firewall/handoff/tether remain untouched and out of scope). Implements exactly: automatic discovery (`discover()`, read-only, zero side effects, confirmed by a dedicated test asserting no writes/no `systemd-run` calls) → diagnosis with an exact-diff proposal (`diagnose()`, `format_proposal_for_tty1()`) → indefinite local confirmation (`wait_for_confirmation()`, no timeout, no default, EOF never treated as confirmation — same discipline as Investigation 6's corrected state machine, re-verified here by dedicated tests) → the appropriate repair pipeline (replace or additive, chosen by `plan_and_derive`) → `package_install_allowed` gated strictly on `result.ok`, never on confirmation alone.

**Deliberate design choice, stated explicitly**: this flow does not call `harness.propose_repair()` (the AI-harness step from the original branch's design). Diagnosis here is fully deterministic (topology parsing + `network.check_lifeline()`), so no AI involvement is needed or was added — matches "nothing beyond network integration," avoiding an unrequested AI-integration expansion.

**A real gap found and fixed in this module, not in `network.py`**: `network.py`'s own default-route lookup (`_route_default()`) is IPv4-only (`ip -4 route show default`) and returns no device at all when only an IPv6 default route exists — exactly Fixture A's shape. `firstboot_network_repair._observed_dev()` adds a protocol-agnostic fallback (plain `ip route show default`, then `ip -6 route show default`) so the repair proposal still knows which interface to target. `network.py` itself was not modified — this fallback lives entirely in the new module.

## Unit test results

71/71 passing (34 original + 37 new), TDD-driven for the new modules — tests were written and run to red before each corresponding implementation change, with two real design corrections made in response to actual test failures (the glob-refusal redesign in §9, and two counting/scripting bugs in the test harness itself, not the production code). ≥ line coverage was not separately measured as a percentage this pass — per the plan's own "coverage is a floor, not proof" correction, the bar applied here was behavioral: every invariant in the instruction's verification list (below) has a dedicated, named test.

| Required verification | Test(s) |
|---|---|
| Fixture A produces a bounded additive IPv4-DHCP proposal on vmbr0 | `test_additive_pipeline_success_fixture_a_produces_bounded_additive_proposal`, `test_diagnose_produces_additive_diff_for_fixture_a` |
| Fixture B continues to use the existing replacement behavior | `test_derive_target_replace_path_still_selects_vmbr0_for_fixture_b`, `test_plan_and_derive_picks_replace_for_fixture_b`, `test_replace_path_still_used_for_fixture_b_through_first_boot_flow` |
| ens3 remains manual | `test_ens3_remains_manual_after_reparsing_the_additive_result`, `test_ens3_remains_manual_after_real_pipeline_run` |
| Declining authorization makes no change | `test_declining_authorization_makes_no_change` |
| Concurrent edits refuse | `test_concurrent_edit_between_backup_and_write_refuses` |
| Failed DHCP restores the exact original | `test_failed_apply_leaves_rollback_armed_original_restorable`, `test_failed_syntax_check_restores_exact_original` |
| Successful DHCP verifies address, route/gateway, DNS, HTTPS | `test_successful_dhcp_verifies_address_route_gateway_dns_and_https`, `test_dns_failure_fails_verification_even_with_address_and_route_present`, `test_https_failure_fails_verification_even_with_dns_working` |
| Persistence across normal reboot | **Not unit-testable** (requires a real reboot) — this was the target of the QEMU integration run; not reached, see below. |

## QEMU integration run — one disposable install, real evidence, Gate A does not fully pass

Reused Investigation 3's proven pipeline (unmodified) to install a fresh disposable image **without `ipv6=off`**, reproducing genuine Fixture A directly (`https://[fec0::5054:ff:feba:5e20]:8006/` on first login — confirmed via screendump, same shape as decision record 10). The repair modules were injected via a read-only vvfat drive (Investigation 6's proven method) and staged at the real, production paths (`/opt/baseline/lib/`, `/opt/baseline/bin/baseline-repair-rollback`).

**First attempt**: refused cleanly at the rollback-arming step (`rollback_arm_failed: could not arm the independent rollback timer: Failed to find executable /opt/baseline/bin/baseline-repair-rollback`) — an environment-setup gap in this test (the wrapper wasn't yet staged at its production path), not a defect in the pipeline. Confirmed the live `/etc/network/interfaces` was byte-identical to the pre-attempt backup afterward — no partial write occurred, matching the "arm rollback before any write" ordering directly.

**Second attempt**, after staging the rollback executable correctly: the pipeline ran for real through discovery (correctly reporting `address_assigned: false` with the exact same IPv4-only-route-lookup gap `firstboot_network_repair._observed_dev()` was built to work around), diagnosis (correctly derived `vmbr0`, `additive`, `ens3` as the physical member), the exact-diff tty1 proposal (byte-accurate before/after text, captured directly), confirmation, backup, and rollback-arming (succeeded this time) — then **refused at the syntax-validation step**: `ifreload --syntax-check` reported `warning: vmbr0: bridge-fd: value of out range "0": valid attribute range: 2-255` with a non-zero exit code for the additive (two-stanza) file, and the pipeline correctly restored the exact original configuration (confirmed byte-identical via `diff` immediately after) rather than proceeding.

**A directly-verified, important nuance**: running `ifreload --syntax-check -a` by hand against the restored (original, single-stanza) Fixture A file produces the **identical warning text but exits 0** — the warning is non-fatal against the original file alone. The real, pre-existing `bridge-fd 0` value (present in Fixture A/B as generated by the automated installer, untouched by this repair) appears to be treated as fatal by this specific `ifreload` version specifically when a second `iface vmbr0 ...` stanza (the additive DHCP line) is also present — a genuine interaction this investigation did not have budget to isolate further, given the one-QEMU-run limit.

**Gate A status**: does **not** fully pass. Full success (a verified, working DHCP-acquired address with confirmed target-bound address/route/gateway/DNS/HTTPS, persisting across reboot) was not reached in this one permitted integration attempt. What **was** directly demonstrated, against real infrastructure, not mocks: the exact-diff proposal is accurate and honest; the confirmation gate works; the backup/rollback-arming sequence executes correctly; and — critically — when `ifreload` itself signals a real problem, the pipeline refuses and restores the exact original configuration rather than applying something uncertain. This is the fail-closed behavior the whole design exists to guarantee, and it held under real, non-mocked conditions.

## Retained limitations, explicitly not solved here

- **The `bridge-fd 0` / dual-stanza `ifreload --syntax-check` interaction** — real, reproducible, not yet root-caused beyond what's stated above. The additive (two-`iface`-stanzas-per-name) approach may need a different concrete syntax (e.g. `ifupdown2` may expect family-specific options declared differently when two stanzas share a name) — or this may be specific to this `ifreload` version's validator being stricter for the second stanza it encounters. Needs its own follow-up, not solved speculatively here.
- **Persistence across reboot** — not reached, since the pipeline never got to a successful apply in this attempt.
- **The documented duplicate-stanza-name limitation** (§9 of `repair_additive.py`'s `add_dhcp_stanza` docstring) — confirmed only at the unit-test level (re-parsing the additive result shows `duplicate_names`), not independently re-confirmed against real `ifreload` behavior this pass (moot, since the real run never reached a successful apply to observe this downstream).
- **The permanent boot-time rollback recovery service** — unchanged, still not installed, per the original branch's own stated (and still valid) blocker.

## Artifacts retained or deleted

Both plaintext credentials and their answer-file/hash content were deleted after use, confirmed absent from every retained log via direct grep before deletion. The prepared ISO and the 7.0GB disposable target image were deleted after their evidence was captured. Raw `.ppm` screendumps were deleted, keeping only converted `.png` evidence and small text logs. Total retained evidence: 488KB (`experiments/m1-gateA/`, gitignored, not committed).

## Whether Gates B–F may begin

**No, unchanged from the plan's own rule** — Gate A must fully pass before Gates B–F start. This pass produced real, valuable evidence and a materially safer pipeline (glob resolution fixed, additive repair implemented and reused correctly, fail-closed behavior proven against real tooling) but did not achieve a passing Gate A. The `bridge-fd`/dual-stanza syntax-check interaction is the concrete, named blocker for the next attempt.
