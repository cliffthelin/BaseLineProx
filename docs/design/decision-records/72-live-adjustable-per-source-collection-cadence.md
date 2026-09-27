# Decision record: live-adjustable, per-source collection cadence

Status: **implemented and tested (1053/1053 suite passing). Per-source
gating and interval-storage logic verified against real sqlite; the
real systemd drop-in application and real `mount -o noexec` semantics
require root, unavailable in this environment - not verified live here.**

## Direct instruction

"The 30 sec cycle must be a parameter available to be set as needed as
often as needed so if a time of high concern want checking every
second until a condition changes that should be possible and it
should not change places that are not of high concern."

Three concrete requirements: (1) the interval must be a real, settable
parameter, not a hardcoded constant; (2) it must go as fast as 1s
(or faster) when needed; (3) escalating one source must never speed up
any other source.

## The real design: two honestly-separate concerns

**Per-source gating** - whether a specific source's real hardware
query even runs on a given tick - is fully scopable per source, and
lives entirely in `sensors_history.py`'s own sqlite tables:
`collection_intervals` (source -> override, absent means "use the
caller's default") and `collection_last_attempt` (when a source's
collector last actually ran, independent of whether that run produced
a recordable sample - so a source with no hardware present is still
correctly throttled instead of being re-queried every tick forever).
`sensors_collect.collect_once()` now checks each source's own due-ness
before calling its real collector at all - `_SOURCES`, one small
explicit `(name, collect_fn, flatten_fn)` table instead of four
near-identical branches.

**The outer systemd timer tick** is the one thing that genuinely
cannot be scoped per source - you cannot check a source more often
than the loop that invokes the collector at all actually runs. New
`sensors_interval_control.py` computes `required_tick_seconds` (the
minimum interval across every source, capped at the plain 30s default)
and applies it via a systemd drop-in
(`baseline-sensors-collect.timer.d/override.conf`), never by editing
the shipped `.timer` unit `provision.sh` stages. Reverts by **removing**
the drop-in entirely - not widening a number - the instant nothing
needs faster than the default, so the shipped unit's own cadence is
exactly what runs again; a true no-op (nothing overridden, no drop-in
present) never touches `systemctl` at all.

New CLI `baseline-sensors-set-interval` ties both together:
`--source nvme --seconds 1` (escalate one source), `--source nvme
--reset` (de-escalate), `--list` (see every source's current effective
interval and whether it's overridden). Every call recomputes and
applies the real required tick.

## Verified live, not just against fakes

Ran the real CLI end to end against a genuine (non-`:memory:`) sqlite
file: listed defaults, escalated `nvme` to 1s, listed the override,
reset it, listed defaults again - all real reads/writes through the
actual file, not a mock. It then correctly attempted the real
`/etc/systemd/system/...` write and failed with a genuine
`PermissionError` - the expected, correct behavior for an unprivileged
process attempting a real root-owned path, not a bug. The interval-
storage half (the actual "settable parameter" the instruction asked
for) is proven real; the outer-timer-application half's argv/content
generation is fully covered by `FakeRunner`-based tests, and its real
effect needs root, matching every other privileged operation already
in this codebase (`mount`, `lvcreate`, etc.).

Handed the user two standalone verification scripts to run themselves
with real root, outside this sandbox: (1) a real loop-mounted ext4
filesystem proving `-o noexec` genuinely blocks direct execution while
`bash script.sh` still works, and a live remount lifting the
restriction (decision record 71's own open gap, closed by verification
tooling handed over rather than skipped); (2) a throwaway systemd
timer/service pair proving a drop-in override actually changes
`OnUnitActiveSec=` live and that removing it reverts cleanly - the
exact mechanism `sensors_interval_control.py` depends on, provable
without needing a real Baseline install staged at all.

## What this does not do

- Does not attempt to auto-detect "a condition changing" to
  automatically de-escalate - that is unbounded, application-specific
  logic this module has no way to know in general. De-escalation is a
  deliberate `--reset` call, by whoever (a human or a future
  monitoring script) decided the concern is over - the same shape as
  escalation itself.
- Not run against real hardware.

## Verification performed

- `sensors_history.py`: 12 new tests for
  `get_interval`/`set_interval`/`clear_interval`/`list_intervals`/
  `get_last_attempt`/`record_attempt`.
- `sensors_collect.py`: 5 new tests proving a source is skipped when
  not yet due, recollected once its interval elapses, respects a
  real 1s override, and - the direct instruction's own core
  requirement - that escalating one source never speeds up another.
- `sensors_interval_control.py`: 9 new tests for
  `required_tick_seconds`/`dropin_content`/`apply_timer_tick`,
  including the true-no-op case (never touches `systemctl` when
  nothing needs to change) and the real-revert case (drop-in file
  removed entirely, not widened).
- A real end-to-end CLI run against a genuine sqlite file (not
  `:memory:`): list, escalate, list, reset, list - all real reads/
  writes confirmed.
- `bash -n boot/provision.sh` - clean.
- `systemd-analyze verify boot/baseline-sensors-collect.timer` -
  structurally clean (pre-existing unit, unaffected by this change).
- `tools/check_provision_deploys_all_imports.py` - zero gaps.
- Full suite: 1053/1053 passing, no regressions.
