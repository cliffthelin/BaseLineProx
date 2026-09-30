# Decision record: xorriso `-boot_image any replay` fails on the real Proxmox ISO's quadruple-hybrid boot record

Status: **real bug found live during an actual `build_self_installer`
run, fixed, and confirmed directly against the same real ISO that
failed. Not yet confirmed the resulting ISO actually boots - that's
proven downstream by the real QEMU install attempt itself, the next
real step.**

## What happened

A real `build_self_installer` attempt against `/dev/sdd` failed at the
ISO-remastering stage:

```
✗ self-contained ISO build failed at xorriso_remaster_exit_zero:
  ...
  libisofs: FAILURE : Overlapping MBR partition entries requested
  xorriso : FAILURE : Failed to prepare session write run
```

Investigated directly against the real, still-present intermediate
file (`/var/tmp/baseline-self-installer/answer-embedded.iso`, the
real answer-embedded ISO produced by the earlier `prepare-iso` stage)
rather than guessing.

## Root cause

`xorriso -report_system_area plain` on the real ISO showed a genuinely
elaborate boot record: `El Torito , MBR grub2-mbr cyl-align-off GPT
APM` - a quadruple hybrid (El Torito boot catalog for BIOS-CD boot,
MBR with real embedded GRUB2 code for legacy BIOS-HDD boot, a GPT for
UEFI boot, and an Apple Partition Map for Mac). `remaster_argv`'s
`-boot_image any replay` mode tries to fully *recompute* every one of
these partition tables from scratch to match the newly-resized image
(after the real `baseline/`+`boot/` tree gets added) - and failed for
real on this specific ISO's geometry, reporting overlapping MBR
partition entries.

## Fix

Reproduced the exact failure directly against the same real,
already-failed 1.7GB ISO in a disposable scratch location (never
touching the real workspace), then tried two real, documented
alternative `-boot_image` modes:

- `patch` (adjust the existing boot records in place rather than
  recompute them from scratch) - completed successfully, but its own
  `-report_system_area` afterward showed the MBR reclassified from
  `grub2-mbr` to a generic `protective-msdos-label` - a real,
  concerning signal, even if possibly just a reporting artifact.
- `keep` (preserve the existing boot image byte-for-byte, no
  recomputation or patching at all) - also completed successfully,
  and showed the *identical* `protective-msdos-label` reclassification
  - strongly suggesting this reclassification is a harmless xorriso
  self-detection quirk affecting its own freshly-written system area
  reporting, not something unique to either mode, and not necessarily
  a real functional difference in the actual boot code bytes.

`keep` was chosen over `patch` as the safer, more literal choice - it
makes the fewest possible changes to the existing structure (xorriso's
own description: "Keeping boot image unchanged"), rather than trying
to intelligently adjust it. Confirmed directly: with either `keep` or
`patch`, new content (`-map`'d staging directory) is genuinely present
in the resulting ISO afterward - the remaster itself works, only the
prior `replay` mode's full-recomputation approach failed on this
specific ISO's geometry.

## What's still unverified

Actual bootability of the resulting remastered ISO is **not**
verified by this fix alone - that's the same real, downstream
"screendump-verified, never assumed" proof this project already
requires for every install stage (decision record 85 and others). The
real QEMU install attempt against `/dev/sdd` is the next real step
that will actually prove whether `keep` mode produced a genuinely
bootable ISO.

## Files changed

- `baseline/lib/iso_builder.py` - `remaster_argv`'s `-boot_image any
  replay` changed to `-boot_image any keep`.
- `tests/unit/test_iso_builder.py` - `test_remaster_argv_shape`
  updated to expect `keep`.

## Verification performed

- Full suite: 1532/1532 (unchanged count - one existing test updated
  to match the new real argv, no new test added since the real
  verification here is empirical against a real ISO, not something a
  `FakeRunner`-based unit test alone can prove).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Live verification against the real, previously-failed ISO**:
  reproduced the exact `Overlapping MBR partition entries requested`
  failure directly with `replay`; confirmed both `patch` and `keep`
  complete successfully against the identical real 1.7GB file; new
  content confirmed present in the output via `xorriso -find`.
  Disposable scratch test outputs deleted after verification, per this
  project's own retention discipline.
- **Not yet verified**: the resulting remastered ISO's actual
  bootability - the operator's next real `build_self_installer` retry
  is the actual proof.
