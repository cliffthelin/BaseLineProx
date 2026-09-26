# Decision record: Chat-tab streaming via real, captured NDJSON events

Status: **implemented, unit-tested (17 new tests, 691/691 suite
passing), the parsing logic verified against real captured CLI output;
the Textual UI wiring itself not yet verified live on a real boot.**

## What this closes

Item 3 of `docs/design/v0.1-work-queue.md`: `-p --output-format
stream-json` for real incremental streaming, the last major piece of
the original 2026-09-20 "Chat tab quality" ask still unaddressed.

## What "streaming" actually means in this pass - stated precisely

This dev environment's real `claude` CLI was used directly (continuing
decision record 40's verification work) to capture the real
`--output-format stream-json` event shape for a trivial prompt. Two
real facts came out of that, neither guessed:

1. **`--verbose` is required alongside `--output-format stream-json`
   under `-p`** - confirmed directly: omitting it fails fast with
   `Error: When using --print, --output-format=stream-json requires
   --verbose`, before any request is sent (no cost incurred checking
   this).
2. **Without `--include-partial-messages`, the assistant's own
   `{"type": "assistant", ...}` event arrives once, already containing
   the complete turn's text** - not token-by-token deltas. Real
   streaming value in this pass is therefore "the answer is available
   as soon as that one event lands, before the trailing
   `rate_limit_event`/`post_turn_summary`/`result` bookkeeping events
   and before the process exits" - a real latency improvement over
   blocking on the whole process, but not per-token incremental
   typing. `--include-partial-messages`'s actual delta shape was
   **not tested**, to limit further real API cost during this pass -
   see "What this deliberately does not do."

## What was built

- **`baseline/lib/stream_json.py`** - `parse_event`/`extract_assistant_text`/
  `extract_final_result`/`is_error_result`, pure functions. Its own
  test fixtures are the **real, captured lines** from a real `claude
  -p "Say exactly: hello world" --output-format stream-json --verbose
  --tools ""` invocation run directly in this session - not a guessed
  shape.
- **`harness.py`**: `Runner.stream()` (new, optional - existing
  `run()`-only fakes elsewhere are unaffected by its default
  `NotImplementedError`), `RealRunner.stream()` (real `subprocess.Popen`,
  line-by-line), `build_stream_argv` (adds `--output-format stream-json
  --verbose` to `build_ask_argv`'s existing session/tools logic),
  `ask_streaming(prompt, on_text, ...)` - calls `on_text` when the
  assistant event lands, returns the final answer text with the same
  contract as `ask()`.
- **`bin/baseline`**: `ask_harness` now calls `ask_streaming` instead
  of `ask`; `on_text` writes to the Chat log as soon as it fires.
  `printed` tracks whether `on_text` ever fired, so an error path
  (missing credentials, timeout, CLI not found - none of which call
  `on_text`) still gets shown exactly once, never zero or two times.

## What this deliberately does not do

- Does not implement `--include-partial-messages` token-level deltas -
  real cost was the limiting factor for testing that shape this pass;
  the current implementation is honest about calling `on_text` once
  per turn today, not many times.
- Does not change the Console tab's `ask <question>` command - still
  uses the blocking `harness.ask()`, matching this queue item's own
  Chat-tab-only scope.
- Does not add UI affordances for a mid-stream cancel/interrupt -
  out of scope for this pass.

## Verification performed before this commit

- `stream_json.py`: 11 tests against real captured NDJSON lines (the
  assistant/rate-limit/result event shapes actually emitted by the
  real CLI).
- `harness.py`: 6 new tests for `build_stream_argv`/`ask_streaming`
  against a fake streaming runner yielding those same real event
  shapes - session-started marking, malformed-line tolerance, and the
  no-credentials path never touching the runner.
- Full suite: 691/691 passing (674 before this change), no
  regressions.
- `harness.py`, `stream_json.py`, and `bin/baseline` all byte-compile
  clean.
- **Not verified**: the Textual UI actually rendering incrementally on
  a real boot - no real hardware access this session, same blocker as
  every other UI-facing item in this pass.
- All real API calls made to verify the NDJSON shape were minimal
  (one trivial prompt, one fast-failing flag-validation check that
  incurred no request cost) and no scratch files were retained
  afterward.
