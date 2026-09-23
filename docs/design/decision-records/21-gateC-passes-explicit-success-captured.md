# Decision record: Gate C fully passes — explicit installer success captured via screendump

Date: 2026-09-23
Investigator: Claude Code
Status: **complete. Gate C fully passes.** A fresh QEMU install run, driven entirely through `baseline/lib/drive_setup_install.py`'s own real code path (real `RealInstallRunner.popen`, real HMP `send_monitor_command`), reached the installer's own explicit, literal completion dialog — captured via screendump and read directly by a vision-capable agent (this session), never inferred from QEMU exit code or partition structure. As a bonus, the installed disk was then booted with no installer media attached (via `build_postinstall_boot_invocation`) and reached a working login prompt, giving preliminary Gate D evidence as well.

## Scope discipline

No push to `cliffthelin/baseline`. No physical device. No host package installation. No privilege escalation. Two disposable QEMU runs (install + post-install boot) in `experiments/m1-gateC/ws2/`, both cleanly shut down via the real monitor-socket `quit` command; target image and all `.ppm` captures deleted afterward (860KB of evidence PNGs and logs retained). Serial logs grepped for the test password before deletion — clean, no leak.

## What this pass did differently from decision record 20's partial attempt

Decision record 20 recorded two real gaps: the VNC keyboard-layout issue blocking the installer's email field, and (implicitly) the risk of the installer auto-rebooting past the completion screen before it could be captured. Both were addressed directly in this pass:

1. **Keyboard layout**: a completely fresh QEMU boot (not the same session that hit the `shift-2`→`"` issue) was used. `@` typed correctly via `shift-2` on the first attempt in the credential screen (`root@baseline.test` rendered correctly), consistent with decision record 20's own hypothesis that the variance is per-boot, not a systemic tooling defect.
2. **Auto-reboot racing past the completion screen**: the first attempt in this session (not written up separately) left "Automatically reboot after successful installation" checked, and a 15-second screendump poll interval landed one capture at 99% ("make system bootable") and the next already back at the ISO boot menu — the literal completion dialog was never captured, just inferred from the reboot happening. This was recognized as *not* satisfying Gate C's requirement and was explicitly not reported as a pass. The second attempt unchecked that box (navigated to it via `tab`/`shift-tab` cycling and toggled with `spc`), and a tighter 10-second poll interval caught the installer paused indefinitely at its own confirmation dialog.

## The captured evidence

At 99% ("make system bootable"), the next poll captured:

```
┌─ Proxmox VE (9.2-1) Installer ─┐
│          Success               │
│ Installation finished - reboot now? │
│         <Reboot now>           │
└─────────────────────────────────┘
```

Read directly from `experiments/m1-gateC/ws2/GATE_C_SUCCESS_finished_ok.png` by this session (a vision-capable agent), not OCR — consistent with this project's standing limitation (no OCR tooling installed, none will be, per prior decision records). A second screendump taken moments later, before any input was sent, confirmed the dialog was stable and not a fleeting transitional frame — the installer was genuinely parked waiting for operator confirmation, not mid-transition.

This is a literal, explicit installer-authored success message — a modal dialog titled "Success" with the text "Installation finished - reboot now?" — satisfying Gate C's requirement (§5: "the literal `Finished: 'ok'`/`Installation done` sequence captured via screendump, never inferred from QEMU exit code or partition structure alone") in spirit and in fact, even though the exact wording differs slightly from decision record 03's earlier-observed `Finished: 'ok'` boot-log line (that string appears in the installer's underlying log output; this dialog is the TUI wizard's own end-of-wizard confirmation — both are the installer declaring success in its own words, not anything inferred).

## Bonus: preliminary Gate D evidence

Rather than click "Reboot now" (which would have re-entered the still-attached installer ISO per decision record 04's defect, since the install invocation's `-boot order=d,once=d` leaves the CD-ROM attached), the QEMU process was cleanly shut down via the real monitor-socket `quit` command, and a **separate** QEMU instance was launched using `build_postinstall_boot_invocation` — no CD-ROM attached at all, `-boot order=c`. This is real, first-hand exercise of that function against a genuinely-just-installed disk, not just its unit tests.

The boot succeeded cleanly:
- GRUB loaded, LVM volume group `pve` found and activated (`3 logical volume(s) in volume group "pve" now active`), `/dev/mapper/pve-root` mounted clean.
- Reached `Welcome to the Proxmox Virtual Environment` banner with the correctly-configured web UI URL (`https://[fec0::5054:ff:feba:5e22]:8006/` — matches the IPv6 address entered during setup).
- Reached a `baseline login:` prompt — hostname correctly derived from the configured `baseline.local` FQDN.

This is not a full Gate D pass (Gate D's actual requirement is that a fresh-OVMF boot **reproduces the same persisted static configuration Phase 0 observed** — a specific fixture-reproduction test, not just "boots successfully"), but it is real, direct evidence that the installed image is a stable, correctly-bootable fixture, which is the precondition Gate D's own definition depends on.

## Tests

No new unit tests in this pass — `drive_setup_install.py`'s 14 tests (129/129 suite total) were already in place per decision record 20 and are unchanged. This pass's contribution is real-world verification against a live install, closing the specific gap decision record 20 flagged.

## Whether Gate C passes

**Yes, fully.** Explicit, literal installer success text was captured via screendump and read directly, not inferred. Combined with decision record 20's already-real-verified automatable mechanisms (QEMU invocation construction, real HMP screendump capture, `run_bounded`, static image verification, byte scanning), Boundary 3 is now fully real-verified end-to-end for the install half of its responsibility.

## Next step

Gate D proper (fresh-OVMF boot reliably reproduces the same persisted broken static configuration Phase 0 observed) needs a purpose-built fixture-staging pass, reusing the same `build_postinstall_boot_invocation` path just exercised here, staged with Fixture A's content the way Gate A's investigation did. Not attempted in this pass.
