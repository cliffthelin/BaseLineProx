# Decision record: OSC 52 clipboard copy for the Chat tab's last answer

Status: **implemented, unit-tested (5 new tests, 672/672 suite
passing). Sending the escape sequence is not proof it was applied** -
whether this actually reaches the local clipboard over this specific
console/SSH path is unverified, per the original 2026-09-20 note that
first raised this exact caveat.

## What this closes

Item 1 of `docs/design/v0.1-work-queue.md` - one of the four still-open
pieces of the original "Chat tab quality" ask (`chat/001.md`,
2026-09-20): "a real clipboard 'copy' action (OSC 52 escape sequence
is the standard mechanism for a TUI to reach the *local* clipboard of
whatever's attached - not yet verified as working over this specific
console/SSH path)."

## Why a hand-built escape sequence, not a Textual API

Newer Textual versions ship their own `App.copy_to_clipboard()`
helper that does this internally. This project's real deployment
target installs `python3-textual` via `apt` (`provision.sh`), and this
dev environment has no `textual` package installed at all to check
against - there is no way to confirm which Textual version the real
target resolves to without real hardware access (the same blocker
named in decision record 36). Building the sequence directly in a
small, dependency-free module sidesteps that unknown entirely, and
makes the actual sequence-building logic unit-testable, which a call
into Textual's own App-level helper would not be.

## What was built

- **`baseline/lib/clipboard_osc52.py`** - `build_osc52_copy_sequence(text,
  *, selection="c")`, a pure function wrapping base64-encoded UTF-8 text
  in the standard `ESC ] 52 ; <selection> ; <payload> BEL` sequence.
- **`bin/baseline`** - a new `c` binding (`action_copy_last_answer`):
  writes the sequence directly to `sys.stdout` and flushes. Tracks
  `self._last_chat_answer`, set in `_write_chat` after every harness
  response. Guards the empty case (nothing asked yet) with a warning
  notification instead of sending an empty-clipboard sequence
  silently.

## What this deliberately does not do

- Does not copy anything from the Console tab - scoped to the Chat
  tab's last answer only, matching the original note's own framing
  ("`... | copy | ...`" as part of the Chat tab's header design).
- Does not confirm the copy actually landed anywhere - the
  notification says "sent," not "copied," because sending the escape
  sequence and a terminal actually applying it are two different
  claims, and only the first one is something this code can observe.
- Does not depend on or replace a Textual clipboard API, if one turns
  out to exist and work in the real deployed Textual version - that's
  a possible future simplification, not attempted here.

## Verification performed before this commit

- RED confirmed first: `ModuleNotFoundError: No module named
  'clipboard_osc52'` before any implementation existed.
- 5 new unit tests for `build_osc52_copy_sequence`: exact byte shape,
  Unicode handled via UTF-8 before base64, default and configurable
  selection buffer, and the empty-string edge case.
- Full suite: 672/672 passing (667 before this change), no
  regressions.
- `baseline/bin/baseline` and `baseline/lib/clipboard_osc52.py` both
  byte-compile clean.
- **Not verified**: whether the sequence is actually received and
  applied by a real terminal over this project's real console/SSH
  path - no real hardware access this session (see decision record
  36's blocker, which applies here identically).
