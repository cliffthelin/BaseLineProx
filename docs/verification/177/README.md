# Rebuilt platform ISO verification

Artifact: `iso_build/BaselineOS-platform-20261010.iso`

This is a newly remastered Proxmox VE 9.2-1 ISO containing the current
BaselineOS platform under `/baseline-src`. Source ISO SHA-256:

`4e88fe416df9b527624a175f24c9aa07c714d3332afb1ee3dbf3879573ef2c6c`

The payload includes `boot/`, `baseline/`, `packaging/`, `automation/`,
`docs/`, `tests/`, `tools/`, `README.md`, and `AGENTS.md`. Independent xorriso
enumeration matched all **1,412 regular files** in these source paths exactly:
zero missing and zero extra files. The builder independently confirmed the
output exists, is larger than the source image, and contains
`/baseline-src/boot/provision.sh`.

A real QEMU/KVM boot with networking and target disks disabled reached the
Proxmox VE 9.2 graphical installer menu. The screen capture is
[`installer-boot.png`](installer-boot.png). This proves boot to the installer
menu in KVM. It does not prove an install, Baseline firstboot, a physical-drive
write, native cold boot, or the post-install Proxmox browser GUI. No fake
runner was used for the build or its real-filesystem staging check.

The final ISO's SHA-256 is reported beside the artifact because storing an
image's own final checksum inside itself would change that checksum.
