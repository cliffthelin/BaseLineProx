# DR238 — Web handlers share strict JSON request parsing

**Status:** Implemented; parser and real-route behavior verified locally  
**Date:** 2026-10-09

## Context

After DR237, three other HTTP applications still converted malformed JSON into
`{}`: the merged Baseline server, Settings server, and Control Panel server.
That made invalid input look like an empty action object and left request size,
UTF-8, and top-level type handling inconsistent.

## Decision

Use one `web_request_json.read_json_object` implementation across those
servers and the scripts inbox. It enforces a bounded request size, valid
Content-Length, complete UTF-8 input, one JSON object, unique object keys, and
standard JSON constants. Invalid bodies raise a specific parse error; each
POST handler converts it to HTTP 400 before dispatch. Form-encoded posts keep
their existing path.

## Evidence and scope

The shared parser tests cover valid UTF-8 objects, empty/malformed/non-object/
non-UTF-8 bodies, oversized input without reading it, invalid Content-Length,
duplicate keys, and non-standard numbers. Real local HTTP tests verify the
scripts inbox rejects malformed writes without creating a file and the
Control Panel returns 400 before dispatch. Twelve focused tests passed. Those
routes use real sockets and production `RealRunner` implementations; no
FakeRunner/FakeProc, external service, or physical drive was used.

## Remaining work

No full route-by-route malformed-body test was added for every merged Baseline
or Settings endpoint. Request parser behavior is shared, while endpoint-level
authorization and action semantics remain covered by their existing suites.
