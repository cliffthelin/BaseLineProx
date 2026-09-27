---
title: "Wiki Update Workflow"
kind: "operations"
status: "active"
last_reviewed: "2026-08-30"
tags:
  - wiki
  - maintenance
---
# Wiki Update Workflow

## New feature

Create or update, in order:

1. `20_Control_Plane/` feature page or `40_Modules/` module page.
2. Relevant `10_Platform/` provider pages.
3. Relevant `90_Sources/wiki/` source snapshots and `SOURCE_REGISTRY.md`.
4. `LOOKUP_MAP.md` keywords.
5. TDD gate/test pointer.
6. ADR if the change makes or reverses an architectural decision.

## Source separation

- Guardian-authored interpretation: `00_Project`, `10_Platform`, `20_Control_Plane`, `40_Modules`.
- Governing test documents: `30_TDD`.
- External-document snapshots/pointers: `90_Sources`.
