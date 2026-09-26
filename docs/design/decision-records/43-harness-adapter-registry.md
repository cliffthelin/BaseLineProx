# Decision record: a real HarnessAdapter contract + registry, replacing hardcoded dispatch

Status: **implemented, unit-tested (10 new tests, 707/707 suite
passing), not yet verified live on a real boot.**

## The actual problem, stated precisely

Item 5 of `docs/design/v0.1-work-queue.md` asked for the harness-
adapter work to be modular. Auditing `bin/baseline` against that
standard found it genuinely wasn't: every Chat/Console-tab handler
(`ask_harness`, `run_console_ask`, `run_console_grant_write`,
`run_console_revoke_write`, `_refresh_harness_status`) hardcoded
`import harness` and called its functions directly - `self
.current_harness` (the dropdown's own selected value) had **no effect
on which module actually ran**, because only one module (`harness.py`,
the Claude Code adapter) existed to run at all. Adding a second real
adapter would have meant either duplicating every one of those five
call sites with an `if/elif` per harness, or writing this registry
first. Building stub adapters for OpenCode/Hermes/Pi/DeepSeek/GrokBot
without fixing this first would have been building on the same
un-modular foundation the request was asking to correct.

## What was built

- **`baseline/lib/harness_adapter.py`** - the contract, stated as
  documentation plus one runtime check (`conforms`), matching this
  project's existing convention (`repair.py`'s `Runner`, `harness.py`'s
  own `Runner`) of plain duck-typed contracts with `NotImplementedError`
  stubs, never `abc.ABC`. A conforming module exposes `new_session()`,
  `ask()`, `ask_streaming()`, `describe_session()`. Anything beyond
  that (`harness.py`'s write-grant functions included) is explicitly
  an *optional* capability, not part of the required contract - this
  project has no evidence yet about what permission-scoping mechanism,
  if any, OpenCode/Hermes/Pi/DeepSeek/GrokBot's own CLIs have, and
  forcing every future adapter to implement Claude Code's specific
  `Edit(...)`+`acceptEdits` shape would be guessing at interfaces that
  don't exist yet.
- **`baseline/lib/harness_registry.py`** - `adapter_module_name`,
  `get_adapter` (imports lazily, returns `None` rather than raising
  for unknown/unimplemented/non-conforming harnesses),
  `supports_write_grant` (a `hasattr`-based capability check, never an
  assumption).
- **`providers.HARNESSES`** gained an `adapter_module` field per
  entry - `"harness"` for `claude`, `None` for the five unimplemented
  ones. A new test enforces the two fields can never disagree
  (`implemented: True` with no `adapter_module`, or vice versa, both
  fail).
- **`harness.py`** gained `new_session()` - a thin, named wrapper so
  `harness_registry`'s callers never need to know this adapter's
  session type is specifically `HarnessSession`.
- **`bin/baseline`** rewritten to dispatch through the registry
  everywhere it previously hardcoded `harness.*`: a new `_session_for
  (harness_id)` method makes the App itself the owner of "which
  session goes with which harness selection" (a dict keyed by harness
  id, each adapter's session created lazily via `adapter.new_session()`)
  rather than relying on a hidden module-global inside one specific
  adapter. Switching the dropdown now genuinely changes which module
  runs, and switching back preserves that harness's own session state
  rather than losing it.

## Why this resolves item 5 without building any stub adapters

Building `opencode.py`/`hermes.py`/etc. with fake or guessed
`ask()`/`ask_streaming()` implementations would be exactly the kind of
unverified guess decision record 40 already found and fixed once this
session (`Write(...)` vs. `Edit(...)`). None of those five tools were
available to check against in this environment, the same way `claude`
turned out to be. **The actually-buildable, honest piece of "item 5
must be modular" is the registry itself** - the thing that makes a
real adapter, once one is confirmed and buildable, a drop-in rather
than a rewrite of `bin/baseline`. Which harness (if any) gets a real
second adapter is still an open question for the user - queued as a
new item, not decided here.

## Verification performed before this commit

- RED confirmed first: `ModuleNotFoundError: No module named
  'harness_registry'` before any implementation existed.
- 10 new unit tests: `adapter_module_name` lookups (known/unimplemented/
  unknown), a structural check that every `providers.HARNESSES` entry's
  `implemented`/`adapter_module` fields agree, `get_adapter` returning
  the real `harness` module (and exposing every contract attribute) or
  `None` for unimplemented/unknown ids, and `supports_write_grant`
  against the real adapter, a fake missing the hooks, and `None`.
- Full suite: 707/707 passing (697 before this change), no
  regressions.
- `providers.py`, `harness_adapter.py`, `harness_registry.py`,
  `harness.py`, and `bin/baseline` all byte-compile clean.
- Not yet verified: a live boot confirming the Chat/Console tabs still
  work end-to-end through the new dispatch path - no real hardware
  access this session, same blocker as every other UI-facing item in
  this pass.
