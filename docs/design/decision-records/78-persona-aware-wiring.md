# Decision record: persona-aware wiring for persist_bind_mounts.py, scripts_inbox.py, settings_web.py, control_panel_web.py

Status: **implemented and tested (1158/1158 suite passing, up from
1122 at the start of this pass). Not run against real hardware.**

## What this closes

Work-queue item 25: "Make persist_bind_mounts.py/settings_web.py/
scripts_inbox.py/control_panel_web.py persona-aware (switch active
persona = unmount current, authenticate, mount+rebind the
newly-authenticated one)." Flagged directly in decision record 76 as
the real follow-up once the multi-persona `USER_PERSISTENCE_<PERSONA>`
model existed in `drive_installer.py` but nothing else knew about it
yet - "each still assumes a single active persistence volume."

The queue listed this item's own blocker as "needs the
persona-selection UX decided (TUI vs web vs CLI) before wiring the
actual mount-switch call sites." Rather than stall on that (a real,
still-open decision - item 28's fuller settings-tab UI is where it
actually belongs), this pass builds the real, testable mechanism each
of the four modules needs underneath *any* future UX choice, and wires
each module only as far as its own real, current shape genuinely
requires - a pragmatic sequencing, not a resolution of the UX
question, which stays open.

## The mechanism: persist_bind_mounts.py

Added the actual persona-parameterized mount/bind machinery:
`persistence_label_for`/`persistence_mountpoint_for` (persona=None
reproduces the legacy singular `USER_PERSISTENCE` label/mountpoint
byte-for-byte - matches the real, already-deployed plain-partition
`/dev/sdb` layout, decision record 46 - a real persona name switches
to `drive_installer.py`'s own `USER_PERSISTENCE_<PERSONA>` naming
functions, reused directly rather than re-derived here).
`ensure_persistence_mounted`/`ensure_redirect`/`ensure_all_redirects`
all gained an optional `persona` keyword on the same terms - every
existing call site (`persona` omitted) is provably unaffected, since
the legacy path is now just `persona=None`'s explicit behavior, not
inferred.

New, symmetric half: `unmount_persistence`, `unmount_redirect`,
`unmount_all_redirects` (unbinds every redirect first - each is
bind-sourced from inside the persistence mount, so unmounting the
volume first would leave them dangling - then the persistence volume
itself). `get_active_persona`/`set_active_persona` read/write a small
marker at `/mnt/BASELINE/state/active_persona` - lives on the shared,
never-persona-scoped BASELINE volume by construction, so it survives
every switch.

`switch_active_persona(runner, *, to_persona, credential_ok, vg_name)`
is the real mechanism item 25 asked for. `credential_ok` is never
inferred or defaulted - a caller must have actually proven the
persistence-credential axis (matching `recovery_tiers.py`'s own
discipline) before this function will touch anything; authentication
itself stays the caller's job, this function only refuses to proceed
without a proven positive. Switching to the already-active persona is
a safe, idempotent re-ensure, not an unnecessary unmount/remount cycle.

## Why persona=None as the default, not persona="admin"

The real, currently-deployed `/dev/sdb` has plain
`USER_PERSISTENCE`/`INSTALLER_CACHE`/`SESSION_TEMP` partitions - no
persona suffix at all (decision record 46). `drive_installer.py`'s own
persona refactor (decision record 76) generates the new
`USER_PERSISTENCE_<PERSONA>` scheme for *future* installs, but
reconciling that against the *specific already-deployed* plain
partitions on the real drive is a separate, still-open architecture
question, flagged directly to the user, not decided here. Defaulting
`persist_bind_mounts.py` to the legacy label keeps this pass entirely
about software-model persona-awareness, without silently forcing that
unresolved hardware-reconciliation choice as a side effect.

## scripts_inbox.py

Added `inbox_dir_for(persona=None)` - `None` reproduces
`DEFAULT_INBOX_DIR` unchanged; a real persona name gives that
persona's own `scripts_inbox` subdirectory under its own
`USER_PERSISTENCE_<PERSONA>` mountpoint, so two personas' pushed
scripts can never collide or see each other's. Every existing CRUD
function already took `inbox_dir` as an explicit parameter, so no
other change was needed here - this was a real gap in *what path
gets passed in*, not in the CRUD logic itself.

