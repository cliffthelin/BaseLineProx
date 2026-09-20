# Entry template

Copy this block for every new entry. One block per request/change, appended
to the bottom of the current open block file for its category (see
`INDEX.md` for which file is currently open, and the block-rotation rule).

```
## <YYYY-MM-DD HH:MM local> - <short title>

**Requested via:** chat | built-in Chat tab
**Context:** why this was asked for - the problem or goal, in the
  requester's own terms.
**Considered:** the real options weighed (including "do nothing" or a
  simpler fix, when relevant) and why the chosen one won.
**Requirement determined:** the concrete, checkable definition of done
  for this change - what "correct" means here, stated before or
  alongside the fix.
**Files changed:**
  - path/to/file — one line on what changed in it
**Verification:** exactly how the requirement was tested and proven
  (commands run, output seen, live device checks) - not "should work,"
  actual evidence.
**Pointer update:** what changed in this category's INDEX.md row.
**Docs update:** any docs/* file touched as a result (or "none").
```

Keep entries factual and specific - real commands, real output, real file
paths. This log is read by grep/search under time pressure, not narrated
for an audience.
