# DR243: Include current Baseline source and documentation in rebuilt installer ISO

Date: 2026-10-10

## Decision

The remastered Proxmox installer carries the current Baseline platform code and
its documentation as a complete `/baseline-src` tree. The staging set includes
`boot/`, `baseline/`, `packaging/`, `automation/`, `docs/`, `tests/`, `tools/`,
and the root `README.md` and `AGENTS.md`. The ISO remains a Proxmox installer
with Baseline source packaged alongside it; this decision does not claim an
unattended or physical Baseline installation.

## Reason

The prior builder included the `docs/` directory but omitted the root overview,
agent/build instructions, and operational `tools/`. A machine booted from the
installer therefore did not carry all project documentation and source tools.
The production staging path now copies those inputs, and the ISO is built from
the current repository rather than an earlier snapshot.

## Evidence

- The regression test first failed against the production filesystem runner
  because the staged `README.md` did not exist, then passed after the fix.
- The publisher Proxmox VE 9.2-1 source image had SHA-256
  `4e88fe416df9b527624a175f24c9aa07c714d3332afb1ee3dbf3879573ef2c6c`.
- xorriso built a new image and confirmed `boot/provision.sh` inside it.
- An independent xorriso inventory matched all 1,412 regular files in the
  selected source paths exactly, including the documentation added for this
  record; no files were missing or extra.
- A real KVM boot with no virtual network or target disk reached the Proxmox
  graphical installer menu. The captured screen is
  `docs/verification/177/installer-boot.png`.
- No fake runner was run. No physical drive was written, and no native cold
  boot or installation was performed.

## Consequences and remaining work

The build remains reproducible through `baseline/bin/baseline-build-iso` with
the publisher source ISO. Publishing the image hash is done alongside the ISO
because embedding an image's own final hash inside that image would be
self-referential. This record does not close v0.2 work-queue row 72: physical
installation, the complete firstboot flow, and the graphical Proxmox GUI after
installation remain open.
