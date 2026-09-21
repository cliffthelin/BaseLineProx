# PRD: BaselineOS Drive Setup GUI v2 — full-scope bootable install + first-boot configuration

Status: draft
Owner: Cliff Thelin
Depends on: `packaging/baseline-drive-setup/` (v1, shipped as `.deb`), `baseline/lib/handoff.py`, `baseline/bin/baseline-setup-wizard`

## 1. Problem

v1 of `baseline-drive-setup` (the `.deb`, shipped this session) solved *authorization* — a GTK4 app that picks a drive and runs a privileged helper through `pkexec`, no custom sudo, no scary install commands. It does **not** solve *installation*: `qemu-install` boots the raw Proxmox ISO with `-nographic -serial mon:stdio`, which the graphical Proxmox installer cannot drive, so nothing actually completes. Everything past drive selection — a bootable Proxmox install, the five diagnostic tools, LAN-scoped Proxmox web UI, SSH/tether preconfiguration, and handoff-packet restore — is either missing or lives in a disconnected CLI tool (`baseline-setup-wizard`) the GUI never invokes.

This PRD defines what "ready to install" actually means and how to get there without regressing the two constraints already in force:

- Proxmox's web UI must be reachable from the local network only — **never** globally exposed.
- Any operation that touches partitions must be strictly scoped to a drive the user has confirmed is disposable — **never** risk a drive that might hold someone else's data.

## 2. Governing architectural principle

> "As much of the setup process as we can should be made available while a full OS is in place, not automating CLI scripts between TUI pages." — user, 2026-09-20

Concretely: the *installer* phase should be as short and standard as possible — Proxmox's own supported unattended-install mechanism (`proxmox-auto-install-assistant` + an answer file), run to completion with zero scripted keystrokes into installer TUI/ncurses screens. Everything else — SSH, tether, extra tools, web UI scoping, handoff restore — is real configuration work against a real filesystem, and belongs in a phase where a full OS (or at minimum a chrootable root filesystem) exists, driven by GUI forms and idempotent scripts, not by simulating a human clicking through installer screens.

This yields two phases with a hard boundary between them:

- **Phase 1 — Unattended install.** GUI collects the minimum the Proxmox installer itself needs. A prepared, answer-file-driven ISO installs Proxmox onto the target drive with no interaction. Ends when the installer signals completion and the target filesystem is verified mountable with a bootloader present.
- **Phase 2 — First-boot configuration.** Runs against the just-installed root filesystem (via chroot immediately after Phase 1, so the user never has to physically move the drive to see it configured) or, if the user prefers, on the new drive's actual first boot. Everything from section 4 items 3–8 lives here.

## 3. Goals / Non-goals

**Goals**
- A user with a blank or wipeable drive can go from "GUI open" to "drive boots Proxmox, configured" with no manual TUI navigation and no hand-typed shell commands.
- Every privileged action stays behind `pkexec` + the existing `.policy` file; the "show me the script" toggle from v1 is preserved and extended to Phase 2 actions.
- Every step that can destroy data has an explicit, hard-to-misclick confirmation naming the exact device and its current contents.
- Local-network-only Proxmox web UI access is the default and the *only* option this tool configures; enabling global exposure is out of scope, not just unchecked by default.

**Non-goals (this PRD)**
- No support for installing alongside an existing OS on the same disk (dual-boot). Target drive is wiped, full stop — this keeps the safety model simple and matches how both real builds (laptop, `/run/media/cane/BaseLine`) have actually been done.
- No remote/headless operation of this tool over SSH — it's a local GUI, run on a machine with the target drive physically attached.
- No support for restoring a handoff packet onto a *different* Proxmox major version than it was created on (mismatch is detected and blocked, not reconciled).

## 4. Functional requirements

### 4.1 Drive selection (extends v1)
- List block devices via `lsblk -J`, excluding the device the running OS is booted from (cross-check against `findmnt -no SOURCE /`).
- For each candidate: show size, current label/filesystem (if any), and a best-effort "looks like it has data" flag (non-empty partition table with a recognized filesystem and existing files, versus genuinely blank/unpartitioned).
- **New:** support a genuinely blank/unpartitioned drive as a valid target — v1's label-match safety check assumed a pre-labeled drive; that assumption breaks for a drive fresh out of the package. Replace it with an explicit **type-to-confirm** dialog: the user must type the exact device path (e.g. `/dev/sdc`) shown in the picker before "Authorize & Build" is enabled. This satisfies "never risk a non-disposable drive" without depending on a label that may not exist yet.

