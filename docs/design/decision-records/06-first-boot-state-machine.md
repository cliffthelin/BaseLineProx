# Decision record: First-boot state-machine prototype

Date: 2026-09-21
Investigator: Claude Code
Status: complete — all required properties verified directly against a real QEMU boot of the proven install pipeline

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
After `systemctl enable baseline-firstboot.service` and a real `reboot`, the guest came back with **no login prompt at all** — straight to the state machine's own output, running unattended through to `state machine run finished.` This confirms the unit's `Conflicts=getty@tty1.service` correctly took over tty1 at boot, exactly as `boot/baseline.service` already does for Baseline's normal operation.

### 3. tty2 remains a working, untouched escape console
Sent `Ctrl+Alt+F2` via the QEMU monitor (a real VT-switch keystroke, not a script) immediately after the tty1 takeover was confirmed. tty2 showed a completely ordinary, unmodified Proxmox login prompt (`m0inv3-final login:`) — nothing in the prototype's unit touches tty2, and the OS's own multi-console behavior was never disturbed.

### 4. Interrupted-run recovery
Reset state, started the state machine in the background, and sent `SIGKILL` roughly 1 second in — landing exactly at the confirmation prompt, before the prototype's 2-second auto-confirm fired. The journal file, inspected immediately after, showed `"state": "proposed"` with the full history (`created`, `discovered`, `proposed`) intact and durably written — **not** `confirmed` or beyond, confirming the fsync'd write genuinely completed before the kill, not a partial/corrupt record. Restarting the script printed `resuming from state: proposed` and continued correctly through `confirmed → applied → verified → committed` **without re-discovering or re-proposing** — it reused the exact journaled proposal rather than deriving a new one.

### 5. Completion marker prevents automatic re-trigger
Running the script again immediately after a successful commit printed `previous run already completed -- not re-triggering.` and the exact completion timestamp, then exited — no re-discovery, no re-proposal, no re-apply.

### 6. Fake, bounded firewall executor — no real policy touched
Every apply step's own logged result includes `'note': 'FAKE executor -- no real firewall rule was touched'`, and the function itself (`fake_apply_firewall`) contains no networking/firewall code of any kind — it sleeps for a fixed 1 second and returns a canned result. This is a structural guarantee (the function literally cannot touch a real firewall), not just a runtime observation.

## What this prototype deliberately does not attempt

- **Real operator interaction.** The confirmation step auto-confirms after 2 seconds, explicitly labeled `(TEST MODE ONLY)` in both the on-screen prompt and the journal's `confirmed_by` field, specifically so the full transition sequence could be exercised unattended inside this investigation's QEMU session. The PRD's real requirement — genuine local confirmation, no auto-proceed — is unchanged; this is a prototype shortcut, not a design relaxation, and is flagged as such in the code itself.
- **A real TUI.** Output is plain `print()` to the console, not a Textual interface. Whether Baseline's existing tty1 Textual infrastructure (`baseline/bin/baseline`, already a substantial 925-line real application with its own tab/modal/Console-command system) can host this state machine directly, or needs a distinct first-boot mode, was not resolved here — noted as still open below.
- **Real firewall/network/tether application.** Explicitly out of scope per instruction; the fake executor stands in for all of PRD §5.10's actual transactional apply logic, which remains to be built in Milestone 1.

## Remaining open question, carried forward

The PRD (§8.4) flagged reuse of Baseline's existing tty1 Textual TUI infrastructure as an open question for Milestone 0. This investigation used a fresh, minimal prototype instead of touching `baseline/bin/baseline` directly — the right call for a structural proof, but the reuse question itself is still unanswered and should be resolved in Milestone 1 when a real (non-auto-confirming) confirmation UI is built: either extend the existing Textual app with a first-boot mode, or build a dedicated first-boot TUI that shares its styling/conventions.

## Security implications

- The durable-journal pattern (fsync file + fsync containing directory + atomic rename) is the mechanism that made interrupted-run recovery provably correct here — this same pattern should carry directly into Milestone 1's real implementation, including for the handoff-restore transaction journal described in PRD §5.13, which needs the identical durability property.
- The completion-marker check happens as the very first action in `main()`, before any discovery or side effect — meaning even a maliciously or accidentally re-triggered service start (e.g., a second unit activation) cannot cause the state machine to redo work past what any real, safety-relevant confirmation already covered.

## Tests added

None as portable/reusable test code — this was an interactive prototype exercised by hand against a real boot, per the instruction not to build additional test matrices for this investigation. The five verified properties above are exactly the test cases Milestone 1's real implementation should carry forward as actual automated tests once it exists as production code.

## Whether Investigation 7 is unblocked

Yes. Investigation 7 (exclusive physical-device access research) is independent of the first-boot state machine and was never blocked by it.
