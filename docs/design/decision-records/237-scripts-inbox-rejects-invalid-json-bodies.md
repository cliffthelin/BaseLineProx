# DR237 — Scripts inbox rejects invalid JSON request bodies

**Status:** Implemented and verified with real local HTTP and filesystem I/O  
**Date:** 2026-10-09

## Context

The scripts inbox HTTP handler converted malformed JSON into `{}`. For an
authenticated `POST /api/scripts/name`, the missing `content` defaulted to an
empty string and the production filesystem runner created an empty script.
The invalid request therefore returned success and mutated state.

## Decision

Require a bounded UTF-8 JSON object for scripts-inbox POST requests. Malformed,
empty, oversized, non-object, or invalid-length request bodies return HTTP 400
before route handlers perform authentication-dependent file operations.

## Evidence and scope

A real local HTTP regression test initially received HTTP 200 for malformed
JSON. After the change it receives HTTP 400 with a malformed JSON error and
confirms no file was created. The test uses the production
`RealRunner` and filesystem, not FakeRunner/FakeProc. No script was executed and
no external service or physical drive was used.

## Remaining work

Other web handlers have separate JSON-body parsers and require their own route
review. This decision covers only the scripts inbox server.
