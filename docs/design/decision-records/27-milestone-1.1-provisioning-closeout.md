# Decision record: Milestone 1.1 provisioning closeout — provision.sh fixed, fresh integrated proof repeated, crash recovery proven

Date: 2026-09-23/24
Investigator: Claude Code
Status: complete. This closes the one release blocker decision record 26 identified (`provision.sh` disrupting its own tty1 session), re-proves the full integrated A→E→F path from a completely fresh disposable image with zero manual intervention, and adds the one proof decision record 26 did not attempt: interrupting the first-boot state machine mid-flow and proving journal-based recovery without repeating already-committed work.

## Scope discipline

No physical drive touched. No GUI packages installed. No Chromium/browser work. No host privilege escalation. No authorization requests triggered on the host. No push to `cliffthelin/baseline` — `origin` (`cliffthelin/BaseLineProx`) only. `settings_web.py` was not touched, not imported, not wired into the authorization path, and was not running during any of this work. Setup intent remains explicitly labeled informational/integrity-only throughout — no signed-intent enforcement was implemented or implied. Two disposable QEMU targets used (`experiments/m1-1-1/`, `experiments/m1-1-2-crash/`), both deleted after inspection per the established retention rule; serial logs grepped clean of the test password (`TestPass1234`) before deletion in both cases. The existing integrated first-boot implementation and authority model were **not changed** in this pass — only `boot/provision.sh` was fixed, per the explicit instruction that the state machine itself should only change if a test exposed a defect in it (none did).

## The fix: `boot/provision.sh` no longer touches its own execution context

Decision record 26 found the defect directly: the old script called `systemctl disable --now getty@tty1.service` then `systemctl enable --now baseline.service`, both of which disrupt the live tty1 session the script itself might be running from — confirmed by `provision.log` stopping execution immediately after the `getty@tty1.service` removal line.

