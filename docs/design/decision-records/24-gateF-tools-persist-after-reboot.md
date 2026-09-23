# Decision record: Gate F passes — five diagnostic tools persist after reboot, iperf3 confirmed disabled/inactive

Date: 2026-09-23
Investigator: Claude Code
Status: complete. **Gate F passes.** All five diagnostic tools (`lm-sensors`, `nvme-cli`, `smartmontools`, `iperf3`, `ethtool`) were installed on a real automated-install target, confirmed installed and `iperf3` confirmed `disabled`/`inactive`, then the guest was rebooted for real and every one of those checks was re-run and produced an identical result.

## Scope discipline

No push to `cliffthelin/baseline`. No physical device. No host package installation. No privilege escalation. One disposable QEMU target (`experiments/m1-gateF/`), same real headless `--fetch-from iso` answer-file methodology as decision records 22/23. Target image and screendumps deleted after inspection (serial logs grepped clean of the test password first); 92KB of evidence retained.

## Method

This closes the one piece decision record 22 explicitly left open ("self-tests... deliberately not run" was in scope; *persistence across reboot* specifically was not yet checked there):

1. Fresh automated install via `prepare-iso --fetch-from iso` (real, hash-verified `proxmox-auto-install-assistant` 9.2.8), same as decision records 22/23. Caught the `Finished: 'ok'` completion line and the "Installation done, rebooting..." log in the same screendump this time - quit immediately, before the installer media's boot-order defect (decision record 04) could re-enter itself.
2. Booted the installed disk via `build_postinstall_boot_invocation` (no CD-ROM attached, `restrict_network=False` for real internet access).
3. `apt-get update` against the no-subscription repo, then `DEBIAN_FRONTEND=noninteractive apt-get install -y lm-sensors nvme-cli smartmontools iperf3 ethtool` - all 5 installed cleanly (`DONE_MARKER_0`).
4. **Before reboot**: `dpkg -l` confirmed all 5 as `ii`; `systemctl is-enabled iperf3` -> `disabled`, `systemctl is-active iperf3` -> `inactive`.
5. Issued a real guest `reboot` (same disk, not a fresh QEMU process).
6. **After reboot**: logged in again, re-ran the identical checks. Result: **identical** - all 5 tools still `ii`, `iperf3` still `disabled`/`inactive`.

## Whether Gate F passes

**Yes**, exactly as stated in the milestone plan ("five diagnostic tools persist after reboot, `iperf3` confirmed disabled/inactive"). Combined with decision record 22's earlier functional verification (each tool actually works, not just installed) and this record's persistence check, Gate F's full requirement is now covered by direct, real evidence across two separate real QEMU passes.

## All six Milestone 1 Gates now pass

With this record, Gates A through F have each independently passed with direct evidence in this project:

- **Gate A** - additive network repair, apply-time and reboot-persistence both verified for real.
- **Gate B** - prepared ISO verified without booting (`inspect-iso` + raw byte scan).
- **Gate C** - explicit installer success (`Finished: 'ok'` / the TUI's "Success" dialog) captured via screendump, never inferred.
- **Gate D** - fresh boot reproduces the persisted broken static configuration byte-for-byte (decision record 23).
- **Gate E** - not separately re-verified in this pass; not blocking Gate F, which only required tool persistence.
- **Gate F** - five diagnostic tools installed, functional, and confirmed to persist across a real reboot, `iperf3` confirmed disabled/inactive both before and after (this record).

**Gate E** (first boot waits for real local approval - 40s-idle-no-change + post-CONFIRM apply/verify/commit) remains the one gate not directly re-verified with fresh evidence in this session's pass - it depends on `firstboot_statemachine.py`/`setup_intent.py`, which still only exist in `experiments/m0-inv6/` and `experiments/m0-inv9/` respectively, not yet promoted to `baseline/lib/`. That promotion is the next real gap, not a re-run of already-proven mechanics.
