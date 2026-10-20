# DR233 — Task catalog revisions include custom application locks

**Status:** Implemented and unit verified; package acquisition and runtime remain unverified  
**Date:** 2026-10-09

## Context

Tasker revisions hashed implementation files but omitted the mutable custom
application catalog. A publisher URL or SHA256 could change while the task
catalog continued advertising the same revision, making a stale revision look
current.

## Decision

Hash the canonical JSON representation of the loaded application definitions
and include that digest in every task component revision and catalog record.
This makes revisions sensitive to custom package source locks.

## Evidence and scope

The regression test failed against the old implementation: changing only a
custom package SHA256 left the task revision unchanged. After the fix, all
seven focused custom-application contract tests passed. The test uses the
production task catalog code and local catalog state; it uses no FakeRunner,
FakeProc, external package, VM, or physical drive.

## Remaining work

No custom package has been downloaded, installed, or launched. Installer Plan
package acquisition and guest/runtime proof remain open under queue item 76;
physical USER_PERSISTENCE mount survival is also unverified. This record
extends DR232 without changing its storage decision.