### 4.2 Phase 1: unattended, verified-bootable install
- GUI form collects only what the Proxmox installer answer file needs: hostname, initial root password (or "generate and show once"), timezone, keyboard layout, network = DHCP (static IP is a Phase 2 concern, configured against the running system, not baked into the installer).
- Helper (new `pkexec` subcommand `automated-install`) generates a TOML answer file via `proxmox-auto-install-assistant prepare-iso`, producing a self-contained unattended ISO, then boots it under QEMU with the target device passed through raw and a real display (`-vnc` or `-display gtk`, not `-nographic`) so the installer can actually run, headless-driven entirely by the answer file.
- Completion check, not a human eyeballing serial output: after QEMU exits, helper mounts the target's boot partition read-only and verifies (a) a GRUB/systemd-boot entry exists, (b) `/etc/pve` or equivalent exists on the root LV. Only on both passing does the GUI report success and unlock Phase 2.
- On failure, the GUI shows the installer's captured log and leaves the drive untouched for retry — it does not silently retry or half-apply Phase 2.

### 4.3 Five diagnostic tools
- Package list: `lm-sensors`, `nvme-cli`, `smartmontools`, `iperf3`, `ethtool` (the manifest already defined in `docs/design/current-drive-inventory-plan.md` on the `inventory/current-drive-manifest` branch — this PRD adopts it as the fixed, non-configurable set; no per-tool opt-out in v2, since the inventory tool depends on all five being present).
- Installed via `apt-get install` inside the chroot/first-boot context, not baked into the installer ISO — keeps the answer file minimal and matches the "configure with a full OS in place" principle.
- Idempotent: safe to re-run (e.g., during a handoff restore onto an already-provisioned system).

