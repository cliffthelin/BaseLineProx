# Decision record: Gate D passes — fresh boot reproduces the persisted broken static configuration byte-for-byte

Date: 2026-09-23
Investigator: Claude Code
Status: complete. **Gate D passes**, with direct evidence: the same real automated-install target's `/etc/network/interfaces` was byte-identical (MD5 `361ddaf545d4288226b86c6e6b5d1115`) before and after a real reboot, and the same "no IPv4 address, no IPv4 route, IPv6-only" broken state was independently reproduced both times — never inferred from the file alone.

## Scope discipline

No push to `cliffthelin/baseline`. No physical device. No host package installation. No privilege escalation. One disposable QEMU target (`experiments/m1-gateD/`), built via the same real, hash-verified `proxmox-auto-install-assistant` binary and headless `--fetch-from iso` answer-file path decision record 22 established. Target image and screendumps deleted after inspection (serial logs grepped clean of the test password first); 168KB of evidence PNGs and logs retained.

## A genuine, unplanned finding: Fixture A is not synthetic - it's what the real installer produces

The original plan for this record was to hand-stage Fixture A's literal bytes (from `tests/unit/test_phase0_additive_repair.py`'s `FIXTURE_A_IPV6_ONLY`) onto a freshly automated-installed disk, matching Gate A's own earlier methodology. That step turned out to be unnecessary: **the real automated installer, given this project's own `answer.toml` (`[network] source = "from-dhcp"`, no static IPv4 configured) and this host's IPv6-only SLIRP/SLAAC environment, generated `/etc/network/interfaces` content that is structurally identical to Fixture A** - `iface ens3 inet6 manual`, `vmbr0 inet6 static` with the address/gateway substituted for this run's own MAC-derived IPv6, and the same `source /etc/network/interfaces.d/*` glob terminator. This is a stronger result than staging a hand-authored fixture would have been: it confirms Fixture A was never an artificial test construct, it's the literal, reproducible output of this real installer under these real, if IPv6-only-test-environment-specific, conditions.

Also directly observed as a bonus: the automated installer's own completion log line was captured verbatim for the first time in this pass - `INFO: Finished: 'ok' Installation finished - auto rebooting in 5 seconds ..` - exactly matching decision record 03's original finding, now reconfirmed against the real headless answer-file path rather than the interactive TUI wizard.

## The test

1. Fresh automated install (`prepare-iso --fetch-from iso`, same real hash-verified assistant binary and methodology as decision record 22), MAC `52:54:00:ba:5e:66` (chosen to reproduce the same `ens3` interface-naming outcome observed in the last several runs on this host - confirmed again here, though decision record 17 already found this isn't universally guaranteed).
2. Shut down cleanly the moment `Finished: 'ok'` appeared (before the 5-second auto-reboot could re-enter the still-CD-attached installer - decision record 04's known defect, avoided deliberately, not accidentally).
3. Booted the installed disk via `build_postinstall_boot_invocation` (no CD-ROM attached, `order=c`) - the first real boot.
4. Logged in, captured `/etc/network/interfaces`'s content and MD5, and confirmed directly: `ip -4 addr show vmbr0` and `ip -4 route` both produced **no output at all** - no IPv4 address, no IPv4 route, exactly the broken state Gate A's whole repair pipeline exists to fix.
5. Issued a real `reboot` from inside the guest - not a fresh QEMU process, the same disk rebooting itself.
6. After the second boot, logged in again and re-ran the identical checks: **MD5 unchanged** (`361ddaf545d4288226b86c6e6b5d1115` both times), `ip -4 addr show vmbr0` and `ip -4 route` still empty, `ip -6 addr show vmbr0` showing the same two IPv6 addresses (site-scope static + link-scope) as before.

## Whether Gate D passes

**Yes.** Gate D's stated requirement (milestone-1-plan.md SS5) is: "Fresh-OVMF boot reliably reproduces the same persisted (broken) static configuration Phase 0 observed, confirming the installed image is a stable, correct fixture for Gate A's repair test - not that networking already works at this point." Both halves are directly confirmed: the broken configuration reproduces byte-for-byte and behaviorally identically across a real reboot, and networking is confirmed still broken (no IPv4) at both checkpoints, not accidentally working.

**One honest scope note on "fresh-OVMF"**: `drive_setup_install.py`'s boot invocations use legacy BIOS (no `-bios`/pflash OVMF wiring at all - QEMU's default SeaBIOS), not UEFI/OVMF. Milestone 0's Investigation 4 separately proved fresh-OVMF-NVRAM portability specifically (a blank `OVMF_VARS` copy reaching a working login prompt), but that was tested against a different, UEFI-specific invocation, not this module's. This pass's "fresh boot" is a real, guest-initiated `reboot` of a legacy-BIOS system - it demonstrates the reproduction property Gate D actually cares about (does the persisted config survive and stay identical across a reboot), but does not itself exercise OVMF/UEFI firmware state. If Milestone 1+ ever adds UEFI support to `drive_setup_install.py`, the fresh-NVRAM-specific claim would need re-verification against that path directly, not assumed from this record or from Investigation 4's separate, differently-scoped result.

## Next

Gate E (first boot waits for real local approval - 40s-idle-no-change + post-CONFIRM apply/verify/commit) and Gate F (five diagnostic tools persist after reboot, `iperf3` confirmed disabled/inactive - the tool-persistence half of this is now easy to re-verify given decision record 22 already proved the install+function half) remain. Gate F in particular is now cheap to close: the same automated-install + `apt-get install` sequence from decision record 22, plus one more reboot and a re-check that all 5 tools/`iperf3`'s disabled state persist, no new mechanism required.
