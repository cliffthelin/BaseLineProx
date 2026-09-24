# Decision record: Gate E rebuilt as the real, integrated A→E→F authorization path — one full run proves it

Date: 2026-09-23/24
Investigator: Claude Code
Status: complete. The prior Gate E pass (decision record 25) proved the state-machine mechanics in isolation. This pass rebuilds `firstboot_statemachine.py` as the real integration point connecting Gate A's repair pipeline, Proxmox detection, and package installation/verification behind one tty1 screen and one CONFIRM gate, deploys it via the real production path (`boot/provision.sh`), and demonstrates the **full A→E→F sequence in a single real boot**, followed by a second real reboot proving persistence.

## Scope discipline

No physical drive touched. No GUI packages installed. No Chromium/browser work. No host privilege escalation. No authorization requests triggered on the host. No push to `cliffthelin/baseline` - `origin` (`cliffthelin/BaseLineProx`) only. `settings_web.py` was not touched, not imported, not wired into this path, and was not running during any of this work. Synthetic setup-intent framing only (no real bundle exists or is claimed). One disposable QEMU target (`experiments/m1-gateE-integrated/`), deleted after inspection per the established retention rule; serial logs grepped clean of the test password before deletion.

## What was promoted / rewritten

**`baseline/lib/setup_intent.py`** - unchanged from decision record 25 (verbatim promotion of the Investigation 9 prototype).

**`baseline/lib/firstboot_statemachine.py`** - substantially rewritten, not the thin wrapper decision record 25 shipped. It now:

- Calls `firstboot_network_repair.py`'s public building blocks directly (`discover`, `diagnose`, `wait_for_confirmation`) instead of its all-in-one wrapper, so discovery, diagnosis, and confirmation can be interleaved with Proxmox detection and package installation under **one** combined tty1 screen and **one** CONFIRM gate - not two separate prompts for one first boot.
- Adds `proxmox_detect.py` (informational - confirms Proxmox is already installed) and `diagnostics.py` (functional verification of the five tools post-install) as new integration points.
- Adds `install_diagnostic_tools()` / `verify_diagnostic_tools()` - real `apt-get install`, real `dpkg-query`/`systemctl`/`ss` verification, real calls into `diagnostics.py`'s collectors.
- Implements a full nine-state journaled machine (`created → detected → discovered → proposed → confirmed → network_repaired → packages_installed → packages_verified → committed`), each transition durably written (fsync file + fsync directory + atomic rename, matching `setup_intent.record_consumption`'s pattern) before the next stage begins.
- Gates completion strictly: the marker is written **only** after package installation **and** functional verification both succeed - never on confirmation alone, never on network success alone. A corrupted or unparseable journal is never trusted for resume - it fails closed by restarting from `created`, which can only ever cause a redundant discovery or an extra confirmation, never a skipped authorization.

New: `baseline/lib/proxmox_detect.py` and `baseline/lib/diagnostics.py` (already existed from earlier sessions, now wired in for real) are copied by `provision.sh` alongside the rest.

## Unit tests

23 tests total for this pass's code (13 for `setup_intent.py`, carried over unchanged from decision record 25; 19 new/rewritten for `firstboot_statemachine.py`, replacing decision record 25's 10 - the old ones tested a design that no longer exists). Explicitly covering every case requested:

- State transitions (`test_successful_completion_commits_after_confirm_network_and_packages` asserts the exact 9-state sequence).
- Interruption recovery (`test_resumes_from_proposed_state_without_rediscovering`, `test_resumes_from_network_repaired_state_without_reapplying` - hand-constructs a journal at a mid-flow state and confirms the already-completed work is never redone).
- Corrupted journals (`test_corrupted_journal_starts_fresh_not_trusted_for_resume`, `test_journal_with_unknown_state_value_starts_fresh`, `test_completion_marker_is_never_bypassed_by_a_corrupted_journal`).
- Declined authorization (`test_declined_confirmation_makes_no_change_and_does_not_commit`, `test_eof_on_stdin_never_treated_as_confirmation`, `test_no_safe_repair_candidate_refuses_without_any_prompt`).
- Network failure preventing package installation (`test_network_verification_failure_blocks_package_installation`, `test_network_apply_failure_blocks_package_installation` - both assert `apt-get install` was never called).
- Package failure preventing completion (`test_package_install_failure_blocks_completion`, `test_package_verification_failure_missing_package_blocks_completion`, `test_iperf3_active_fails_verification_and_blocks_completion`, `test_iperf3_listening_fails_verification_and_blocks_completion`).
- Successful completion (the first test above, plus `test_already_healthy_lifeline_still_requires_confirmation_for_packages`).

