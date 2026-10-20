# DR212: Provider observations preserve uncertainty

**Status:** Accepted  
**Date:** 2026-10-09

## Context

Provider discovery swallowed credential-file read errors and reported the
provider as unconfigured. The Claude row also said a configured token had been
"verified live" even though the periodic check only inspected configuration.
The Ollama TCP probe treated every socket error as proof no service was
configured.

## Decision

Credential lookup now treats a missing file as unconfigured, a non-empty
matching value as configured, and any other file-read error as unknown. Empty
assignments do not count as credentials. Claude configuration is labeled
available without claiming a live API check. Ollama's TCP connection refusal
is Unreachable; timeout and other socket errors are Unknown. The dashboard
preserves Unknown and displays Available separately from Reachable.

## Evidence and scope

The focused provider, harness-registry, network, firstboot, readiness, Settings,
and TUI suite passed 209 tests using injected environment, socket, filesystem,
and AST observations. No provider credentials were read from the host, no
external API was called, and no live Ollama service state was checked.

## Remaining work

These checks establish configuration and TCP reachability only; they do not
prove provider authentication, API functionality, model readiness, or an
end-to-end response. Those claims must be made only after a real request.
