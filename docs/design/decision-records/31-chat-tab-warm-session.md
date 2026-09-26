# Decision record: Chat-tab harness gets a warm, per-process session ("always available, not always running")

Status: **implemented, unit-tested (8 new tests, 618/618 suite passing), not yet verified against a real `claude` CLI invocation on real hardware.**

## The distinction this closes

A cross-session review (see the "BaselineOS Design Review" dossier from
2026-09-26) surfaced that "AI should always be able to help" was being
read as two different things at once:

1. **Reachability** - how fast and friction-free it is to reach the AI
   from any surface. The user wants this maximized.
2. **Execution autonomy** - what the harness can do once invoked,
   unattended. Separately scoped (see decision record 32).

This record is entirely about (1). It changes nothing about (2):
`--tools ""` is still passed on every single call, unchanged from
before this record.

## Problem

`harness.ask()` was a single stateless call per message: `claude -p
<prompt> --tools ""`, with the full hardware+network JSON blob
rebuilt and re-sent as context on every question, and zero memory
between turns - each question started the conversation over. This is
the opposite of "available, not running": it wasn't a warm, present
assistant, it was a cold process spawned fresh each time, with no
continuity to show for it.

`docs/changelog/chat/001.md`'s 2026-09-20 entry had already scoped the
fix and picked an approach, but marked it "plan agreed, not yet
implemented": use the installed `claude` CLI's own `--session-id
<uuid>` (name a session) and `-c`/`--continue` (resume the most recent
one) flags for real multi-turn memory, without embedding a raw PTY
(rejected there for needing to carve Baseline's own key bindings out
of whatever has PTY focus - a real risk this approach avoids
entirely).

## What was built

`baseline/lib/harness.py`:

- **`HarnessSession`** - a dataclass holding one `session_id` (a
  `uuid.uuid4()` generated once) and a `started` flag. A single
  instance (`_default_session`) lives at module scope, so it's created
  once per Baseline process and reused for every `ask()` call in that
  process - it is never written to disk, never a background daemon,
  and dies the moment Baseline exits. That's the literal shape of
  "always available, not always running": present the instant you ask
  it something, gone the instant the process ends, no in-between state
  where it's doing anything on its own.
- **`build_ask_argv(full_prompt, session)`** - a pure function: the
  first call for a session returns `["claude", "-p", full_prompt,
  "--session-id", <id>, "--tools", ""]`; every later call on the same
  session returns `["claude", "-p", full_prompt, "-c", "--tools",
  ""]`. `session.started` flips to `True` right after the first
  attempt (in `ask()`'s `finally` block), even if that attempt fails -
  a session-id was already sent to the CLI on that attempt, so every
  later call should try to continue it rather than name a second new
  one.
- **`Runner`/`RealRunner`** - the same injectable-subprocess-boundary
  convention `repair.py` established (`Runner.run(argv, timeout)`,
  real calls through `RealRunner`, fakes in tests). Deliberately its
  own minimal interface rather than importing `repair.Runner` (which
  would pull in `ifnet_config`/`topology` for no functional reason,
  widening this module's dependency footprint for zero benefit) -
  matches gui_brokers' precedent of each module declaring its own
  narrow `Runner` shape.
- **`ask(prompt, *, runner=None, session=None)`** - both new
  parameters are keyword-only and default to the real runner and the
  process's one warm session, so the two existing call sites in
  `baseline/bin/baseline` (`run_console_ask`, `ask_harness`) needed no
  changes at all.

## What this deliberately does not do

- Does not add streaming (`--output-format stream-json`) or an
  `--allowedTools` visible-scope toggle - both still part of
  `chat/001.md`'s proposed shape but out of scope for this pass, which
  is scoped to session continuity only.
- Does not touch execution autonomy in any way - see decision record
  32 for that axis, decided separately and not yet implemented.
- Does not persist the session id anywhere - closing and reopening
  Baseline starts a brand new session with no memory of the last one.
  That's intentional for this pass, not an oversight; persisting
  session identity across restarts is a separate decision if ever
  wanted.

## Verification performed before this commit

- RED confirmed first: `tests/unit/test_harness.py` failed with
  `AttributeError: module 'harness' has no attribute 'Runner'` before
  any implementation existed.
- 8 new unit tests, all passing: pure `build_ask_argv` behavior for
  both the first-call and continuation cases; `ask()` genuinely names
  a new session then continues it across two calls (asserted against
  the fake runner's recorded argv, not assumed); session marked
  started even when the call fails; no-credentials path never touches
  the runner at all; nonzero exit and timeout paths both return a
  message instead of raising.
- Full suite: 618/618 passing (610 before this change), no
  regressions.
- Not yet verified: an actual `claude -p ... --session-id`/`-c` round
  trip against the real installed CLI on real hardware. The two flags'
  exact semantics are taken from `chat/001.md`'s own note that they
  were "confirmed present in the installed `claude --help`" - that
  confirmation was of the flags' existence, not of a live end-to-end
  session-continuity proof. That proof is the natural next
  verification step before calling this fully closed.
