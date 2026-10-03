# DR132 — Repeatable OS/application adapter development

2026-10-02. Accepted; supplements DR126–131, queue76/74.

User requested a dynamic, repeatable template for other operating systems.
Audited current source: recipe validation remains Ubuntu24.04-specific;
VS Code build remains publisher Linux-x64 archive-specific. These restrictions
are explicit and are not removed without a verified second native adapter.

Added design/repeatable-environment-adapter-pattern.md: shared workflow phases,
native adapter responsibilities, capability/evidence states, test-first extension
checklist and handling of incompatible targets. Reuse demonstrated helpers;
extract shared implementation when a second real adapter establishes the common
behavior. Recipes are data, never arbitrary imported executable plugins. OS,
application and substrate/backend adapters have distinct responsibilities.

Documentation-only verification: checked current implementation boundaries and
Markdown whitespace. No new production behavior, unit/fake runtime tests,
disposable guest or physical deployment verification. DR131 evidence is unchanged.
Open76: generic adapter integration, managed application reconciler and two-target
locked replay;74: actual persistence/isolation; other OS support remains unverified.
Current docs now link the extension pattern; no earlier record proved universal
support, so no historical record is superseded or corrected.
