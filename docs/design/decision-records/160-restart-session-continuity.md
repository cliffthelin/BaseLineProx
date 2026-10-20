# DR160 — Restart authentication and session continuity

Date: 2026-10-04. Status: accepted fix. Continues DR148 and the application
restart-login handoff in DR158 (distinct from DR158 installer preparation).

Restart host's JSON request correctly requires an authenticated web session.
Production sessions previously lived only in memory, so reloading the web
service discarded existing login records while the browser retained its cookie.
The button rendered the raw "not authenticated" response without a sign-in path.
The recent development reloads therefore invalidate old login sessions; these
lost records cannot be reconstructed by trusting an unauthenticated cookie.

The merged production application now uses private SQLite session records keyed
by SHA256 of the random bearer token; raw tokens are not stored. Each record is
HMAC-authenticated with a separately derived web key. Creation time, TTL, persona
and role survive reload unchanged. Operator role/TTL adjustments are persisted
before returning a login cookie. Expired records are removed and logout revokes
the durable record. Modified records are refused. In-memory stores remain the
existing test/default standalone option; production merged-server wiring uses
the protected durable store.

Restart button now offers a same-origin Sign in link when authentication expires.
It does not replay a restart automatically. After sign-in the user selects
Restart host again; the existing gnome-session-quit --reboot native Ubuntu dialog
and authentication/role/cross-site gates remain in place. No forced reboot,
credential bypass or operator credential handling. Previously lost sessions need
one fresh sign-in after this deployment; new sessions survive subsequent reloads.

TDD: reopening, token-hash-only storage, private file mode, retained operator role,
expiry, tamper rejection, logout and authenticated restart after server reopen
were tested with real temporary SQLite/HTTP and test-only desktop runner fixtures.
Missing durable-store tests were confirmed failing before production changes.
The existing restart tests still distinguish a requested native confirmation from
an actual host restart. Full final suite: 3368 passed, no failures/skips/deselections; focused204
passed. Chromium verified the expiry sign-in link against fixtures. Production
reload PID1624321 serves login HTTP200 with same-origin policy. Results are
recorded in INSTALL.md and verification/160. No physical host restart or drive action is
claimed by these tests. Previous records remain history.
