# Decision record: a "current" installer ISO, and the real BASELINE volume for app state

Status: **implemented and tested (971/971 suite passing at the time).
ISO remastering verified for real against a genuine synthetic bootable
ISO; the BASELINE volume itself never run against real hardware.**

## Direct instruction

"no focus on creating a current updated ISO... installer and drivers
in the installer_cache partition and all applications changes into the
Baseline partition." Three concrete, separately verifiable asks.

## 1. A current, self-contained installer ISO

New `baseline/lib/iso_builder.py` remasters the already-verified
Proxmox auto-install ISO (`drive_setup_answer.prepare_iso_defensively`'s
own output) with `xorriso` to also carry this repo's own
`boot/provision.sh` + `baseline/` tree at `/baseline-src`, so a fresh
install needs no separate git-clone/copy step afterward.

`-boot_image any replay` is the real safety property: it copies the
source ISO's own, already-working El Torito boot record onto the new
ISO unchanged rather than rebuilding one from scratch - verified
directly (not assumed) against a real, synthetic bootable ISO built
with real xorriso before writing any code: the remastered output kept
the original `boot.catalog` and boot file, and independently confirmed
`provision.sh` landing inside the new ISO via a second `xorriso -find`
call. The same real check runs as a build postcondition, not just a
one-off manual proof - `build_current_iso` never trusts xorriso's own
exit code alone (matching `prepare_iso_defensively`'s own standing
discipline), checking exit code, output existence, a size floor, and
the independent `-find` verification.

`baseline-build-iso` defaults its output onto the real INSTALLER_CACHE
partition - the installer media belongs there, alongside cached driver
packages, not on USER_PERSISTENCE or the disposable substrate.

## 2. Drivers in INSTALLER_CACHE

No real driver-detection/download backend exists in this codebase to
hook a cache into - the earlier configurator artifact's driver-CRUD UI
was fully removed this session per direct instruction ("ABSOLUTELY
NOTHING SHOULD BE ADDED AND NOT WIRED IN"). Building a cache directory
with no real producer or consumer would be speculative, not real - not
done in this pass. The one concrete, real piece that exists today (the
ISO itself) is wired to INSTALLER_CACHE; a driver cache is deferred
until there is a real driver-management mechanism to attach it to.

## 3. The real BASELINE volume for app/VM/LXC state

`drive_installer.py`'s own module docstring named
`BASELINE/USER_PERSISTENCE/INSTALLER_CACHE/SESSION_TEMP` from the
start, but `BASELINE_VOLUMES` only ever created the other three - a
real, latent gap the docstring itself exposed, not a hypothetical one.
Given a direct choice between "app state lives on the disposable
substrate" and "a new, real BASELINE volume," the answer was the
latter: a fourth 200G logical volume (`baseline_app_state`, label
`BASELINE`, `/mnt/BASELINE`) - persistent but scoped to app/VM/LXC
state specifically, separate from USER_PERSISTENCE (credentials/
config/logs, meant to survive a reinstall) and from the disposable
substrate itself (Proxmox's own root LV, wiped by any fresh install).

`ensure_baseline_volumes`/`detect_existing_baseline_install` and
`backup_restore.all_persistence_targets()` all generically iterate
`BASELINE_VOLUMES`, so they picked up the new volume automatically -
one pre-existing test's hardcoded three-target set was the only real
fallout.

## Partition architecture question, addressed directly

Asked whether "all on one partition" made sense versus separate
containers per role for permissions/updates/access-restriction/
telemetry. Direct finding: the four volumes were never "one
partition" - each is already a separate LVM logical volume (separate
filesystem, label, mountpoint, size cap), which already gives
whole-container replace semantics, per-mount permission restriction,
and per-volume telemetry potential. What is genuinely shared is the
physical drive and volume group - real GPT partitions on the same
drive would lose LVM's flexible resizing and reintroduce the exact
partition-table-editing risk decision records 46-49 already avoided,
without buying any additional fault isolation (still one physical
device); true physical fault isolation would need more drives than are
currently available (two spare NVMe drives total, not four-plus).
Confirmed direction: keep the current per-role LVM volumes, with
per-mount permission restrictions and per-volume telemetry as real
follow-up work (not yet built).

## Verification performed

- `iso_builder.py`: RED-then-GREEN unit tests (fake runner), then a
  real smoke test - built a genuine synthetic bootable ISO with real
  xorriso, remastered it with this repo's own 236 real `boot/`+
  `baseline/` files via the actual module code and the CLI wrapper,
  independently confirmed `provision.sh` landed inside the output via
  a second real `xorriso -find` call.
- `drive_installer.py`: existing tests updated for four volumes
  instead of three; full suite green.
- Full suite: 971/971 passing at this point, no regressions.
