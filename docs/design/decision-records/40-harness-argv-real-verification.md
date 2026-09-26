# Decision record: harness.py's argv shapes verified against the real claude CLI - one bug found and fixed

Status: **verified for real, one real bug corrected.** This is the
first time any of decision records 31-33/36-39's "not yet verified
against the real claude CLI" flags were actually checked against the
real binary, rather than left open pending real hardware.

## What made this possible

This dev environment (`cane-System-Product-Name`) has no `qm`/`pct`/
`pvesh`/Docker daemon (decision record 36's blocker, unchanged - still
true), but it does have a real, authenticated, working `claude` CLI
installed (`claude --version` -> `2.1.226 (Claude Code)`). That's
enough to verify every claim decision records 31-33 made about the
CLI's own flags, independent of Proxmox/Docker access entirely.

## Finding 1 (confirms record 31): session continuity is real

```
claude -p "Remember this exact secret code for later: PELICAN-7. ..." --session-id <uuid> --tools ""
claude -p "What was the secret code I told you a moment ago? ..." -c --tools ""
```

Second call answered `PELICAN-7` correctly. `--session-id` naming a
session on the first turn, then `-c` continuing it, genuinely
preserves multi-turn memory. `build_ask_argv`'s reachability half
(record 31) needed no changes.

## Finding 2 (corrects records 32/33/36): `Write(...)` is not a valid rule; `Edit(...)` is

Running the exact argv records 32/33 had pinned in tests
(`--allowedTools "Write(<scope>/**)"`) against the real CLI:

```
Permission allow rule (--allowed-tools): Write(<path>/**) is not matched
by file permission checks — only Edit(path) rules are. Use
Edit(<path>/**) instead (Edit rules cover all file-editing tools).
```

This is a real bug records 32/33/36 all built on top of an unverified
guess. Fixed directly: `build_ask_argv` now sends
`--allowedTools "Edit(<scope_path>/**)"`.

## Finding 3 (new, not anticipated by any prior record): `--allowedTools` alone isn't enough

With the corrected `Edit(...)` rule name but no other change, the real
CLI still refused the write non-interactively: *"I don't have write
access to that path... the permission request wasn't granted."*
Isolated directly (two otherwise-identical calls, only one flag
different): the missing piece is `--permission-mode acceptEdits`.
`--allowedTools` names which rule *would* match; the permission mode
governs whether a matching edit is applied without an interactive
prompt to approve it. `build_ask_argv` now sends both together.

## Finding 4: the scope still genuinely holds under a real, adversarial prompt

With both fixes in place, a follow-up test asked the real CLI to write
a file *outside* the granted `scope_path` (worded to look like a
plausible task, not an obvious test). It refused on its own reasoning,
correctly describing the request as resembling "a sandbox-escape or
data-exfiltration probe," and no file was created outside the scope.
This is the first real confirmation - not just a unit test against a
fake - that a `WriteGrant`'s `scope_path` boundary actually holds
against the real tool it's meant to constrain.

## What changed

`baseline/lib/harness.py`'s `build_ask_argv`: the active-write-grant
branch now emits `--allowedTools "Edit(<scope_path>/**)" --permission-mode
acceptEdits` instead of the original, unverified `--allowedTools
"Write(<scope_path>/**)"` guess. `tests/unit/test_harness_write_grant.py`'s
corresponding test updated to the corrected, now-verified shape - this
is a case of "fix the test because the implementation's assumption was
wrong," not a test that was itself buggy.

## What this still does not verify

- Nothing about `vm_provision.py`/`pct_provision.py`/`docker_provision.py`
  - those need real Proxmox/Docker access, unrelated to this finding
  and still blocked exactly as decision record 36 describes.
- Whether the *installed target's* `claude` CLI version matches this
  dev machine's `2.1.226` - a version skew is possible and would need
  re-checking once real deployment access exists.
- Streaming (`--output-format stream-json`)'s actual JSON event shape
  - not tested in this pass; still item 3 on `v0.1-work-queue.md`.

## Verification performed before this commit

- Four real `claude -p` invocations run directly in this session,
  each isolating one variable at a time (rule name, permission mode,
  in-scope vs. out-of-scope target) - not simulated, not assumed.
- `tests/unit/test_harness_write_grant.py`/`test_harness.py`: 22/22
  passing after the correction.
- Full suite: 674/674 passing, no regressions (same count as before -
  this corrected an existing test's assertion, it didn't add a new
  one).
- `harness.py` byte-compiles clean.
- All scratch probe files created during this verification
  (`probe*.txt`, `write_grant_probe/`) deleted afterward - nothing
  retained.
