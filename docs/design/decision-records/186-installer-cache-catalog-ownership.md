# DR186: Installer Cache catalog follows its owning modules

Date: 2026-10-09

## Context

The cache catalog caught every exception while loading its authoritative
firstboot package list and VM script manifest. It then substituted a locally
curated fallback list, omitted script entries, or used a generic upstream
origin. Those fallbacks could make an incomplete cache report look complete.

## Decision

Diagnostic package declarations, VM script entries, and their upstream
provenance must come from the modules that own those values. Import or data
failures raise `CatalogDefinitionError`. `reconcile()` converts that to a
`CacheScanError` so the web page presents an error state and does not render an
incomplete catalog as authoritative.

## Verification and limits

131 focused Installer Cache, web, source, and installer-input tests passed.
Tests inject failures for the firstboot and VM script owner modules and verify
that catalog generation or reconciliation fails visibly. Current host imports
and catalog generation work. This does not verify the mounted Installer Cache,
which remains unavailable as documented in DR185. No drive was modified.

## Follow-up

Other incomplete production behavior remains in the active audit backlog at
`docs/design/runtime-reality-tasks.md`.
