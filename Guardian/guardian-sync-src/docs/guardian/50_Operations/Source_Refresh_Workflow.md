---
title: "Source Refresh Workflow"
kind: "operations"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - sources
  - maintenance
---
# Source Refresh Workflow

## When to refresh

Refresh a source snapshot when:
- Ubuntu package updates change a provider version;
- D-Bus introspection or polkit policy hash changes;
- a TDD test fails after system update;
- a provider behavior seems inconsistent with the wiki;
- preparing a new Guardian release baseline.

## Procedure

1. Open [Source Registry](../90_Sources/SOURCE_REGISTRY.md).
2. Revisit the canonical URL.
3. Compare contract-relevant behavior, not only prose.
4. On the target VM, capture installed package version, D-Bus introspection, polkit policy hash, and systemd unit version where applicable.
5. Update the local source snapshot.
6. Update the platform/provider page if Guardian interpretation changes.
7. Update the relevant ADR.
8. Update TDD contract/tests if the external contract requires it.
9. Run the affected gate.
10. Commit all linked changes together.

## Never

Do not silently update a source snapshot while leaving tests/ADRs based on old semantics.

## Optional automated fetch/hash pass

From the wiki root:

```bash
python3 tools/refresh_sources.py
```

The script reads `90_Sources/source_registry.json`, caches current canonical pages under
`90_Sources/cache/`, and writes SHA-256 comparison state to
`90_Sources/source_hashes.json`.

A changed hash is a **review trigger**, not permission to automatically rewrite a
Guardian contract. Review the authoritative provider behavior before updating the
wiki/TDD/ADR.
