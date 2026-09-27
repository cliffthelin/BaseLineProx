# Decision record: provision.sh's real missing-dependency bug found and fixed; persist_bind_mounts.py wired in

Status: **implemented and tested (961/961 suite passing). Not run
against real hardware** - same standing constraint as every other
provisioning change this session, but the bug this fixes would have
surfaced immediately on the very first real deployment attempt.

## What was found, auditing "how far can you get without stopping"

Building `persist_bind_mounts.py`'s systemd wiring required tracing
exactly what `provision.sh` actually deploys versus what the code it
deploys actually imports. That trace surfaced a real, severe,
previously-invisible defect: **`provision.sh`'s copy list has been out
of sync with the real import graph for multiple past changes this
session, not just this one.**

A small real tool (now `tools/check_provision_deploys_all_imports.py`)
parses `provision.sh`'s own copy list, resolves every bin script it
installs against the real, current `baseline/lib/*.py` import graph
(transitively - two levels deep and beyond), and diffs the two. Run
against this repo before any fix, it found **seven** real gaps:

- `config_apply.py`, `config_pipeline.py` - `firstboot_statemachine.py`
  imports `config_pipeline` at module scope (decision record 51); it
  in turn imports `config_apply`. Neither was ever added to
  `provision.sh` when that wiring landed. **This would have crashed
  `baseline-firstboot.service` with `ModuleNotFoundError` before Gate
  E ever ran at all, on any real fresh install since decision record
  51.**
- `harness_adapter.py`, `harness_registry.py`, `harness_events.py`,
  `clipboard_osc52.py`, `status_bar.py` - all real, transitive
  dependencies of `baseline/bin/baseline` (the main TUI, launched by
  `baseline.service` on every real boot) that were never added when
  those modules were introduced (decision records 43-44 and earlier
  TUI work). **This would have crashed the main console on every real
  boot.**

Both are exactly the kind of defect this project's own "full walkthrough
inventory" discipline exists to catch - a real gap between what's
claimed to work and what the code actually does, invisible because
nothing in the test suite exercised `provision.sh`'s copy list against
the current import graph.

## The fix

All seven modules added to `provision.sh`'s copy list, its
present-and-executable pre-activation verification loop, and (for the
two new bin-adjacent lib modules) documented inline with why they were
missing. `tools/check_provision_deploys_all_imports.py` is now a real,
permanent regression check - not just a one-off audit script - with
its own tests: one asserts directly against this actual repo's current
`provision.sh` that the gap is zero (the real regression guard for
this exact bug), and three more prove the checker's own logic correct
against a synthetic fixture repo, independent of this repo's state, so
this repo drifting can never accidentally make the checker's test
suite pass without the real gap actually being closed.

## persist_bind_mounts.py wired in for real

The module existed and was tested (decision record 62) but nothing
called it. Added:

- `baseline/bin/baseline-persist-bind-mounts` - the thin entry point,
  matching every other boot-invoked script's exact convention
  (`repair_additive_persist.main()`'s shape: print each result, exit 0
  only if all applied).
- `boot/baseline-persist-bind-mounts.service` - `Type=oneshot`,
  `RemainAfterExit=yes`, `After=local-fs.target` + `Requires=local-fs.target`
  (the USER_PERSISTENCE partition must be mountable before this runs),
  `Before=baseline-firstboot.service baseline.service` (neither may
  touch `/etc/baseline`, `/var/lib/baseline`, or `/var/log/baseline`
  before the redirect is in place), `WantedBy=multi-user.target` -
  deliberately the same standard, already-proven ordering shape this
  project's other real units already use (`baseline-firstboot.service`),
  not a riskier `DefaultDependencies=no`/`sysinit.target` scheme that
  can't be verified without real hardware.
- `boot/baseline-firstboot.service` and `boot/baseline.service` both
  gained the matching `After=baseline-persist-bind-mounts.service`,
  matching this project's own existing belt-and-suspenders convention
  of declaring real ordering on both sides.
- `provision.sh`: staged, enabled, and verified alongside every other
  real unit, in the same three places (copy list, `systemctl enable`
  list, present-and-executable check).
- Verified structurally with real `systemd-analyze verify` on this
  machine (filtered to just this project's own units, since verifying
  a single file also cross-checks the whole host's real, unrelated
  unit set): all three edited/new units parse cleanly with no
  ordering-cycle or syntax errors - the only complaint is the expected
  "the real binary doesn't exist on this dev machine," which is
  correct, since this machine isn't the real install target.

## What this does not do

- Not run against real hardware - `persist_bind_mounts.py`'s own real
  mount/bind-mount/fstab behavior has never executed for real,
  matching every other provisioning module this session.
- Does not re-audit whether any OTHER real gap exists beyond what the
  import-graph checker can see (e.g. a genuinely missing *system*
  package, not a local `lib/*.py` module) - scoped deliberately to the
  one real defect class this pass found and fixed.

## Verification performed

- RED confirmed first for `persist_bind_mounts.main()`.
- The import-graph checker found the real 7-module gap before any fix
  was applied - confirmed by running it directly against the
  unmodified repo state, not assumed.
- `bash -n boot/provision.sh` - syntax clean after every edit.
- Real `systemd-analyze verify` against the new and two edited unit
  files on this machine - structurally clean.
- 6 new tests for the checker tool (one against this real repo, three
  against a synthetic fixture proving two-level-deep transitive
  resolution and both the presence/absence of a gap, two for `main()`'s
  exit codes) plus 2 new tests for `persist_bind_mounts.main()`.
- Full suite: 961/961 passing (953 before this change), no
  regressions.
