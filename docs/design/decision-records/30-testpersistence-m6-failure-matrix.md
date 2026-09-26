# Decision record: TestPersistence Milestone 6 - the eight failure modes, exercised for real

Status: **complete, real QEMU execution, all 23 recorded sub-steps passed on the final run.** Entirely synthetic. No physical hardware, no host privilege escalation, no live internet access from inside any guest. Builds on Milestone 2 (`d31d509`), Phase A (`e5144a9`), Phase B (`dc22f17`/`39458d0`), Milestone 5 (`700e954`/`da14fc7`), and the independent-review fix pass (`d225450`) - branch `local/testpersistence-m6-failures`, unmerged into `main`.

```
identity_scan.current_content: pending_full_scan
identity_scan.git_history:     known_findings_scope_unknown
identity_scan.full_scan:       pending_operator_verification
```

Entirely synthetic; neither depends on nor resolves that gate.

## What this proves

`baseline/lib/testpersistence/failures.py` (Milestone 2) already models the PRD's eight failure modes (§13) as pure-code `Outcome` objects, unit-tested with no disk I/O. This experiment proves the underlying **OS-level signals** those outcomes are built on are genuinely observable in a live guest - three boots, reusing Phase B's proven helpers.

## Step-by-step result (final passing run, all 23 recorded sub-steps `OK`)

| Failure mode | Boot | What was observed |
|---|---|---|
| **Missing** | A | `/dev/vdb` genuinely doesn't exist (`ls: cannot access '/dev/vdb': No such file or directory`) when no persistence disk is attached at all - not merely unformatted |
| **Unknown** | B | A permanently-blank second disk (`vdc`) never shows a `blkid` signature - attachment alone causes no auto-format |
| **Locked** | B | Right after `luksFormat`, before `open`: `cryptsetup isLuks` reports true, but nothing is mounted |
| **Corrupted** | B | A colocated copy of the manifest is corrupted with random bytes; `json.load` raises `JSONDecodeError` rather than silently returning partial data; the real manifest is untouched |
| **Newer-schema** | B | A `schema_version: 99` manifest is written, dumped, and checked with the **real** `baseline.lib.testpersistence.manifest.check_schema_version` (not a re-implementation) - it raises `SchemaVersionError`: *"manifest schema_version 99 is newer than this reader supports (1) - refusing to guess-parse"* |
| **Read-only** | B | Remounted `ro`; `touch` is refused: *"Read-only file system"* |
| **Full** | B | The small filesystem is filled to capacity; `dd` stops early (215 of 1000 requested blocks) with *"No space left on device"*; the pre-existing manifest is confirmed still intact afterward |
| **Cloned** (simultaneous-attachment case only) | C | After Boot B shuts down, the now-LUKS-formatted persistence disk is byte-copied (independent `qemu-img convert`, never a backing file) to a second image; both attached together, and `blkid` reports the **identical** LUKS UUID for `/dev/vdb` and `/dev/vdc` |

## Scope claim - stated precisely

**Cloned** here proves only the simultaneous-attachment case, per the PRD's own scoping (§5) and decision record 28. This experiment makes **no claim** about detecting a byte-identical clone used separately and never simultaneously observed - that remains explicitly undecidable from the store's own evidence alone, as already documented.

## A check-command bug, not a system-under-test bug

The first run of the "full" check piped `dd`'s stderr through `tail -3`, which cut away the actual `"No space left on device"` line and left only the trailing summary stats (`215+0 records in / 214+0 records out / ...`). The **real** behavior was correct throughout - `dd` genuinely stopped at 215 of the requested 1000 blocks, and the pre-existing manifest was genuinely still intact - only the check itself was wrong to rely on truncated output. Fixed by removing the unnecessary `tail`, since `dd`'s stderr here is only a few lines.

## Retention

No credentials, encryption keys, prepared ISOs, or disk images were retained after this record was written. Deleted after evidence capture: `TestPersistenceDisk-001.qcow2`, `unknown-disk.qcow2`, `clone-disk.qcow2`, all three seed ISOs, `pkgs.iso` (via `qemu_harness_safety.delete_validated_image` - exact validated paths, never a glob), and the download cache (base image + APT verification workspace, re-verified fresh for this experiment against the same checksums/signatures recorded in decision record 28). `TestSystem-A-missing.qcow2`/`-matrix.qcow2`/`-clonecheck.qcow2` were each deleted by the experiment itself between boots. Nothing under `experiments/testpersistence-m6-failures/` remains except this record's own evidence, checked for prohibited identifiers and absolute host paths (none found) before this commit.

## Verification performed before this commit

- Evidence JSON checked for real identifiers and absolute host paths - none found.
- Full repository test suite: 536/536 passing (no regressions from the harness commit).
- This record itself checked for the same before commit.
