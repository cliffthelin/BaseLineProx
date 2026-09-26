# Decision record: the harness may gain write ability, only as an explicit, scope-asked, session-only grant

Status: **decided, not yet implemented.** No code in this repository
grants the harness any write or execution ability as of this record.
`harness.ask()` still passes `--tools ""` on every call (see decision
record 31, which changed reachability only and left this untouched).

## The question this record answers

The project's own salvage notes (`docs/salvage/OLD_BASELINE_NOTES.md`)
record a considered rejection from the predecessor project:

> The "Agentic (YOLO)" AI mode - the old harness could propose *and,
> with approval, execute* bash commands. V0.1's harness is read-only
> tools only; this is a deliberate narrowing, not an oversight.

A cross-session review flagged that this narrowing needed either an
explicit re-affirmation or an explicit, written reversal - never a
silent drift in either direction. Asked directly, the decision is:
**partially reversed, in a specific, bounded way.**

## The decision

The harness may be given the ability to write files. This is granted
under three conditions, all required together:

1. **Explicit, per-instance authorization.** The harness never writes
   anything the first time a need for it comes up without asking.
   Before any write, it asks the operator what scope it's allowed to
   write within (e.g. a specific path or directory) - the operator
   names the boundary, the harness does not assume one.
2. **Scope, not blanket access.** The authorization is *of a scope*
   (where it can write), not a standing "may write anything"
   permission. A grant for one path says nothing about any other path.
3. **Session-only duration.** The grant is valid only for the current
   session. It is never persisted as a standing permission - the next
   session starts with no write ability at all, and must be asked
   again if a write is needed there too.

Everything the old harness's "Agentic (YOLO)" mode implied and this
project rejected once already - unattended execution, standing
privilege, arbitrary bash - remains rejected. This decision grants
**write ability to files, under an explicit ask, scoped, and
session-bound** - a narrower thing than what was rejected, not an
overturning of that rejection's spirit.

## Why this shape, not a bigger one

The field research behind this review (OpenClaw's failure profile;
Progent's shrink-only privilege formalization; this project's own
`baseline/lib/testpersistence/grants.py`, which already models exactly
this shape - a `Grant` scoped to one `collection`, one
`access_mode`, one `duration` ("until_revoked" or an expiry marker),
and one `authorized_by`, for a different resource) all converge on the
same structure: a grant is scoped, explicit, and time-bounded, and
expanding it always requires a fresh explicit act, never an inherited
default. This decision applies that same shape to file-write access
instead of TestPersistence's disk/collection access - reusing a
pattern this codebase has already proven out, not inventing a new one.

Session-only duration specifically (rather than `grants.py`'s
`until_revoked` option) is the deliberate choice here: the harness's
write ability should not accumulate or persist the way an
application's data-access grant might reasonably want to. Every new
Baseline session is a clean slate for this.

## What implementing this actually requires (not yet built)

- A grant object mirroring `grants.py`'s shape, addressed at
  filesystem scope rather than a `collection`: something like
  `{scope_path, authorized_by, granted_at}`, held only in memory for
  the life of the process (consistent with decision record 31's
  session model), never written to disk.
- A prompt flow: when the harness's response indicates it wants to
  write something, Baseline asks the operator to name (or confirm) the
  scope before any write tool is enabled for that session - this is
  new UI, not just a flag flip, and it does not exist in `bin/baseline`
  today.
- A revised `build_ask_argv` (or an equivalent) that only ever adds a
  write-capable tool flag (e.g. a scoped `--allowedTools`) after that
  grant exists, and never before - the current `--tools ""` default
  stays the floor for every session until a grant is explicitly made
  in it.
- Tests proving the negative as rigorously as the positive: no write
  tool is ever enabled without a grant in that specific session, a
  grant made in one session grants nothing in the next, and a grant
  for one scope path never allows a write outside it.

None of the above is implemented. This record exists so a future
session builds toward this shape deliberately, rather than
re-deciding (or accidentally contradicting) this in an ad hoc way
without knowing this conversation happened - the same reason decision
records 25-30 exist for their own subsystems.

## Explicitly not decided here

- Whether the harness ever gets anything beyond file writes (arbitrary
  command execution, network calls, package installation) - out of
  scope for this record; would need its own decision if ever
  proposed.
- The exact mechanism Claude Code's own CLI offers for a scoped write
  grant (its `--allowedTools`/`--disallowedTools` flags, confirmed
  present in `chat/001.md`'s research, are the likely mechanism but
  were not re-verified against this specific scope-of-write use case
  for this record).
