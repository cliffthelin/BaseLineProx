# Decision record: status bar truncates to the 80x24 layout floor

Status: **implemented, unit-tested (6 new tests, 697/697 suite
passing), not yet verified on a real 80x24 terminal.**

## What this closes

Item 4 of `docs/design/v0.1-work-queue.md`: the original note that the
header/toggle-bar design should target an 80x24 floor for hardware
where KMS isn't available, never designed until now.

## A concretely self-inflicted version of the problem

Decision record 39's `#status_bar` is `height: 1` - overflow content
there is clipped, not wrapped. `harness.describe_session`'s output
includes the write grant's real, absolute `scope_path` (decision
record 33), which can genuinely be long
(`/var/lib/baseline/settings-web/store.json`-scale paths are already
real examples elsewhere in this repo). A line like `BaselineOS |
session: warm (multi-turn memory active) | write: <long path> (this
session only) | c=copy` can exceed 80 characters outright - a real,
self-inflicted instance of exactly the floor problem item 4 named in
the abstract.

## What was built

- **`status_bar.elide_middle(text, max_len)`** - truncates the middle
  of `text`, keeping both ends visible (so a truncated path still
  shows where it starts and ends, not just its prefix), never
  exceeding `max_len` for any value including very small ones (tested
  down to `max_len=1`).
- **`status_bar.format_status_bar(session_desc, *, max_width=80)`** -
  computes the fixed prefix/suffix budget (`"BaselineOS | "` /
  `" | c=copy"`) and elides only the variable part in between, so the
  result never exceeds `max_width`.
- **Plain ASCII truncation only** (`"..."`, never an ellipsis glyph) -
  this project's own standing rule, `docs/SESSION_HANDOFF.md`'s
  "Standing rules": *"No non-ASCII characters anywhere in rendered
  output - found and removed the app's only Unicode use (arrow
  glyphs) after multiple TERM=linux rendering bugs this session; the
  bare console's font can't be assumed to have arbitrary glyphs."*
  Directly enforced by a test asserting `.isascii()`.

## What this deliberately does not do

- Does not change any other widget's layout - `DataTable`s already
  use flexible `1fr` heights and Textual's own scrolling, which
  degrades acceptably at a smaller terminal size without code changes;
  the concrete, provable risk was specifically the docked, one-line,
  clip-not-wrap status bar.
- Does not verify actual rendering at 80x24 on a real terminal -
  the arithmetic is proven (the result string's length is bounded),
  but whether it *looks* right, and whether anything else in this
  layout has its own floor problem, needs a real boot to check - no
  real hardware access this session.

## Verification performed before this commit

- RED confirmed first: `AttributeError: module 'status_bar' has no
  attribute 'elide_middle'` before any implementation existed.
- 6 new/updated unit tests: short text untouched, long text truncated
  with a bounded length and an ASCII-only ellipsis marker,
  `elide_middle` never exceeding `max_len` across seven different
  small-to-moderate values, the full `format_status_bar` line staying
  within an 80-char budget for a realistically long write-grant path,
  and the default `max_width` matching an explicit `80`.
- Full suite: 697/697 passing (691 before this change), no
  regressions.
- `status_bar.py` byte-compiles clean.
