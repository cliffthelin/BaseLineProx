# Decision record: First-boot state-machine prototype

Date: 2026-09-21
Investigator: Claude Code
Status: complete, including a correction. The original version of this record contained a real authorization-boundary defect (auto-approval), caught in review and fixed. See the Addendum for the corrected behavior and its own direct evidence; the original sections below are left in place, with the defect marked, for auditability.

## Scope

Per the milestone plan: exercised only inside a QEMU Proxmox installation, no real firewall applied (fake bounded executor stands in), confirm tty1 ownership, tty2 escape, discovery-before-authorization ordering, interrupted-run recovery, and completion-marker behavior.

## What was built

`experiments/m0-inv6/firstboot_statemachine.py` — a prototype, not production code. States: `created → discovered → proposed → confirmed → applied → verified → committed`. Every transition is written durably (`fsync` on the file and its containing directory, atomic rename via `os.replace`) before the next stage begins. `experiments/m0-inv6/baseline-firstboot.service` — a systemd unit mirroring the exact tty1-ownership pattern already proven in this repo's `boot/baseline.service` (`Conflicts=getty@tty1.service`, `TTYPath=/dev/tty1`, `TTYReset`/`TTYVHangup`), touching nothing related to tty2.

## Deployment method — corrected mid-investigation

Initial attempts used the network path proven in Investigations 3–5 (HTTP fetch over a `guestfwd` tunnel). It repeatedly hung — confirmed via direct host-side testing that the relay server itself was healthy, and via `curl -v` inside the guest showing the request was sent but no response ever returned. Root cause: my relay used Python's single-threaded `http.server.HTTPServer`, and an earlier interrupted connection (from a `Ctrl-C`'d attempt) left it blocked servicing a stale connection, queuing all subsequent requests indefinitely. Switching to `ThreadingHTTPServer` didn't fully resolve it either within the time budget, so the deployment method was changed rather than debugged further: a **read-only QEMU vvfat drive** (`-drive file=fat:ro:<host-dir>,format=raw,readonly=on`), which exposes a host directory to the guest as an ordinary FAT-formatted block device — no network, no HTTP, no `guestfwd` involved at all. The guest mounted it (`mount -o ro /dev/vdb1 /mnt/payload`) and copied the two files directly. This is simpler and more reliable for one-time file injection than the network path, and is noted here as a better default for any future investigation that just needs to get a handful of files into a guest without exercising the network stack.

A second, smaller correction along the way: the login credential typed via QEMU monitor `sendkey` injection must be given generous settle time between the username and password prompts (found empirically — rapid-fire keystroke batches without enough delay caused the password string to occasionally land on the wrong prompt, visible as it appearing as a new *username* after a spurious "Login incorrect"). Slowing the per-key delay and waiting 2.5s+ between username and password resolved it reliably.

## Verified properties, each with direct evidence

### 1. Discovery before authorization — always, never the reverse
Every run's own log output shows the fixed order: `discovering facts (read-only, no prompt yet)...` → `discovered: {...}` → `PROPOSED action: {...}` → the confirmation prompt. This is enforced by the code's state-machine structure itself (the `proposed` transition can only be reached from `discovered`, which can only be reached from `created`) — not just an accident of this run's ordering.

### 2. tty1 ownership
After `systemctl enable baseline-firstboot.service` and a real `reboot`, the guest came back with **no login prompt at all** — straight to the state machine's own output, confirming the unit's `Conflicts=getty@tty1.service` correctly took over tty1 at boot, exactly as `boot/baseline.service` already does for Baseline's normal operation. **Correction**: the original text here continued "...running unattended through to `state machine run finished.`" — true of this original run, but only because that run's confirmation step **auto-approved itself**, which is the defect corrected in the Addendum below. tty1 ownership itself is real and unaffected by that defect; the claim of unattended completion was the problem, not the tty1 takeover.

### 3. tty2 remains a working, untouched escape console
Sent `Ctrl+Alt+F2` via the QEMU monitor (a real VT-switch keystroke, not a script) immediately after the tty1 takeover was confirmed. tty2 showed a completely ordinary, unmodified Proxmox login prompt (`m0inv3-final login:`) — nothing in the prototype's unit touches tty2, and the OS's own multi-console behavior was never disturbed.

