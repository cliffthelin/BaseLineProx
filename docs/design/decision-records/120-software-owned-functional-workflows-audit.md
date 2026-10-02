# 120 — Software-owned functional workflows audit

Date: 2026-10-02
Status: accepted operating requirement and completed source audit; implementations open.

Direct instruction: AI is meant to create the software means to accomplish goals,
not be that software. Baseline normal workflows must function with AI disconnected.
Optional bots may invoke existing authorized operations; bot instructions cannot
stand in for an installer, scheduler, lifecycle manager or recovery engine.

Audit: `docs/design/functional-gap-audit-2026-10-02.md`, F01–F12. Key findings:
application apply/launch lifecycle absent; VM/LXC long operations synchronous on
single-threaded HTTP server; existing drive/backup jobs volatile; incomplete
workload/login recovery has no application workflow; guest/bind-data restore
coverage incomplete; requested distro links aren't install recipes. Existing
Operations schedules are deterministic and don't require an agent — retained.

Add queue75 for durable shared workload jobs/reconciliation, referencing existing
rows rather than declaring all functionality missing. App lifecycle remains74,
backup59/60, deploy72 and recipes73. No production implementation or hardware
verification done in this audit; no failing tests or fake successes suppressed.
Current INSTALL and handoff gain audit pointers. DR119 remains the application/OS
mechanism audit; this record adds the no-AI-runtime completion requirement.

GitHub publication of earlier increments was verified at6a806d8 on the exact
approved BaseLineProx branch. Documentation changes here do not alter that proof.
