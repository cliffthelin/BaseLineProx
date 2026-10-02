# DR126 — Installer wiring and portable OS/app recipe audit

2026-10-02. Accepted architectural direction; implementation remains open.

User requested installer audit, rebuild retaining all durable state, and compact
stackable OS/app configuration templates without user content. Source inspection
finds substrate installer and VM lifecycle already separate, app lifecycle absent.
Recommend one application with a reusable environment recipe engine and guest
reconciler, not a second competing destructive installer. Recipe-only export,
fresh instantiate, retained rebuild and private data restore are distinct actions.
Raw overlay export is not a safe portable configuration exporter.

See installer-overlay-template-audit-2026-10-02.md for source wiring, state classes,
rebuild contract, proposed format, composition conflicts and acceptance sequence.
No parser/UI/runtime implementation, native tests, physical operation or new
lossless-rebuild claim. Rows72–75 remain open; row76 records recipe composition,
export/import and fresh-state instantiation. DR119/125 planner evidence remains
historical. Current queue, INSTALL and handoff updated to reflect this direction.
