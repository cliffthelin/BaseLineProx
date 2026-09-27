# Decision record: USER_PERSISTENCE self-installs locally, and real systemd enforcement of its absence

Status: **implemented and tested (1084/1084 suite passing at this
point). Not run against real hardware.**

## Direct instruction

Corrected a real design mistake directly: I had told the user "keep
both USB drives plugged in - persistence... won't work if it's not
connected at boot," which the user rejected outright: "The drives are
self installing systems... make BASELINE the first thing added into
the installer_Cache. There are no immutable volumes only reasons why
things should change or not change them... So loosen any exact match
failures." Then, sharpening the priority: "If the User Persistence is
missing it immediately become the most important aspect to resolve.
It determines everything... Without it everything only has one mode:
recovery."

## The fix, part 1: real discovery + local self-install cascade

`persist_bind_mounts.ensure_persistence_mounted` previously refused
outright the moment `mount LABEL=USER_PERSISTENCE` failed once - an
artificial hard dependency on a second physical drive being present,
not a reasoned one. Now cascades through three real steps:

1. Mount by label (unchanged, the common case once a labeled device
   exists).
2. If that fails, real discovery via `blkid -L USER_PERSISTENCE` - not
   just retrying the same mount. A labeled device found anywhere gets
   mounted **directly by device path**, never duplicated - this
   matters because self-installing a second local volume with the
   same label when one already exists elsewhere is exactly the
   same-label-two-real-volumes risk decision record 69 already found
   once for a different reason.
3. Only when nothing is found anywhere does it self-install a real,
   adaptively-sized (decision record 73) local logical volume. A
   second, dedicated persistence drive becomes an optional upgrade,
   never a requirement for the drive to be a complete, self-installing
   system on its own.

## The fix, part 2: real systemd enforcement, not just ordering

Auditing what "without it everything only has one mode: recovery"
actually requires structurally found a second real gap:
`baseline-firstboot.service`, `baseline.service`, and
`baseline-settings-web.service` (which lacked even `After=
baseline-persist-bind-mounts.service`, despite its own data store
living under `/var/lib/baseline` - itself redirected onto
USER_PERSISTENCE) all only declared `After=`, never `Requires=`.
`Before=`/`After=` order units but never block a dependent from
starting when the required unit's own `ExecStart` genuinely fails -
only `Requires=` does that for a `Type=oneshot` activation failure.
Added `Requires=baseline-persist-bind-mounts.service` to all three
(and the missing `After=` to settings-web), plus
`baseline-scripts-inbox.service` which had `After=` but not
`Requires=` either.

Now, if the discovery+local-fallback cascade above is ever genuinely
exhausted (no external device, no local free space), these dependents
do not start at all. Because `baseline.service` never starts, its own
`Conflicts=getty@tty1.service` never takes effect, so a normal login
getty remains on `tty1` - real, structural "recovery mode" access
(a plain login prompt an operator can actually use), not a
partially-broken TUI silently coming up as if nothing were wrong.

## What this does not do

- Does not yet build the fuller "Baseline Recovery mode" the user
  described - a real userless discovery mode (matching the Ubuntu
  installer's own live-environment shape), tiered guest/Proxmox-
  credential/USER_PERSISTENCE-credential access, and SESSION_TEMP as
  the scoped store for session-only recovery-mode state. That is
  real, separate, substantial work - planned next, not built in this
  pass.
- Not run against real hardware - in particular, the getty-remains-
  on-tty1 consequence of a failed `Requires=` is standard, documented
  systemd behavior, not something verified live on this repo's own
  target hardware.

## Verification performed

- 5 new tests for `discover_persistence_device` and the full
  discovery-then-local-fallback cascade, including the case where a
  discovered device is mounted directly rather than triggering a
  duplicate local create, and the case where every fallback is
  genuinely exhausted.
- `systemd-analyze verify` on all four edited units - structurally
  clean, no ordering-cycle errors (only the expected "binary not found
  on this dev machine" notes).
- Full suite: 1084/1084 passing, no regressions.
