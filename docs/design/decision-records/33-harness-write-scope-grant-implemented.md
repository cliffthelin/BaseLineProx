# Decision record: the write-scope grant from decision record 32 is now implemented

Status: **implemented, unit-tested (11 new tests, 629/629 suite
passing), not yet verified against a real `claude` CLI invocation on
real hardware.** Decision record 32 is unchanged and stays the record
of the decision itself; this one documents building it, per this
project's own append-only changelog convention (a past record is never
edited, a new one supersedes it and links back).

## What was built

`baseline/lib/harness.py`:

- **`WriteGrant`** - `{scope_path, authorized_by, granted_at}`, exactly
  the shape record 32 specified. No duration field: the answer is
  always "this session," enforced by construction (see below), not by
  a value that could be set wrong.
- **`grant_write_scope(session, scope_path, *, authorized_by, now)`** -
  the only way a `WriteGrant` comes into existence. Refuses a
  `scope_path` that isn't a real, existing directory (`os.path.isdir`
  after `os.path.realpath`) - fail-closed rather than granting a
  boundary around nothing, matching `gui_brokers.file_picker`'s
  allowlist-by-construction discipline. Stores the *resolved* path, so
  a symlink or `..` in what the operator typed can't later be used to
  smuggle the grant somewhere else.
- **`revoke_write_scope(session)`** - clears the grant early, before
  the session (process) ends on its own.
- **`is_path_within_grant(session, path)`** - real containment after
  resolving symlinks/`..` on both sides, never a prefix-string
  comparison alone. False whenever there is no active grant. Nothing
  calls this yet outside its own tests - it exists now because record
  32 named it as required, and because this project's own convention
  (`repair.py`'s "nothing here trusts that proposal" boundary) is to
  never take the model's own claim about what it wrote as sufficient;
  this is the function Baseline itself would call to check a written
  path against the grant, once anything downstream needs to.
- **`HarnessSession.write_grant`** defaults to `None` on every new
  instance - a fresh session (a fresh Baseline process, per record 31)
  never inherits a grant made in a previous one, by construction of
  where the field lives, not by remembering to clear it anywhere.
- **`build_ask_argv`** now branches on `session.write_grant`: with no
  grant, behavior is byte-for-byte what it was before this record
  (`--tools ""`); with an active grant, it sends `--allowedTools
  "Write(<scope_path>/**)"` instead - and never both. This exact
  mapping is **not yet verified** against the real Claude Code CLI's
  actual permission-pattern syntax (record 32 flagged this explicitly
  as unverified); it is pinned in a unit test so a real-CLI
  verification pass has one concrete claim to confirm or correct,
  rather than an unspecified mapping nobody can check.

`baseline/bin/baseline` - the operator-facing half record 32 said
didn't exist yet:

- **`grant write <directory>`** and **`revoke write`** console
  commands (the existing Console tab's command line, alongside
  `hardware`/`network`/`tether`/`ask <question>`). Synchronous, not a
  background worker - a single `stat()` call and in-memory
  bookkeeping, not a long-running operation. The operator types the
  path; nothing infers or guesses one, per record 32's "the operator
  names the boundary" requirement.
- Confirmation output states the grant's real scope path and says
  explicitly that it ends when Baseline exits and is never remembered
  next time - the session-only property is stated to the operator at
  the moment of granting, not left implicit.

## What this still does not do

- The harness itself has no way to *ask* for a grant - there is no
  tool-calling surface for it to request one through (it has zero
  tools until a grant exists - a chicken-and-egg this record resolves
  by making the grant operator-initiated, not harness-initiated).
  Record 32's "it asks the operator" is implemented as "Baseline's own
  console asks the operator," not as the LLM soliciting one mid-
  conversation - the only shape that's actually possible given zero
  tools is the starting state.
- Nothing yet actually calls `is_path_within_grant` outside its own
  tests. It's built and correct per its own tests; wiring something to
  call it (e.g. double-checking a write Claude reports having made)
  is a real follow-up, not implied by this record.
- The `--allowedTools "Write(...)"` argv shape is unverified against
  the real CLI, as stated above and in record 32 - this is the
  concrete next verification step before this is fully closed, the
  same as record 31's own `--session-id`/`-c` mapping.

## Verification performed before this commit

- RED confirmed first: all 10 write-grant-specific tests failed with
  `AttributeError: module 'harness' has no attribute 'grant_write_scope'`
  before any implementation existed.
- 11 new unit tests, all passing, explicitly covering the negative
  cases record 32 required: a fresh session never inherits another
  session's grant; a sibling directory whose name merely starts with
  the same prefix is refused; a `scope/../outside` traversal attempt
  is refused; no grant at all means `is_path_within_grant` is always
  false; a grant for a nonexistent directory is refused outright.
- Full suite: 629/629 passing (618 before this change), no
  regressions.
- `baseline/bin/baseline` and `baseline/lib/harness.py` both
  byte-compile clean.