### 4. Interrupted-run recovery
Reset state, started the state machine in the background, and sent `SIGKILL` roughly 1 second in — landing exactly at the confirmation prompt, before the prototype's 2-second auto-confirm fired. The journal file, inspected immediately after, showed `"state": "proposed"` with the full history (`created`, `discovered`, `proposed`) intact and durably written — **not** `confirmed` or beyond, confirming the fsync'd write genuinely completed before the kill, not a partial/corrupt record. Restarting the script printed `resuming from state: proposed` and continued correctly through `confirmed → applied → verified → committed` **without re-discovering or re-proposing** — it reused the exact journaled proposal rather than deriving a new one.

### 5. Completion marker prevents automatic re-trigger
Running the script again immediately after a successful commit printed `previous run already completed -- not re-triggering.` and the exact completion timestamp, then exited — no re-discovery, no re-proposal, no re-apply.

### 6. Fake, bounded firewall executor — no real policy touched
Every apply step's own logged result includes `'note': 'FAKE executor -- no real firewall rule was touched'`, and the function itself (`fake_apply_firewall`) contains no networking/firewall code of any kind — it sleeps for a fixed 1 second and returns a canned result. This is a structural guarantee (the function literally cannot touch a real firewall), not just a runtime observation.

## What this prototype deliberately does not attempt

- **A real TUI.** Output is plain `print()` to the console, not a Textual interface. Whether Baseline's existing tty1 Textual infrastructure (`baseline/bin/baseline`, already a substantial 925-line real application with its own tab/modal/Console-command system) can host this state machine directly, or needs a distinct first-boot mode, was not resolved here — noted as still open below.
- **Real firewall/network/tether application.** Explicitly out of scope per instruction; the fake executor stands in for all of PRD §5.10's actual transactional apply logic, which remains to be built in Milestone 1.

## Remaining open question, carried forward

The PRD (§8.4) flagged reuse of Baseline's existing tty1 Textual TUI infrastructure as an open question for Milestone 0. This investigation used a fresh, minimal prototype instead of touching `baseline/bin/baseline` directly — the right call for a structural proof, but the reuse question itself is still unanswered and should be resolved in Milestone 1 when a real confirmation UI is built: either extend the existing Textual app with a first-boot mode, or build a dedicated first-boot TUI that shares its styling/conventions.

---

## Addendum: authorization-boundary correction (same day, follow-up)

### The defect

The original prototype's confirmation step auto-approved itself after a 2-second sleep, labeled `(TEST MODE ONLY)` in the code and this record. On review, that label doesn't neutralize the defect it describes: **a first-boot pipeline that can auto-approve itself under any condition — test mode, a flag, a timeout — is not proving the authorization boundary the PRD requires, it's demonstrating exactly the failure mode that boundary exists to prevent.** Discovery may run unattended; consequential configuration must stop for a real, human, local keystroke, unconditionally. The original run's own log line — "running unattended through to `state machine run finished`" — is a direct description of that boundary collapsing, not a success worth recording as one.

### The fix

`firstboot_statemachine.py`'s `proposed` handling was rewritten. The `time.sleep(2)` auto-confirm and its `(TEST MODE ONLY)` journal entry were deleted outright, not merely disabled. The replacement blocks indefinitely on `sys.stdin.readline()`, looping until the literal string `CONFIRM` is received; an EOF on stdin (e.g. a closed tty) is explicitly **not** treated as confirmation — the loop keeps waiting rather than proceeding. There is no timeout, no default branch, and no code path that reaches `confirmed` other than that exact input.

### Test performed — fresh disposable overlay, new credential, never reused

A new image was generated via the same proven pipeline (`run_final.sh`), with a freshly generated one-time credential retained only long enough to complete this test. **That credential is now compromised by definition** (it was displayed on screen and typed via recorded keystrokes) and has been purged: the overlay/target image, the prepared ISO, and the plaintext credential file were all deleted after this test, and a repository-wide search confirms the credential string no longer exists anywhere under `experiments/`. It will not be reused for any future test.

Sequence, each step confirmed by direct evidence:

