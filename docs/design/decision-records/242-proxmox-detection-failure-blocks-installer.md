# DR242 — Proxmox detection failure blocks installer

**Status:** Implemented; pure decision tests and read-only current-host probe  
**Date:** 2026-10-09

## Context

The installation gate treated every nonzero `dpkg-query` and `pveversion`
result, and an unavailable mountpoint check, as proof that Proxmox was absent.
That could send a target with an unknown installation state toward the
installer path.

## Decision

Recognize only explicit package absence, missing `pveversion`, and an
unmounted `/etc/pve` as negative evidence. Preserve command exceptions,
unexpected return codes, empty successful responses, and mountpoint errors as
probe errors. Positive Proxmox evidence still wins if a different probe fails.
When the state is unknown, the decision is `detection_unavailable`; firstboot
refuses further work and retries the probes on a subsequent invocation.

## Evidence and scope

Four pure gate/decision tests passed, including unknown-state refusal, positive
evidence precedence, confirmed-absence continuation, and firstboot's
package-install block. A read-only production
`RealRunner` probe on this development host observed absent `proxmox-ve`,
missing `pveversion`, and no `/etc/pve`, and returned the fresh-host installer
decision. The installer itself was not run. No FakeRunner/FakeProc or physical
hardware was used.

## Remaining work

This protects the detector branch; it does not verify firstboot end-to-end on
a physical Proxmox host or a target drive. Native target verification remains
open under work-queue item 7.
