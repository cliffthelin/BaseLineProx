# DR234 — Retained launch settings apply across application adapters

**Status:** Implemented and unit verified; GUI behavior remains unverified  
**Date:** 2026-10-09

## Context

All supported application recipes accept Baseline's `scale` launch option, but
`apply_configuration` only wrote native preferences for VS Code and Chrome.
For Spotify, ChatGPT, and Claude, applying scale to an existing retained app
state failed even though the launcher already supports the option.

## Decision

Persist Baseline-owned launch settings in `home/.baseline/BASELINE.json` inside
the retained application data volume. Updates are validated, locked against a live app, and
published atomically with mode 0600. Capture reports the retained setting, and
launch overlays it on the generation's original recipe before forming the
application command. Native application preferences remain separately
allowlisted and are not exported as opaque profile state.

## Evidence and scope

The new retained-scale regression test failed before the implementation because
the non-native adapter was rejected. It now verifies applying scale to a
ChatGPT retained profile, re-reading the value through installed capture,
checking the exact settings document, and confirming the state backup includes
it. All 39 application-bundle tests and two
persistent-catalog installer-page tests passed. No FakeRunner/FakeProc, package
download, GUI, guest, or physical drive was used.

## Remaining work

The actual GUI response to a scale change has not been observed. Spotify,
ChatGPT, and Claude native preference extraction/apply remain unimplemented;
this change applies only Baseline's launch-scale setting. Application package
acquisition and guest verification remain open under queue item 76.