1. **Boot into the tty1 state machine** — `systemctl enable` + real `reboot`; no login prompt appeared, confirming tty1 takeover as before.
2. **Discovery ran automatically** — the same fixed log ordering (`discovering facts...` → `discovered: {...}` → `PROPOSED action: {...}`) appeared with no input from the operator.
3. **Discovered facts and proposed action displayed** — the full JSON proposal, identical in shape to the original run.
4. **Stopped indefinitely at the authorization prompt** — the new prompt text reads exactly `Type CONFIRM and press Enter to proceed. No timeout. No default.` A screenshot was captured (`waiting_proof.png`), then **40 seconds passed with zero input of any kind**, and a second screenshot was captured — byte-for-byte identical to the first. No progression, no timeout firing, no default branch taken.
5. **tty2 confirmed reachable while tty1 waited** — sent a real `Ctrl+Alt+F2` VT-switch via the QEMU monitor; tty2 showed a completely ordinary, unmodified `m0inv3-final login:` prompt. Switched back with `Ctrl+Alt+F1`; tty1 was still at the identical, un-advanced authorization prompt — the tty2 excursion had no effect on tty1's blocked state.
6. **Returned to tty1 and typed the real local confirmation** — the literal text `CONFIRM` followed by Enter, via the same keystroke-injection mechanism used throughout this investigation (a real keyboard event delivered to the console, not a program-level shortcut).
7. **Only then did the fake executor run** — `applying (FAKE executor)...` → `apply result: {...'note': 'FAKE executor -- no real firewall rule was touched'...}` → `verified: True` → `COMMITTED. Marker written -- will not re-run automatically.` → `state machine run finished.`, all appearing only after step 6's keystroke, in the same order as the original (uncorrected) run — confirming the fix changed only *when* the authorization gate opens, not the transition logic downstream of it.

Two screenshots were captured as required: one during the indefinite wait (`waiting_proof.png`, confirmed unchanged after 40 seconds of no input) and one after explicit authorization (`confirmed.png`, showing the full apply/verify/commit sequence that only began once `CONFIRM` was typed).

### vvfat attachment — confirmed explicitly read-only

Beyond the QEMU-level `readonly=on` drive flag (present in the launch command throughout this investigation), the guest's own kernel-reported mount flags were checked directly this round: `cat /proc/mounts | grep vdb1` showed `/dev/vdb1 /mnt/payload vfat ro,relatime,...` — the `ro` flag is confirmed at the point where it actually matters (what the guest's kernel believes about the mount), not just inferred from the host-side command that requested it. This vvfat mechanism is explicitly a **test-only file-injection convenience** for this investigation — it is not, and should not be read as, any part of the setup-intent delivery design described in PRD §5.6, which uses a signed bundle over a different mechanism entirely.

### Whether the rest of Investigation 6 needed re-verification

No. tty1 ownership, tty2 escape, the durable journal, interruption recovery, and the fake executor's structural inability to touch a real firewall were all re-observed identically during this corrected run (steps 1–7 above exercise all of them again, incidentally) — none of those properties depended on the auto-confirm defect, and none needed a separate re-test beyond what this narrow confirmation test already re-covered.

### IPv6-only DHCP finding — scope correction

Per review: the IPv6-only `from-dhcp` result documented in Investigation 5 (and encountered again in this investigation's own setup, requiring the same manual IPv4 workaround each time) is an **observed behavior of this specific QEMU/SLIRP/installer combination**, not a general claim about Proxmox VE's `from-dhcp` handling on real hardware or under a different hypervisor's DHCP server. It should be carried into Milestone 1 as "reproduced consistently under QEMU SLIRP, unconfirmed against a physical DHCP server," not generalized further than that.

## Security implications

- The durable-journal pattern (fsync file + fsync containing directory + atomic rename) is the mechanism that made interrupted-run recovery provably correct here — this same pattern should carry directly into Milestone 1's real implementation, including for the handoff-restore transaction journal described in PRD §5.13, which needs the identical durability property.
- The completion-marker check happens as the very first action in `main()`, before any discovery or side effect — meaning even a maliciously or accidentally re-triggered service start (e.g., a second unit activation) cannot cause the state machine to redo work past what any real, safety-relevant confirmation already covered.

## Tests added

None as portable/reusable test code — this was an interactive prototype exercised by hand against a real boot, per the instruction not to build additional test matrices for this investigation. The five verified properties above are exactly the test cases Milestone 1's real implementation should carry forward as actual automated tests once it exists as production code.

## Whether Investigation 7 is unblocked

Yes. Investigation 7 (exclusive physical-device access research) is independent of the first-boot state machine and was never blocked by it.
