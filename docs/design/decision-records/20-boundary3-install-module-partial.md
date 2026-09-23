# Decision record: Boundary 3 (`drive_setup_install.py`) promoted and partially real-verified — Gate C not yet fully attempted

Date: 2026-09-22
Investigator: Claude Code
Status: **partial.** `baseline/lib/drive_setup_install.py` is written, unit-tested (14 new tests, 129/129 total), and its core automatable mechanisms are real-verified: real QEMU launch via the promoted `build_sparse_install_invocation`, real monitor-socket HMP `screendump` commands sent and successfully captured. **The literal `Finished: 'ok'` completion-text capture — Gate C's actual stated requirement — was not re-completed in this pass**, for an honest, specific reason recorded below. Gate C does not yet fully pass.

## Scope discipline

No push to `cliffthelin/baseline`. No physical device. No host package installation (in particular: OCR tooling like `tesseract-ocr` was considered and deliberately not installed - see below). No privilege escalation. One disposable QEMU workspace (`experiments/m1-gateC/ws`), target image deleted, evidence screendumps retained (184KB).

## What was built

`baseline/lib/drive_setup_install.py`:

- `build_sparse_install_invocation` / `build_postinstall_boot_invocation` - pure QEMU-argv construction, reproducing decision record 03's accepted design exactly: sparse-file-only target, no other drives, no host block-device paths, `guestfwd`/`restrict`-isolated networking. The install invocation uses `-boot order=d,once=d` (CD-ROM first, but only once); the post-install invocation attaches **no CD-ROM at all**, directly encoding decision record 04's confirmed defect (installer media left first in boot order can silently re-enter itself against an already-installed disk) as a structural property of the function, not a runtime flag someone has to remember to set.
- `capture_screendumps` - periodic screendump via a real HMP client over the QEMU monitor socket, matching decision record 03's own established mechanism (serial-only monitoring confirmed not viable for this installer - its diagnostic output goes to the VGA console, not the serial port).
- `run_bounded` - kills the whole process group on timeout, not just the parent, matching decision record 02/03's `_run_bounded` pattern.
- `verify_image_structure` - `fdisk -l` / `blkid -p` against the raw image file, never a loop device or mount.
- `scan_for_forbidden_bytes` - streamed, chunked byte scan for credential canaries in a multi-GB image, with correct handling of a canary straddling a chunk boundary (directly unit-tested).
- `CompletionCheck` / `COMPLETION_MESSAGE_SUBSTRING = "Finished: 'ok'"` - a typed result for the literal-text check, with an honestly-documented limitation (below), not a false claim of full automation.

## The honest limitation: why "Finished: 'ok'" was not re-captured this pass

Decision record 03 already established, with direct evidence, that the installer's own completion message is the literal text `Finished: 'ok'` (specifically: `INFO: Finished: 'ok' Installation finished - auto rebooting in N seconds ..`), read from a captured screendump. That verification was done by a vision-capable agent (Claude Code) reading the rendered console text in the image directly - **not by OCR**. No OCR tooling (`tesseract-ocr`, `pytesseract`) is installed on this host; `libtesseract5` (the shared library only, no CLI binary, no Python binding) is present as an unrelated dependency of something else, confirmed via `apt list --installed` and `which tesseract` (not found). Installing OCR tooling was considered and **deliberately not done** - it would be a host package install, out of scope per this project's standing constraints without the user's explicit authorization.

This pass attempted a real, fresh install run specifically to re-capture this message through the newly-promoted module's own real code path. It hit an unrelated, real operational obstacle: the VNC-keystroke test-harness tooling (`vnc_type.py`, explicitly designated test-harness-only in the PRD's §6, never shipped in `baseline/lib`) could not reliably produce a literal `@` character on this particular QEMU boot's guest keyboard state - `shift-2` (the normal US-layout mapping this project's tooling has used successfully many times earlier tonight) produced `"` instead, and several other plausible alternate key combinations (`shift-apostrophe`, `altgr-2`, `altgr-q`) either produced wrong characters or silently no-op'd. This blocked the installer's own email-address field validation (`user@domain.tld` shape required) from being satisfiable, which blocked completing the interactive wizard far enough to reach the completion screen at all.

**This is a keyboard-layout/tooling-state issue in test infrastructure, not a defect in `drive_setup_install.py` itself** - the same finding as decision record 17's earlier note that this host's per-boot QEMU/keyboard/interface-naming state is not fully deterministic (interface names varying between `ens3`/`nic0` across otherwise-identical boots; here, apparent keyboard-layout variance across boots as well, despite an unchanged "U.S. English" locale selection each time). Rather than keep escalating workarounds against a test-tooling problem, the interactive run was stopped and cleaned up, and this is reported plainly as an incomplete verification pass - not silently worked around, not claimed as done when it wasn't.

## What was real-verified in this pass

- `build_sparse_install_invocation` produced a real, valid QEMU argv; `RealInstallRunner.popen` launched it for real (confirmed via `ps aux` - the process survived detached from the launching Python script, correct `start_new_session=True` behavior).
- `send_monitor_command`'s real HMP client (a genuine gap in the first draft - the class shipped with `raise NotImplementedError` for this method until fixed in this same pass) was implemented and **used for real, repeatedly** - `screendump` commands were sent over the real monitor socket for 13 separate captures across the session, every one of which produced a valid, readable PPM→PNG image (confirmed by directly viewing each one: GRUB menu, EULA, disk selection, locale, and the password/email screen through its many edit attempts). This is the actual mechanism `capture_screendumps` wraps, now confirmed working end-to-end against a real QEMU process, not just `FakeInstallProcess` in the unit tests.
- No credential material, no host state change, no partial/corrupt disk image left behind - retention policy applied (target image deleted; only small evidence PNGs and a serial log kept, 184KB total).

## Tests added

`tests/unit/test_drive_setup_install.py`, 14 tests: QEMU invocation boots CD-ROM first exactly once and only once (`once=d`); uses only the sparse target and the prepared ISO, no other drives; SLIRP-restricted networking by default with the correct MAC; the post-install invocation never attaches a CD-ROM at all (direct test of decision record 04's fix); sparse target creation goes through the runner, not the real filesystem; screendump capture stops when the process exits and respects a `max_captures` bound; capture timestamps are monotonically increasing; `run_bounded` returns the real exit code on a normal exit and kills the process group on a timeout; image-structure verification uses `fdisk`/`blkid` and never `mount`/`losetup`; the forbidden-byte scanner finds a canary in a real file, correctly catches one straddling a chunk boundary, and handles an empty file.

## Whether Gate C passes

**No, not yet.** The automatable mechanisms this boundary is actually responsible for are real-verified. The literal-completion-text capture that is Gate C's stated requirement was not re-completed in this pass, for the specific, honestly-recorded reason above - a test-tooling keyboard-layout issue, not a code defect, and not something to route around by lowering the bar or inferring success from anything else (partition structure, QEMU exit code) instead, which is exactly what Gate C exists to prevent.

## Recommended next step, not attempted here

Retry the same real run with either (a) a from-scratch, freshly-booted QEMU instance in case this keyboard-layout variance is itself non-deterministic per-boot (plausible, given `ens3`/`nic0` interface naming showed the same pattern) and a fresh attempt succeeds without further changes, or (b) sidestep the email field's `@`-character requirement entirely by using the **automated** install path once decision record 16's guestfwd blocker is resolved (a prepared, answer-file-embedded ISO needs no interactive keystroke input at all, and was the originally-intended path for this exact boundary).