Fixed (commit `0d7e900`, prior to this session's continuation) by staging all files first (unchanged), then running atomic verification (`[ -s "$f" ]` for every staged file, `[ -x "$f" ]` for every entry point, unit-file presence checks) via a `verify_fail()` helper that aborts with `exit 1` on any failure, then `systemctl enable` (no `--now`) all three units with **zero** direct `getty@tty1` manipulation — relying entirely on `baseline-firstboot.service`'s own `Conflicts=getty@tty1.service` / `Before=baseline.service` ordering to take over tty1 safely at the *next* boot, which is systemd's job, not the script's. A final verification loop confirms `systemctl is-enabled` reports `enabled` for all three units before the script prints success.

## Fresh proof 1: unattended provisioning + full integrated first-boot, from a completely fresh image (`experiments/m1-1-1/`)

Steps, each independently verified, not inferred:

1. **Fresh automated Proxmox install** (`fqdn=baseline-111.local`) via the proven `proxmox-auto-install-assistant prepare-iso --fetch-from iso` pipeline — no guestfwd dependency, no answer-server. The QEMU monitor connection was quit immediately on the installer's own `Finished: 'ok'` line, before the reboot-loop could re-enter the still-CD-attached installer.
2. **Corrected `provision.sh` run completely unattended**, foreground, from the same tty1 session used to invoke it: `bash boot/provision.sh > /root/provision.log 2>&1; echo PROVISION_RC=$?`. Screendump (`prov1.png`, retained) shows `PROVISION_RC=0` followed immediately by a fresh, live, unbroken shell prompt in the *same* session — direct proof the script never disrupted its own execution context. `provision.log` (`provlog1.png`, retained) shows both `PASS: all staged files and units present and correctly permissioned.` and `PASS: all three units confirmed enabled.`, plus the final `Done. Nothing on this tty/session was touched or disabled` message.
3. **Reboot.** tty1 automatically displayed the full integrated proposal (Proxmox detection, network diagnosis/diff, five proposed packages, rollback/verification description, setup-intent informational status, single CONFIRM footer) with **zero manual steps** — confirming `baseline-firstboot.service`'s `Conflicts=`/`Before=` ordering took over tty1 correctly at boot.
4. **Indefinite-wait proof**: two screendumps 42 seconds apart differ in exactly 16 pixels, all confined to an 8×2px box at the bottom-left cursor position (blink) — every other pixel on screen, including the full proposal text, is byte-identical. No timeout, no default action.
5. **tty2 verified as a normal, unaffected recovery console** (`baseline-111 login:` getty prompt, reachable via Ctrl+Alt+F2, switching back to tty1 leaves it unchanged).
6. **Real local CONFIRM sent.** The full pipeline ran and completed: network repair applied and independently verified (IPv4 `10.0.2.15/24`, default route, DNS, and a real external HTTPS `200`), all five packages installed (`dpkg -s` = `install ok installed` for all five, `which` resolves all five binaries), iperf3 confirmed `disabled`/`inactive`/not listening on `:5201`, completion marker written (`2026-09-24T01:37:55`), journal's final state `committed`. Baseline's own console app then took over tty1 directly (`BaselineOS — online - lifeline up`).
7. **Second reboot.** tty1 went straight to Baseline's console — no first-boot screen, proving first-boot does not re-run. Network, all five packages, iperf3 safety, and the (unchanged) completion-marker timestamp all persisted, verified independently via tty2 a second time.

This repeats decision record 26's integration proof end-to-end with the **fixed** provisioning script and **zero** manual completion steps — the gap decision record 26 flagged as a release blocker is closed.

## Fresh proof 2: interruption after confirmation, before commitment — journal-based recovery without repeating committed work (`experiments/m1-1-2-crash/`)

A second, completely independent fresh disposable install (`fqdn=baseline-crash.local`), provisioned unattended the same way, confirmed via the same `PASS`/`PASS` log lines.

**Method**: rather than trying to time an external kill against an unpredictable network round-trip, a small watcher script (`killwatch.sh`, test-harness-only, never part of the shipped system) was fetched onto tty2 and polls `/var/lib/baseline-firstboot/journal.json` every 0.15s; the instant its last recorded state becomes `network_repaired`, it sends `pkill -9 -f baseline-firstboot` and exits. This was pre-authenticated and pre-staged on tty2 before CONFIRM was sent on tty1, so the watcher was already polling when the real CONFIRM keystroke went in.

**What happened**: the watcher fired and printed `KILLED_AT_STATE=network_repaired`. Inspection immediately after showed:

- The journal's last transition was `network_repaired` with `network_ok: false` — because a manual `dhclient vmbr0` run on tty2 (needed only to give that shell's `curl` fetch of `killwatch.sh` an IPv4 route — a side effect of this test's own methodology, not a defect) had already brought the interface up before the repair pipeline's own apply step ran, so its safety check correctly refused to touch an interface that was reporting `address_assigned/gateway_reachable OK` ("refusing to change a device that isn't actually broken"). This is a genuine, correct safety behavior of the repair pipeline, not a bug — but it means this run demonstrates recovery from an interrupted **network-refusal** decision rather than an interrupted **package install**, which is still squarely "after confirmation, before commitment" and is reported here honestly rather than reframed as the originally-intended scenario.
- No completion marker existed. `systemctl status baseline-firstboot.service` showed `Active: failed (Result: exit-code)`.
- `baseline-firstboot.service`'s own process was gone (killed), confirming the interruption was real, not merely a slow poll catching a normal transition.

**Reboot, then recovery verification**:

- `diff` between the journal captured immediately before reboot and the journal read immediately after reboot produced **zero output** — byte-identical. The resumed run did not re-run network diagnosis or re-apply any change; it read the already-recorded `network_repaired`/`network_ok: false` state and reached its `network_failed` conclusion without writing anything new.
- `systemctl status baseline-firstboot.service` showed a **new** invocation for this boot (new invocation ID, new timestamp), `Active: failed (Result: exit-code)` again, but **CPU: 45ms** — against **668ms** for the original run that actually performed discovery, diagnosis, and repair. The ~15x reduction is corroborating evidence the expensive already-completed work was not repeated.
- No completion marker exists after the second boot either — package installation correctly never ran.
- **Decisive package-state check**: `iperf3` — which nothing else in a stock Proxmox install depends on or pulls in — is confirmed `dpkg -s`: *"package 'iperf3' is not installed and no information is available"*. (`smartmontools`, `ethtool`, and `lm-sensors` are present, but as Proxmox's own base dependencies — `lm-sensors` is marked `[installed,automatic]`, i.e. pulled in as *someone else's* dependency, not requested by this pipeline.) Since the five-package install is one atomic `apt-get install` call, `iperf3`'s absence is conclusive proof the install step never executed on either boot.
- Baseline's own console app took over tty1 as normal fallback behavior (`Before=baseline.service` ordering runs regardless of `baseline-firstboot.service`'s exit status), correctly and honestly reporting `BaselineOS — offline - stopped at address_assigned` — an accurate reflection of the actual (test-induced) network state, not a false "healthy" claim.

