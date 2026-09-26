# Decision record: Chat tab now shows the live session/write-scope state

Status: **implemented, unit-tested (3 new tests, 667/667 suite
passing), not yet verified live on a real boot.**

## What this closes

The 2026-09-26 V0.1 remaining-work audit (`docs/SESSION_HANDOFF.md`)
flagged that `HarnessSession`/`WriteGrant` (decision records 31-33)
existed with no UI reading them - the original 2026-09-20 ask was
specifically for `--allowedTools` "exposed as a visible/toggleable
header item rather than the current hardcoded empty string." That
data now has a reader.

## What was built

- **`harness.describe_session(session) -> str`** - pure, cheap enough
  to call on every render: `"session: cold (no memory yet) | write:
  none"` before the first turn, `"session: warm (multi-turn memory
  active) | write: none"` after it, or `"...| write: <scope_path>
  (this session only)"` whenever a grant is active. The exact session-
  only framing is stated in the text itself, not just documented
  elsewhere.
- **A new `#harness_status` `Static`** in the Chat tab, directly under
  the harness-select toolbar row.
- **`_refresh_harness_status()`**, called after: initial mount, every
  `ask_harness`/`run_console_ask` completion, and every `grant
  write`/`revoke write` console command. `harness._default_session` is
  one process-global instance, so a grant made from the Console tab is
  reflected in the Chat tab's header without either tab needing to know
  about the other's existence.

## What this still does not do

- No streaming (`-p --output-format stream-json`).
- No condensed one-line header bar (`BaselineOS | tabs | access scope
  | memory | copy | datetime`) - this is one `Static` inside the Chat
  tab specifically, not the app-wide header the original note
  described.
- No OSC 52 clipboard copy.
- No 80x24 layout floor design.
All four remain open per the current `SESSION_HANDOFF.md` audit.

## Verification performed before this commit

- RED confirmed first: `AttributeError: module 'harness' has no
  attribute 'describe_session'` before any implementation existed.
- 3 new unit tests for `describe_session` (cold/no-grant, warm/no-
  grant, warm/active-grant with the real resolved path).
- Full suite: 667/667 passing (664 before this change), no
  regressions.
- `baseline/bin/baseline` and `baseline/lib/harness.py` both
  byte-compile clean.
- Not yet verified: a live boot showing the header actually render and
  update after a real `ask`/`grant write` - this project's established
  discipline (edit -> deploy -> pilot test -> restart -> visual
  confirm) needs real hardware access this session doesn't have (see
  decision record 36's "Why nothing here has run for real").
