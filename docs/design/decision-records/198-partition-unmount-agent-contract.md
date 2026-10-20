# DR198 — Partition unmount browser-action contract

Date: 2026-10-09

## Decision

`unmount_partition` remains a serial-scoped, human-confirmed Drive Administration
action. The live page already requests the mounted partition path and the
production action checks the mount source and selected drive ancestry before
calling `umount`. The browser-action test adapter now sends that required path
and routes the action to its RAM-drive recorder, rather than allowing a bot test
to fall through toward host devices. A matching `BotUnmountPartition` definition
documents browser-only use and hands native confirmation to the human.

## Evidence and limits

The previous failure was reproduced in the in-memory browser test: its generic
parameter helper omitted the path that the real modal sends, causing a
`KeyError` while building the review summary. The focused bot and serial-safety
tests passed (63 bot tests; 21 action/agent contract tests). The RAM drive is a
test stand-in; no real partition was unmounted or hardware action exercised.