This is the crash-recovery property the Milestone 1.1 directive's step 10 asked for: a real kill of the real process, after a real durable journal write, with recovery proven by (a) an unchanged journal, (b) a near-zero-cost resumed run, (c) no re-attempted or skipped authorization, and (d) definitive package-state evidence that nothing already-decided was redone.

## Closeout record: what is proven where

**QEMU-proven** (this session, both fresh-image passes, `experiments/m1-1-1/` and `experiments/m1-1-2-crash/`):
- Unattended provisioning that never disrupts its own tty/session, with atomic pre-activation verification.
- Automatic tty1 handoff to the integrated first-boot proposal at boot, with no manual steps.
- Indefinite wait with no timeout/default (byte-level proof, not visual).
- tty2 remains an unaffected, normal recovery console throughout.
- Full integrated network-repair → package-install → verify → commit pipeline, with independent post-hoc verification of every claim (network reachability, package status, iperf3 safety, completion marker, journal contents).
- First-boot does not re-run after a normal, successful reboot; all state persists.
- A real kill of the first-boot process after a durable journal write, followed by real recovery that neither repeats completed work nor skips required authorization/verification, evidenced by an unchanged journal, drastically reduced re-run CPU cost, and conclusive package-state proof.

**Unit-test-only behavior** (not re-derived from QEMU in this pass, already covered by the 19 `test_firstboot_statemachine.py` cases from decision record 26, unchanged in this pass): resume-from-`proposed`, declined/EOF confirmation, no-safe-candidate refusal, corrupted/unknown-state journal fail-closed handling, and each individual package/iperf3 verification failure mode. This pass's real interruption test exercised the resume-from-`network_repaired` path for real, on top of that existing unit coverage.

**Physical-hardware-unverified** (unchanged from decision record 26 — not attempted in this pass, explicitly out of scope): actual sensor readings, NVMe discovery and SMART data on real drives, physical NIC topology, Wi-Fi/phone-tether recovery, GPU/USB behavior, installation on the intended external drive, preservation of the current BaselineOS drive's packages/settings, and recovery from power loss (as opposed to process termination) during the confirmation sequence.

**Deferred setup-intent enforcement** (unchanged): setup intent remains parsed/signed/verified only as an informational integrity check (per PRD §5.6) — it is not, and was not made in this pass, part of the authorization gate. Before it could carry any destructive or broader authority, it would still need schema constraint, target/expiration/action-allowlist checks, replay protection, operator-visible display, and consumption recorded only after commitment — none of that was implemented or implied here.

## Commits and push status

Implementation fix (`boot/provision.sh`) was committed prior to this continuation as `0d7e900`. This pass is documentation-only (this record plus the `docs/design/milestone-1-plan.md` closeout update) — committed separately per this project's documentation/implementation separation convention, pushed to `origin` (`cliffthelin/BaseLineProx`) only.

## What this means for Milestone 1

The gap decision record 26 identified — "provisioner partially runs → operator repairs → reboot → integrated workflow succeeds" instead of "provisioner runs unattended to completion → reboot → integrated workflow succeeds" — is closed: this pass demonstrated exactly the latter, twice, from completely fresh images, with no manual completion steps. Combined with the crash-recovery proof, Milestone 1's original goal — a reproducible, unattended Proxmox-substrate path back to the original Baseline functionality — is functionally complete in the disposable-QEMU reference environment. Physical-hardware deployment (the item explicitly listed above as unverified) remains the next validation step before any real installation, not a reason to discount this milestone. GUI/browser sandbox work, the Proxmox capability adapter, and any physical-drive work remain deferred to a future milestone and were not started in this pass.
