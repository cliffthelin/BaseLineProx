# DR203: Show the selected AppData volume check on the isolation page

Date: 2026-10-09  
Status: accepted

## Context

DR200 added a read-only check that refuses a missing or wrong AppData mount,
but the `/app-isolation` page did not invoke it and still said live mount
verification was unimplemented. The page therefore hid a real check and
reported stale status text.

## Decision

The route passes its real command runner into the page renderer. Each render
now shows whether the chosen persona's labeled ext4 volume is mounted at the
expected path and whether its canonical source matches. Probe failures are
rendered as errors; an absent runner is shown as unchecked. The page remains
read-only and still does not apply overlays or claim application confinement.

## Evidence

The new success-path test failed before implementation because the renderer
did not accept a runner. Tests now cover a matching labeled mount and a
different mounted source. The combined AppData, isolation-page, TUI-modal,
harness-registry and OpenCode adapter suite passes 185 tests with scripted
command responses. No physical volume was inspected or changed in this test
run.

## Remaining work

Overlay application, per-app process confinement, reset, sharing, migration,
and guest verification remain open under queue74/REAL-008. DR200 remains the
read-only verification contract; no earlier decision record is superseded.
