# Decision record: app-wide condensed status bar

Status: **implemented, unit-tested (2 new tests, 674/674 suite
passing), not yet verified live on a real boot.**

## What this closes

Item 2 of `docs/design/v0.1-work-queue.md`: the original 2026-09-20
ask for a condensed one-line header bar (`BaselineOS | tabs | access
scope | memory | copy | datetime`).

## Scope narrowed against what already exists, not duplicated

Two pieces of the original six-part description are already rendered
by widgets this app already has:

- **datetime** - Textual's own `Header(show_clock=True)` already
  shows a live clock. Adding a second clock would be redundant, not
  additive.
- **tabs** - `TabbedContent`'s own tab strip already renders every tab
  name and highlights the active one (`Tab.-active` in this file's own
  CSS, pre-existing). A second "tabs" element in a header bar would
  duplicate what's already visible one line below it.

So the actual new bar covers only what nothing else already shows:
**access scope** and **memory** (both already computed by
`harness.describe_session`, per decision record 37) and **copy** (the
`c` binding added in decision record 38). `status_bar.format_status_bar`
combines those into one line: `BaselineOS | <session/access-scope
description> | c=copy`.

## What was built

- **`baseline/lib/status_bar.py`** - `format_status_bar(session_desc)`,
  a pure function.
- **`bin/baseline`** - a new `#status_bar` `Static`, docked at the top
  (directly under `Header`), updated by the same `_refresh_harness_status`
  call already wired to mount/ask/grant/revoke (decision record 37) -
  extended to update both the Chat-tab-local line and this app-wide
  bar, not one replacing the other. New CSS: `dock: top; height: 1;
  background: #005f87; color: #ffffff` - an explicit hardcoded color
  pair, matching this file's existing convention throughout.

## What this deliberately does not do

- Does not re-render tab names or a clock - both already exist
  elsewhere, per the scoping above.
- Does not make the bar interactive/toggleable, despite the original
  note's "access scope... exposed as a header toggle" phrasing - this
  is a read-only display of the same state a `grant write`/`revoke
  write` console command already changes; a toggle control would be a
  separate, larger follow-up if ever wanted.

## Verification performed before this commit

- RED confirmed first: `ModuleNotFoundError: No module named
  'status_bar'` before any implementation existed.
- 2 new unit tests for `format_status_bar` (plain description, and one
  with an active write grant embedded in the description).
- Full suite: 674/674 passing (672 before this change), no
  regressions.
- `baseline/bin/baseline` and `baseline/lib/status_bar.py` both
  byte-compile clean.
- Not yet verified: a live boot confirming the bar actually renders,
  docks correctly above the tab strip, and updates on every relevant
  action - no real hardware access this session (see decision record
  36's blocker, which applies identically here).