**205/205 unit tests pass** across the whole suite (no regressions).

## Deployment path verified before launching QEMU - per instruction

Before any QEMU boot, cross-checked every `$SRC/...` path `boot/provision.sh` references against a tarball of `baseline/`, `boot/`, and `tests/console_font_check.sh` (`comm -23` against the referenced-file list - zero missing). After extracting the tarball inside the guest, explicitly `ls`'d all six of the newly-added critical files (`firstboot_statemachine.py`, `proxmox_detect.py`, `diagnostics.py`, `baseline-firstboot.service`, `console_font_check.sh`, `baseline-return.sh`) and confirmed none were missing **before** running `provision.sh` - this is the exact check that would have caught decision record 25's missing-rollback-binary mistake earlier, now applied proactively rather than discovered by a mid-run failure.

## A real, honest finding: `provision.sh` cannot fully complete when run interactively from tty1 itself

Running `bash boot/provision.sh` from the tty1 session I was typing into hit a real, structural problem: the script's own `systemctl disable --now getty@tty1.service` line (needed so `baseline.service` can later claim tty1) stops the getty process backing the very shell running the script, terminating it mid-execution. The log confirms the script ran cleanly through package installation and all three `cp .../etc/systemd/system/...service` + `Removed .../getty@tty1.service` lines, then stopped - `systemctl enable baseline-firstboot.service` / `systemctl enable baseline.service` / `systemctl enable baseline-additive-dhcp-reapply.service` and the remaining lines never ran, confirmed directly (`baseline.service` showed `disabled; inactive (dead)` immediately afterward).

This is **not a defect in Gate E's design or in `provision.sh`'s command sequence** - it is a real operational constraint of *how the script was invoked* in this test (interactively, from the tty it was about to disable). The fix applied here was to complete the remaining `systemctl enable` calls (deliberately **without** `--now` on `baseline.service`, so the real first-boot sequence would still run on the next clean boot rather than starting immediately) from `tty2` instead, which is unaffected. **This is flagged as a real gap in `provision.sh` for its next revision**: it should either be run non-interactively (e.g., piped, or via a one-shot unit) or from a session other than the tty it disables, not assumed safe to run interactively from tty1 as currently documented. Not fixed in this pass - out of scope per the instruction to stop after Gate E.

## The integrated run: one real boot, the full combined screen, real 46-second-idle-no-change, real CONFIRM, real success

After deployment (via the corrected path above) and one clean `reboot`, `baseline-firstboot.service` took over tty1 (per its `Conflicts=getty@tty1.service`/`Before=baseline.service` ordering) and produced, for real, on the very first boot after provisioning:

- **Proxmox detection**, from the real running system: `pveversion runs and reports: pve-manager/9.2.2/b9984c6d90a4bd80` and `/etc/pve (pmxcfs) is present`.
- **The real detected broken Fixture-A-shaped networking**: `Mode: additive`, `Target interface: vmbr0 (bridge)`, `Physical device(s): ens3`, the exact before/after diff (adding `iface vmbr0 inet dhcp` while the `ens3` manual stanza and the existing `vmbr0 inet6 static` stanza are both left untouched).
- **The five packages proposed**: `lm-sensors`, `nvme-cli`, `smartmontools`, `iperf3`, `ethtool`.
- **Rollback/verification behavior described in full**, and the **setup-intent integrity status**, worded exactly as PRD SS5.6 requires ("INTEGRITY/CORRUPTION check only... not authentication... never the authorization gate").
- **One combined `Type CONFIRM...` prompt** at the end.

