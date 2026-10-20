# DR223: Declared harness failures stay visible

**Status:** Accepted  
**Date:** 2026-10-09

## Context

The harness registry advertised adapters as implemented but returned `None`
when importing one failed or its module did not satisfy the adapter contract.
The UI then described the selected harness as absent, hiding the actual
installation or integration failure.

## Decision

Unknown IDs and entries deliberately marked unimplemented still return `None`.
A harness marked implemented must name an importable, conforming adapter;
missing modules, dependency import failures, and contract violations raise
`HarnessAdapterError` with the cause. The Textual status, console, and chat
surfaces display the diagnostic instead of presenting the adapter as absent.

## Evidence and scope

Registry, Claude/OpenCode adapter, streaming, and Baseline web tests passed 126
tests. New regression tests injected an import failure and a nonconforming
module. No live harness process or external provider was invoked for this
change.

## Remaining work

The selected adapter's runtime still depends on its native CLI and provider
configuration. Existing real OpenCode ACP evidence remains separate from this
injected registry test; no new live runtime verification was performed.
