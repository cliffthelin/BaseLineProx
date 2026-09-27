# Decision record: adaptive volume sizing - no immutable volumes, only reasons

Status: **implemented and tested (1062/1062 suite passing at this
point). Not run against real hardware.**

## Direct instruction

"So loosen any exact match failures... There are no immutable volumes
only reasons why things should change or not change them," said
directly in the context of `drive_installer.py`'s fixed
`BASELINE_VOLUMES` sizes (200G/300G/100G/50G, total 650G) refusing
outright when real free space doesn't cover them - exactly the real
state discovered on this dev machine's own `sdd`: only 16GB free in
its `pve` volume group.

## The fix

`compute_adaptive_plan(free_bytes, volumes=BASELINE_VOLUMES)`: if real
free space covers every default size, returns them unchanged; if not,
scales every volume down proportionally so they all still fit,
preserving their relative size ratios (USER_PERSISTENCE still gets
more than SESSION_TEMP even when everything is smaller), reserving a
1GiB safety margin never claimed. Returns all-zero only when truly no
usable space remains, letting the caller refuse cleanly rather than
create a zero-byte volume.

`ensure_baseline_volumes` now uses this plan instead of a single
all-or-nothing space check - the fixed defaults are a reasoned
starting point, never a hard requirement.

`adaptive_single_size_gb(free_bytes, desired_gb)` is the same logic
for a single volume, reused directly by `persist_bind_mounts.py`'s own
local-fallback path (decision record 75).

## What this does not do

Not run against real hardware - the real dev machine's actual `pve` VG
(16GB free, per live `pvs`/`vgs` inspection this session) was used as
the test fixture's own real numbers, but `ensure_baseline_volumes`
itself was never actually run against it (that VG already holds a
real Proxmox install with real VMs - not touched).

## Verification performed

- 8 new tests: `adaptive_single_size_gb` (comfortable space, tight
  space, exact-safety-margin edge, zero space) and
  `compute_adaptive_plan` (comfortable space uses defaults unchanged,
  tight space scales proportionally with ordering preserved, zero
  space returns all-zero), plus `ensure_baseline_volumes` adapting
  successfully at the real dev machine's own 16GB-free number instead
  of refusing, and still refusing cleanly at truly zero space.
- Full suite: 1062/1062 passing, no regressions - the one pre-existing
  test asserting the old "insufficient" refusal wording still passes
  unchanged, since the new zero-space detail message deliberately
  keeps that word.
