# DR235 — Audit view rejects corrupt history

**Status:** Implemented and verified with real local HTTP coverage  
**Date:** 2026-10-09

## Context

The Audit view skipped malformed JSONL lines and displayed the remaining
records as a complete history. A truncated or corrupt record could therefore
be hidden while the page still returned success.

## Decision

Treat malformed JSON, non-object records, invalid UTF-8, empty records, and an
incomplete final record as `AuditReadError`. For a bounded tail read that starts
inside a record, discard only that first partial line after finding its next
newline. A missing log remains a valid empty history; read failures and
corruption are unavailable states.

## Evidence and scope

A regression test failed before the change because corrupt input did not raise.
All 18 audit and approvals page tests passed. A new real local HTTP test writes
a malformed record into the configured log and verifies `/audit` returns 503
with the corruption detail, never the empty-history message. The tests used no
FakeRunner/FakeProc, physical drive, or external service.

## Remaining work

No corruption-detection changes were made to the append-only writer or log
rotation. Production log durability, rotation boundaries, and physical host
operation remain separate checks.