**Waiting evidence**: captured `WAITING_PROOF.ppm`, waited 46 seconds with zero input of any kind, captured `WAITING_PROOF_2.ppm`. `md5sum` of the two files is **identical** (`e0632c28a2dd9704c1a58803af6db6d2`) - genuinely byte-for-byte, not merely visually identical (this proposal has no blinking-cursor artifact, unlike decision record 25's bash-prompt case, so this is a strictly stronger result). No progression, no timeout firing, no default branch taken. Both files retained as `WAITING_PROOF.png`/`WAITING_PROOF_2.png`.

**Post-authorization evidence**: typed the literal string `CONFIRM` (a real keystroke sequence via the QEMU monitor, not an injected stdin iterator - the integration proof specifically avoids that). Captured immediately after: `[baseline-firstboot] network result: success - vmbr0 gained a new inet dhcp stanza (existing inet6 stanza preserved); address=10.0.2.15 gateway=10.0.2.2` followed by `[baseline-firstboot] installing diagnostic tools...`.

**Full state transition, confirmed directly from the durable journal** (not inferred): `created`, `detected`, `discovered`, `proposed`, `confirmed`, `network_repaired`, `packages_installed`, `packages_verified`, `committed` - all nine states present in order.

**Independently verified, not just log lines**: `ip -4 addr show vmbr0` showed a real `10.0.2.15/24` address; `ip -4 route` showed a real default route via `10.0.2.2`; `dpkg -l` confirmed all five packages `ii`; `systemctl is-enabled iperf3` → `disabled`; `systemctl is-active iperf3` → `inactive`.

**Then, still on this same boot**, systemd proceeded (per `baseline.service`'s `After=baseline-firstboot.service` ordering) to start the real Baseline console - **the actual Textual TUI rendered correctly on the VGA console**, showing `BaselineOS — online - lifeline up` and real hardware/network data (CPU, memory, `ens3` link state) in its Hardware tab. tty2, switched to via a real `Ctrl+Alt+F2` VT-switch through the QEMU monitor, showed a completely ordinary, unaffected Proxmox login prompt throughout.

## Second reboot: full persistence proof

Issued a second, real `reboot` from inside the guest. On this boot:

- **Baseline appeared on tty1 immediately** - no firstboot proposal, no delay, straight to the normal `BaselineOS — online - lifeline up` console.
- **tty2 still a normal, working login prompt.**
- `systemctl is-active baseline-firstboot` → `active` (the oneshot unit's `RemainAfterExit=yes` state, confirming it completed without re-running its logic) and `systemctl is-active baseline` → `active`.
- **Real IPv4 `10.0.2.15/24` persisted** - the repaired networking survived the reboot.
- **All five packages persisted** - `dpkg -l ... | grep ii | wc -l` → `5`.
- **`iperf3` still `disabled`/`inactive`.**
- **First-boot did not rerun** - the completion marker (`/var/lib/baseline-firstboot/complete`, timestamped `2026-09-24T01:10:42`) was checked first and short-circuited the second boot's `baseline-firstboot.service` run entirely, exactly as designed.

## Whether the integrated A→E→F path is now demonstrated in one run

**Yes.** This is the single closeout step decision record 25 and the milestone plan both named as still missing, and it is now closed: one real boot took a genuinely broken (Fixture-A-shaped) Proxmox install, through real local authorization (46-second-idle-no-change proven, real CONFIRM), through Gate A's real repair pipeline (address/route/gateway independently verified), through real package installation and functional verification (Gate F's mechanism, invoked for the first time *as gated by real first-boot authorization* rather than run standalone), to a real, correctly-rendering Baseline console taking over tty1 - and a second reboot proved every part of that persists and does not re-trigger.

## Remaining limitations, stated plainly

- `provision.sh`'s interactive-from-tty1 self-interruption (above) is a real gap in the *documented deployment procedure*, not in Gate E's own code - flagged for the next revision, not fixed here.
- The `baseline-firstboot.service` unit's own `Conflicts=getty@tty1.service` ordering was exercised for real in this pass (unlike decision record 25, which ran the state machine from an interactive shell) - this closes that previously-flagged gap.
- `sensors`/`nvme`/`smart` functional collectors still only exercise the "no hardware" path on this VM (decision record 22's finding) - `verify_diagnostic_tools()` treats that as success, correctly, but real populated hardware output remains unverified.
- `setup_intent.py`'s actual signed-bundle *use* (PRD SS5.6's installer-GUI-to-first-boot handoff) is still not wired to anything - this pass's tty1 display is informational/synthetic-only, exactly as scoped.
- Gate E's own unit was not tested under a simulated crash-mid-confirmation (`SIGKILL` during the indefinite wait) in this integrated pass - the unit-level interruption-recovery tests cover the state-machine logic directly; a real kill-during-wait against the live QEMU process was not repeated here.

## Commits and push status

Three commits to `origin` (`cliffthelin/BaseLineProx`), `main` branch: the rewritten `firstboot_statemachine.py` + `proxmox_detect.py`/`diagnostics.py` provision.sh wiring + rewritten tests, this decision record, and the milestone-1-plan status update. No push to `cliffthelin/baseline` at any point.
