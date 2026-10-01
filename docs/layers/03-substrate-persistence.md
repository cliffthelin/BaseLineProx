# 03 · SUBSTRATE

**Status: In progress** · [index](README.md)

Small, security-relevant recovery and substrate configuration. Fixed 1 GB
(min = max = 1), `defaults,nosuid,nodev,noexec`: config only, nothing meant to
run. Deliberately separate from [BASELINE](02-baseline.md), which holds
state rather than this kind of small config.

The page keeps its old filename so links still resolve. The volume was
renamed from `SUBSTRATE_PERSISTENCE`; the old name is still recognised.

## Open defects

| Finding | Status |
|---|---|
| ext4 label truncation (`SUBSTRATE_PERSIS`) | fixed on the real drive 2026-09-30, read back as `SUBSTRATE` |
| `baseline_drive_layout.py` describes this volume as holding the encrypted admin installer/recovery passphrase. No code writes it | open |

## Status

| Item | Status | Verified | Evidence |
|---|---|---|---|
| Volume defined, mounted with restricted options | MVP completed | unit tests | `drive_installer.MOUNT_OPTIONS` |
| Holds the encrypted admin passphrase | On roadmap | none | stated in `baseline_drive_layout.py`, not implemented |
| Per-install identity (`install_identity.py`) | In progress | unit tests | not yet called from firstboot |
