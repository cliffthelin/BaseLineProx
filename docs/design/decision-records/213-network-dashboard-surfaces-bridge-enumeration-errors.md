# DR213: Network dashboard surfaces bridge enumeration errors

**Status:** Accepted  
**Date:** 2026-10-09

## Context

The network module already distinguished an absent bridge-member directory
from an inaccessible or otherwise unreadable one. The Textual dashboard bypassed
that helper and swallowed every `OSError`, so it could omit physical interfaces
behind an active bridge without saying that member discovery had failed.

## Decision

The dashboard now uses `network._bridge_members()`. Confirmed absence still
means the active interface is not a bridge. A probe error adds a Network row
with Unknown status and the diagnostic while retaining the observed routed
interface as Active.

## Evidence and scope

The focused provider, harness, network, firstboot, readiness, Settings, and TUI
suite passed 210 tests using injected observations and structural TUI checks.
No live bridge or interface state was inspected, and interactive Textual
rendering was not verified.

## Remaining work

REAL-007 still tracks route-attribute preservation, transactional rollback, and
recovery verification without cutting off the active session. This record does
not claim physical network verification.