### 4.4 Proxmox web UI — local-network-only
- Default Proxmox behavior (`pveproxy` binds all interfaces) is *not* sufficient on its own — this requirement is about actively restricting reachability, not just "don't port-forward and hope."
- Implementation: enable `pve-firewall` with a datacenter-level rule allowing TCP/8006 only from the detected local subnet (derived from the DHCP-assigned interface's CIDR at first-boot time, e.g. `192.168.1.0/24`), default-deny otherwise. No rule ever references `0.0.0.0/0`.
- GUI shows the exact subnet it detected and lets the user confirm or override it before applying — never applies a guessed subnet silently.
- A "verify" step after applying: from the machine running the GUI (presumed to be on the same LAN), attempt a TCP connect to the new host's `:8006`; report success/failure. This is a real-network check, not a rule-syntax check — catches "the subnet I guessed was wrong."

### 4.5 Handoff packet restore, selectable from this GUI
- New GUI step (Phase 2): "Restore from a previous build?" with a file picker constrained to `*.gpg`/`*.tar.gpg` and a passphrase field.
- Wires directly into the existing `baseline/lib/handoff.py` (`open_packet`) rather than re-implementing anything — this GUI becomes a second caller of that module, alongside `baseline-setup-wizard`.
- Before applying: show the manifest (host label, creation timestamp, what categories of data it contains — SSH host keys, root SSH keys, `/etc/baseline`, `/var/lib/baseline`) and require an explicit "Apply" click per category, mirroring `baseline-setup-wizard`'s existing behavior of never auto-restoring `authorized_keys` without a separate explicit step.
- Wrong-passphrase and manifest-mismatch (e.g., packet built on a different Proxmox major version) are hard stops with a clear message, not a partial apply.

### 4.6 SSH preconfiguration
- Independent of handoff restore (a user may want fresh SSH setup with no previous build to restore from).
- GUI offers: paste/import a public key to seed `authorized_keys`, and a toggle for password auth (default: **disabled** once a key is present — matches standard hardening practice, not left to the user to remember to do later).
- If a handoff packet was also selected, GUI makes the ordering explicit and visible: handoff-restored keys apply first, then any keys entered in this step are appended, never silently overwritten.

### 4.7 Tether preconfiguration
- Scope: USB tethering from a phone as a network fallback path, matching how this project has actually used tethering during the laptop incident this session.
- GUI collects: interface alias (if known from a previous build's handoff packet, pre-filled from it), and whether to prefer it over the primary interface or treat it as fallback-only.
- Implementation: a udev rule + systemd-networkd profile (or NetworkManager connection profile, matching whichever the target OS is using — Proxmox base is Debian, typically NetworkManager is *not* installed by default, so this should write an `/etc/network/interfaces.d/` stanza or systemd-networkd `.network` file consistent with what `provision.sh` already assumes elsewhere in this repo — confirm against `boot/provision.sh` before implementing, don't assume).

### 4.8 "Show me the script" (extends v1)
- v1's toggle covers the Phase-1 pkexec command line. Extend it to cover every Phase-2 privileged action too — each one (tool install, firewall rule, SSH config write, tether config write, handoff restore) should be individually inspectable before it runs, not just the initial QEMU invocation.

## 5. UX flow

```
1. Welcome / drive picker
   -> select device, type-to-confirm device path
2. Handoff packet? (optional)
   -> pick .gpg file + passphrase -> show manifest -> user checks which categories to pre-seed as defaults for steps 3-7
3. Installer basics (Phase 1 form)
   -> hostname, root password, timezone, keyboard
   -> [Authorize & Install] -> pkexec -> progress screen (QEMU log, live)
   -> bootability verification -> pass/fail
4. First-boot configuration (Phase 2, only unlocked after 3 passes)
   a. Diagnostic tools — on by default, fixed list, just a progress indicator
   b. Proxmox web UI scope — detected subnet shown, confirm/edit, apply, verify (real TCP check)
   c. SSH — import key, toggle password auth, shows ordering vs. handoff-restored keys
   d. Tether — alias + fallback/preferred, pre-filled from handoff if present
   e. Handoff restore — apply remaining categories not already used as defaults in step 2
5. Summary
   -> what was applied, what was skipped, link to the full script log
```

Each step in Phase 2 is independently skippable ("not now") and independently re-runnable later — this tool should be safe to re-open against an already-configured drive without repeating destructive actions (tool install and SSH/tether config writes are idempotent; handoff restore explicitly warns before overwriting existing keys).

## 6. Security requirements

Per the standing security checklist, applied to this specific system:

- [ ] No hardcoded secrets — root passwords and passphrases are never written to disk in plaintext, never logged, never embedded in the answer-file TOML beyond what `proxmox-auto-install-assistant` itself requires (which hashes them); the GUI passes them to the helper over the `pkexec` argv/stdin boundary, not a temp file left behind.
- [ ] All GUI inputs validated before being interpolated into any shell command or config file — hostname, subnet, interface alias all get an explicit allow-list regex check before use; reject rather than shell-escape.
- [ ] No injection surface in the privileged helper — every helper subcommand takes fixed positional args (as v1 already does), never a free-form string executed as-is.
- [ ] Firewall rule generation never emits a rule wider than the confirmed local subnet — codify this as a unit test, not just a code-review note (see 7.3).
- [ ] Handoff packet decryption failures and manifest mismatches fail closed — partial-apply is explicitly a bug, not a degraded-but-usable state.
- [ ] Error messages shown in the GUI never leak passphrase or password values, even in a stack trace / "show details" panel.

## 7. Testing strategy (TDD)

Per the project's testing rules: 80% minimum coverage, unit + integration + e2e, red-green-refactor, AAA structure. This system spans Python (GUI, `handoff.py`, helper glue) and bash (the privileged helper) — apply the right harness to each.

### 7.1 Unit tests (Python, `pytest`, mirrors the existing `tests/unit/inventory_tests/` pattern — a `FakeRunner`, no real subprocess/filesystem/network access)

New `tests/unit/drive_setup_tests/`:
- `test_answer_file.py` — given a form dict, the generated TOML matches expected structure; rejects a hostname/password combination that fails validation (RED: write the rejection test before the validator exists).
- `test_firewall_rule.py` — given a detected subnet, generated `pve-firewall` rule string never contains `0.0.0.0/0`; given a malformed/oversized subnet input, generation raises rather than emitting a rule.
- `test_handoff_integration.py` — GUI's call into `handoff.open_packet` is exercised against a `FakeRunner`/temp dir exactly like the existing `handoff.py` manual test did, asserting: wrong passphrase raises, manifest mismatch raises, correct passphrase + matching manifest returns the expected category list.
- `test_ssh_key_ordering.py` — given both a handoff-restored key set and a newly pasted key, the merged `authorized_keys` output preserves handoff keys first, appends new ones, never duplicates.
- `test_device_confirmation.py` — type-to-confirm comparison is exact-match, case-sensitive, whitespace-sensitive (reject `"/dev/sdc "` against `"/dev/sdc"`).

Example shape (AAA, per `common/testing.md`):
```python
def test_firewall_rule_rejects_wildcard_subnet():
    # Arrange
    detected_subnet = "0.0.0.0/0"

    # Act / Assert
    with pytest.raises(ValueError, match="not a private subnet"):
        build_pveproxy_firewall_rule(detected_subnet)
```

### 7.2 Unit tests (bash helper, `bats` or equivalent)
- `require_confirmed_device` rejects a device whose current label doesn't match, exactly as v1 does today — regression-lock this with a test rather than relying on it having been fixed once.
- Every helper subcommand rejects a missing/malformed positional arg with a non-zero exit and no partial side effect (nothing mounted, nothing written) — test via a fake block device path and a `set -x` trace assertion that no destructive command ran before the validation failed.

### 7.3 Integration tests
- Run the full Phase 1 flow against a QEMU raw disk image (a throwaway sparse file, not a real device) end-to-end: answer-file generation -> unattended install -> bootability verification passes. This is the one place a real (virtual) install actually has to happen — budget real wall-clock time for it (Proxmox install is not instant) and run it in CI or as an explicit pre-release check, not on every commit.
- Phase 2 integration: chroot into the image produced above, apply tool install + firewall rule + SSH config, then boot the image in QEMU and assert (a) the five tools are present via SSH-less serial console check, (b) `pve-firewall status` shows the expected rule, (c) SSH with the seeded key succeeds and password auth fails.

### 7.4 E2E (GUI)
- Given GTK4 has no first-party headless test harness as convenient as Playwright, use `pytest` driving the GUI's underlying model/controller layer directly (keep GTK widget code as thin as possible, per the existing container/presentational split principle, so the controller is testable without a real display) plus one smoke test under `Xvfb` that opens the window, walks the drive picker, and confirms the "Authorize & Build" button enables only after type-to-confirm matches.

### 7.5 Coverage target
80% minimum across `baseline/lib/handoff.py`, the new answer-file/firewall-rule/ssh-merge modules, and the bash helper's validation logic (via `bats` + `kcov` or equivalent). GUI widget wiring itself is exempted from the numeric target (thin by design, covered by the one Xvfb smoke test instead) — consistent with "visual regression supplements coverage targets; it does not replace them" from the web testing rules, adapted here to "the smoke test supplements the model tests; it does not replace them."

## 8. Acceptance criteria

- A user can go from a blank drive to a booted, configured Proxmox host with zero manual keystrokes into any installer TUI screen.
- Attempting to target the currently-running OS's own drive is impossible (excluded from the picker, not just discouraged).
- Attempting to proceed on a drive with existing data requires typing the exact device path; there is no single-click destructive path.
- After setup, `:8006` is reachable from another host on the same LAN and unreachable from outside it (verified by the GUI's own check, not just asserted).
- A second run of Phase 2 against an already-configured drive changes nothing unexpected (idempotence holds for tool install, SSH, tether; handoff restore explicitly warns before touching existing keys).
- Every privileged action is visible via "show me the script" before it runs.
- All new logic in §7.1–7.3 has tests written first and passing, at ≥80% coverage on the modules listed in §7.5.

## 9. Open risks / explicit unknowns to resolve before implementation

- Whether `proxmox-auto-install-assistant` can actually be obtained/run on this non-Debian Ubuntu 26.04 desktop without a container — this was an unresolved blocker earlier this session and needs a real answer (a minimal Debian chroot/systemd-nspawn without Docker is the most likely path, but unverified) before §4.2 can be built.
- Whether Proxmox base install actually omits NetworkManager (assumed in §4.7) — confirm against a real installed system, don't assume from general Debian knowledge.
- QEMU raw-disk passthrough for the actual target device (not a throwaway image) is the one place this tool asks Claude Code's own safety classifier to allow a real block-device operation — that request should go through `pkexec` + the audited helper exactly as v1 already does, never a raw `dd`-equivalent, and should be re-confirmed with the user before first real-device use of Phase 1.
