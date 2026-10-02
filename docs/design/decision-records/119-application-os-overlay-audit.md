# 119 — Application and whole-OS overlay audit

Date: 2026-10-01
Status: accepted audit and truthful UI correction; runtime application implementation still open.

User requested GitHub push and an audit of application-layer isolation/overlays and an overlay for the whole OS. Reviewed source and existing plans; no physical hardware or credentials handled. Findings and implementation sequence: `docs/design/application-layer-audit-2026-10-01.md`.

The App Isolation page previously inferred “Isolation holds” from pure declared-path checks. RED regression test confirmed this misleading claim. Page now reports “Plan checks passed/failed” and explicitly states runtime isolation has not been applied or verified. No declared target is no longer described as proof of statelessness. Existing route assertions were updated for this actual design change, not weakened to conceal a failure.

Pure reproductions: 15 catalog app plans, 7 overlays, 3 binds, all `isolated=True`, no exact target conflicts; target escaping collides for `~/a-b` and `~/a/b`; Quadlet persistence check accepts `/mnt/BASELINE/app:/data`; Caddy publishes without explicit host IP. These findings are not live exploits or runtime tests. App plan apply/launch/update/reset and backup/restore, physical AppData mounts and per-guest adapters remain unimplemented/unverified.

Whole OS overlays are real in DR117 VM and DR118 LXC proofs inside disposable KVM, but aren't per-app confinement. The disposable host proof's qcow2 layer is not a deployed bare-metal host OS overlay. Current mutable PVE host root has no such production root-overlay implementation.

Correct current layer docs and INSTALL in place; preserve older decision records and DR117/118 fingerprints as historical evidence. Add v0.2 row74 for the app lifecycle; retain rows42/60/72/73 gaps. This audit does not introduce guest users or partition changes. Validation result is appended after checks. GitHub publication is explicitly authorized by the user; push current branch to configured origin upstream, without force or unrelated remote changes.

Final validation: 2,863 hardware-guarded unit tests passed in 126.11 seconds.
Seven focused App Isolation tests passed, including real loopback HTTP with
fake dependencies; no real application confinement was exercised. Deploy
import coverage and git whitespace checks passed. Changed-file private-key/token
pattern and large-artifact checks passed. No new physical hardware verification
was performed. Earlier DR117/118 evidence and fingerprints remain historical.
