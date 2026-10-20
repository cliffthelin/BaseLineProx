> Imported 2026-10-11 from the parallel (Codex) effort, where this record is DR248. Numbered DR252 here so it does not collide with this branch's DR245-248. Other DR numbers inside the text refer to that effort's numbering.

# DR252 (parallel effort DR248) — Refreshed current-source installer ISO boots in isolated KVM

**Status:** ISO build and targetless installer-UI boot passed in KVM
**Date:** 2026-10-11

## Artifact and build

Built from the current repository source with `RealIsoBuilderRunner`; generated files were written to the new backup-drive directory
`/mnt/10TB/backup/baseline-tests/pc401-r247-refresh-20261011`.
The artifact is `BaselineOS-platform-20261011-r247.iso`, SHA-256
`255363b349f96628dd863dd3be8ba698757f98a6536d8af81d6102416d2a8fea`.
The builder postconditions passed. An independent xorriso inventory matched all
987 expected `/baseline-src` files, with no missing or extra entries and no
`.pyc`/`.pyo` files. The sidecar checksum verified.

## Isolated KVM boot

Started a separate QEMU process from this turn, booting the new ISO with no
network interface and no target disk. The captured framebuffer reached the
Proxmox VE Installer GUI and showed “No Hard Disk found!”, expected with no disk
attached. QEMU exited with code 0 after capture. The serial transcript and PNG
screenshots are in the same backup-drive directory. The build staging tree and
screenshots remain there as evidence; no existing files were moved or deleted.

This proves current ISO-media boot to the installer interface in KVM only. No
physical drive was written. It does not prove installation completion, PC401
network/internet/firewall, installed Proxmox browser GUI, or native cold boot.
The prior PC401 QEMU guest still lacked IPv4 and reachable HTTPS 8006, and the
installed PC401 has not been updated with these latest source changes. Queue
row78 and the independent-drive checklist remain open.
