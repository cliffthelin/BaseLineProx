# DR313 — Claude history and maintenance checkout belong on APPDATA

2026-10-19. Supersedes DR312's pending physical deployment checkpoint.

The operator approved importing Claude Code conversations, then directed that
this data belong on USER or APP data. APPDATA_ADMIN holds application history
at `/mnt/APPDATA_ADMIN/claude-code/.claude` and the editable source checkout at
`/mnt/APPDATA_ADMIN/workspaces/BaselineOS`. Encrypted provider credentials remain
in the USER_ADMIN vault. No transcript belongs in SUBSTRATE or INSTALLER_CACHE.

The optional installer `claude_history` boolean copies native projects,
file-history, plans and prompt history, preserving opaque contents. Different
existing child files are preserved with conflicts reported. Missing APPDATA
causes an explicit error; there is no USER_ADMIN fallback. Runtime Claude HOME
links its history directories to this persistent application data. The
`baseline-maintain` command opens the editable checkout and native resume picker;
Ctrl+A in that picker shows projects from other working directories. Native
Claude installation and authentication are still required.

Physical evidence: initial deployment installed AI feature code on PC601 and
its compact mirror, imported 2081 files (809320287 bytes), and created an editable
checkout. An initial USER_ADMIN allocation grew by 1 GiB. The subsequent relocation
moves history, receipt and checkout onto APPDATA_ADMIN on both copies, verifies
bytes before removing the USER_ADMIN originals, and refreshes affected runtime
and installer source. The extra USER_ADMIN capacity is retained rather than
risking a filesystem shrink. Reports live under CACHE/baseline-build/ai-feature-20261019T211020
and CACHE/baseline-build/claude-appdata-*.

Source verification: a failing storage-placement test was confirmed before the
change; 16 focused history/AI tests then passed using synthetic content and
credentials. Real data is copied without printing transcript or credential
contents. Physical copy verification does not establish native boot, Claude
login/session resume, guest profile delivery or an actual provider API call.
Queue72/76's fresh web executor and queue72/78's native acceptance remain open.
DR312 remains historical; INSTALL and the work queue carry the current status.