## settings_web.py

This module's own account/settings store lives under
`/var/lib/baseline`, which `persist_bind_mounts.py` bind-mounts onto
whichever persona is currently active - so a login session's data
identity can silently change underneath it if the active persona
switches mid-session, without this module ever knowing. Added
`ActivePersonaProvider` (an injectable boundary, matching this
module's own established pattern for every other dependency) and a
`persona` field on `LoginSession`, recorded at login time when a
provider is supplied. `handle_settings_view`/`handle_settings_edit`
now refuse a session whose recorded persona no longer matches the
live active persona ("stale session - the active persona changed since
login; log in again") - closing a real correctness gap, not inventing
a persona-switcher UI (which stays open, per item 28).

Every one of these parameters defaults to `None`/unused - a caller
that never opts in (every existing call site, all pre-existing tests)
is provably unaffected. `RunnerBackedActivePersonaProvider` is the real
implementation (reuses `persist_bind_mounts.get_active_persona`
directly); `build_real_server` now accepts an optional `runner` and
wires it in for a genuinely real deployment, and `main()` passes a
real `RealRunner`. Omitting `runner` (the default) keeps this module
fully usable standalone with no persistence layer at all, unchanged.

## control_panel_web.py

Added `handle_active_persona` (reuses
`persist_bind_mounts.get_active_persona`/`persistence_mountpoint_for`
directly) and its `/api/active-persona` route. The Backup card's
target-path field used to hardcode the legacy `/mnt/USER_PERSISTENCE`
default regardless of which persona is actually active or even
mounted; its JS now fetches the real active persona's mountpoint on
page load and fills the field with that instead.

## What this does not do

Does not decide the persona-selection UX (TUI vs web vs CLI) - that
stays explicitly open, now the real blocker for item 26 (recovery mode
itself) alone rather than for this item too. Does not reconcile
`drive_installer.py`'s persona label scheme against the real
already-deployed plain-partition `/dev/sdb` layout - a separate,
still-flagged architecture question. Does not run any of this against
real hardware - `switch_active_persona`'s own tests are explicit about
a `FakeRunner`'s limits: it never updates `/proc/self/mounts` just
because a fake `mount`/`umount` command "succeeded," so the
first-transition and steady-state-success cases are tested separately,
matching this module's own pre-existing precedent for the same
limitation.

## Verification performed

- `persist_bind_mounts.py`: 49 tests (up from 28) - every pre-existing
  test passes with zero changes (proving `persona=None`'s legacy
  default is byte-identical), plus new coverage for
  `persistence_label_for`/`persistence_mountpoint_for`,
  persona-parameterized `ensure_persistence_mounted`/`ensure_redirect`/
  `ensure_all_redirects`, `unmount_persistence`/`unmount_redirect`/
  `unmount_all_redirects` (including unbind-before-unmount ordering),
  `get_active_persona`/`set_active_persona`, and `switch_active_persona`
  (credential refusal, idempotent same-persona switch, real
  unmount-then-mount command ordering, steady-state success + marker
  update, and a real unmount failure never proceeding to mount the new
  persona or update the marker).
- `scripts_inbox.py`: 3 new tests for `inbox_dir_for` (legacy default,
  per-persona paths, no collision between personas).
- `settings_web.py`: 8 new tests (login without/with a provider,
  view/edit success when persona unchanged, view/edit refusal when
  stale, no-provider callers fully unaffected even with a
  persona-bearing session, `RunnerBackedActivePersonaProvider`'s real
  default and real marker read, `build_real_server`'s runner wiring
  both ways) - real sockets opened with `bind_port=0` and explicitly
  closed, not left dangling across the suite.
- `control_panel_web.py`: 2 new tests for `handle_active_persona`
  (default, and a real marker).
- `tools/check_provision_deploys_all_imports.py`: zero gaps.
- Full suite: 1158/1158 passing, no regressions.
