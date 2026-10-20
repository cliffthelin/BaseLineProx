# DR201: Offer only harnesses with a working Baseline adapter

Date: 2026-10-09  
Status: accepted

## Context

The TUI listed Hermes, Pi, DeepSeek, and GrokBot as selectable chat backends,
but three had no adapter and Hermes ACP enables its own tool surface by
default. The selector then reported that a selected backend was not
implemented. That was a production menu path that could never complete a turn,
and the Hermes ACP behavior had not been reconciled with Baseline's no-tools
boundary.

## Decision

`providers.HARNESSES` contains only backends with real, conforming adapters:
Claude Code and OpenCode. The TUI no longer presents or routes unsupported
choices. A candidate backend can enter the list only after its real invocation
and permission behavior are verified and its adapter conforms to
`HarnessAdapter`.

## Evidence

A new registry regression failed before the change because the selectable
catalog contained four entries without adapters. After the change, the focused
registry suite passes; adapter calls are checked with existing adapter tests,
and the live OpenCode ACP round-trip evidence remains as documented in DR44.
No model request or real credential was used for this change.

## Remaining work

No unsupported harness is selectable. Adding any new backend requires a real,
verified adapter and explicit permission-boundary review; this record does not
claim Hermes, Pi, DeepSeek, or GrokBot support.
