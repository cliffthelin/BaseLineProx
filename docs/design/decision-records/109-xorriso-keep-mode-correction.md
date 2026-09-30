# Decision record: correction to decision record 106 - `-boot_image any keep` was wrong; `patch` is the real fix

Status: **real correction, found via a real, isolated QEMU boot test
(never trust exit code / metadata reporting alone). Confirmed working
- the corrected ISO boots all the way into the real Proxmox installer
environment. Live-verified via a real, self-triggered
`build_self_installer` retry currently in progress.**

## What this corrects

Decision record 106 chose `-boot_image any keep` after `replay` failed
with `Overlapping MBR partition entries requested`. That record was
honest about its own limits: "`keep`... completed successfully...
Actual bootability of the resulting remastered ISO is **not** verified
by this fix alone." A real, self-triggered `build_self_installer` run
reached the real QEMU install stage and hung indefinitely at SeaBIOS's
own "Booting from DVD/CD..." line - never progressing, for 5+ real
minutes, while QEMU itself stayed alive the whole time (ruled out a
crash).

## How this was actually diagnosed

Rather than keep guessing against the real drive, built a fully
isolated, disposable reproduction: a throwaway `qcow2` target image, no
real device involved, booting the *exact* real remastered ISO
(`/var/tmp/baseline-self-installer/baseline-self-installer.iso`) via
`qemu-system-x86_64 ... -nographic -serial none -monitor unix:...`,
using the new, safe `screendump`-via-monitor-socket mechanism (decision
record 108) to check progress with zero risk to the real drive.

- The **original, pre-remaster** `answer-embedded.iso` booted
  perfectly in the same isolated setup - "Welcome to the Proxmox VE
  9.2 (ISO 1) installer!", through kernel load, mounting the installer
  environment, "Starting Proxmox installation." Confirms the *source*
  ISO's own boot mechanism was never broken - only the remaster step.
- The **`keep`-mode remastered** ISO reproduced the exact same hang in
  complete isolation - conclusively the remaster step's own fault, not
  a real-hardware/timing artifact.
- The **`patch`-mode remastered** ISO (rebuilt directly against the
  same real `answer-embedded.iso` + staging tree) booted correctly -
  slower than the original (needed ~30s to show output vs. ~15s, but
  genuinely progressed), all the way through kernel load, driver
  installation, Proxmox's own installer startup, and correctly
  attempted (then correctly failed, since this isolated test had no
  network) to fetch its answer file - exactly the real installer's own
  expected behavior when nothing else is wrong.

## The real lesson

Decision record 106 noted `patch`'s own `-report_system_area`
classification changed from `grub2-mbr` to `protective-msdos-label`
and treated that as "a real, concerning signal, even if possibly just
a reporting artifact" - then chose the more conservative-*sounding*
`keep` instead. That reasoning was backwards: `keep` showed the
*identical* reclassification and still doesn't boot, while `patch`
shows the same reclassification and *does* boot. The reclassification
really was just a harmless xorriso self-detection quirk, exactly as
record 106 speculated - but only an actual boot test could tell which
mode was real bootability and which was cosmetic reassurance. Neither
xorriso's exit code nor its own system-area report is sufficient proof
of bootability for an ISO this structurally complex; only a real,
isolated QEMU boot is.

## Files changed

- `baseline/lib/iso_builder.py` - `remaster_argv`'s `-boot_image any
  keep` corrected to `patch`; both the function's own docstring and
  the module docstring rewritten with the full real story.
- `tests/unit/test_iso_builder.py` - `test_remaster_argv_shape`
  updated to expect `patch`.

## Verification performed

- Full suite: 1540/1540 (unchanged count - one existing test updated
  to match the corrected real argv).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Real, isolated, disposable QEMU boot tests** (not just unit
  tests): original ISO boots correctly; `keep`-mode ISO reproducibly
  hangs; `patch`-mode ISO boots correctly all the way into the real
  Proxmox installer environment. All disposable test images and
  screendumps deleted after verification, per this project's own
  retention discipline.
- A real, self-triggered `build_self_installer` retry with this fix
  applied was in progress at the time this record was written - the
  operator should confirm it reaches the real Proxmox installer UI
  (not just "QEMU running") via the Live install screen viewer.
