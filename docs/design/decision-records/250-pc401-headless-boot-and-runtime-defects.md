> Imported 2026-10-11 from the parallel (Codex) effort, where this record is DR246. Numbered DR250 here so it does not collide with this branch's DR245-248. Other DR numbers inside the text refer to that effort's numbering.

# DR250 (parallel effort DR246) — PC401 headless boot and runtime defects

**Status:** QEMU boot completed; network/runtime acceptance failed  
**Date:** 2026-10-10

## Scope and storage safety

PC401 serial `<PC401 drive serial>` was launched headlessly with its raw block
device as a qcow2 backing file. The overlay, screenshots, downloaded signed
Ubuntu `inxi` package and live output are retained on
`/mnt/10TB/backup/baseline-tests/pc401-headless-20261010`. QEMU writes landed in
that overlay. The guest was shut down through ACPI; `qemu-img check` found no
errors. PC601 serial `<PC601 drive serial>` was not used. This is virtual execution
of the installed physical source, not native cold boot on the other machine.

## Observed boot/runtime result

The guest booted through GRUB and showed Proxmox's console welcome and Baseline's
TUI. Its welcome displayed a link-local IPv6 URL only. A loopback-only forward
from host port 25948 to guest TCP 8006 timed out; QEMU's user-network table
showed the connection stuck in `SYN_SENT` toward `10.0.2.15:8006`. The NIC used
`restrict=on`. This does not prove an internet path, a working Proxmox browser
GUI, firewall policy, LAN connectivity, workload launch or persistence.

The firstboot console required the literal `CONFIRM` input. A QEMU monitor
key sequence supplied it to continue this overlay-only test. That automated
input is not independent operator confirmation and is not physical acceptance.
Repeated `baseline-scripts-inbox.service` failures were visible during the
boot. No guest login credential was available or attempted, so the service's
journal and root cause remain unknown.

## Defects repaired in source

The Baseline Hardware TUI showed `invalid inxi inventory: inxi section has an
invalid shape`. The signed Ubuntu archive package `inxi 3.3.40-1-1` was
downloaded without installing it on the host. Its live JSON output contains
nested string lists in the `Repos` section, interleaved with dictionary
entries. The strict parser rejected those valid records and the inventory view
discarded them. `_validate_raw` now validates that section's nested strings,
and `full_inventory` renders them as repository rows. The production collector
ran against the real command output after the repair: 15 sections, 17
repository rows, schema version 1 and no collector error. No FakeRunner or
FakeProc was used for this live collection.

The firstboot prompt's `REAL-012` line said staging inspection was unavailable
and state unknown. There is no defined staging contract in this flow, so the
operator-facing status field was removed rather than implying a real
inspection. The firstboot confirmation gate and network/package actions remain
unchanged. Setup-intent bundle staging/consumption is still outside this flow.

## Tests and remaining work

The two new inxi-shape regression tests failed before the parser repair. The
firstboot proposal regression failed before removing `REAL-012`. The focused
hardware inventory/schema, TUI and truthfulness suites passed afterward: 113
unit tests. The source-staging regression used the real filesystem runner and
failed before the fix; it passed afterward. The stale empty-PCI/block/network
test was aligned with DR239's already-accepted contract, while empty USB remains
valid. Existing unit suites include fake-runner checks; they remain separate
from the live inxi collection, real ISO build, inventory comparison and KVM
boot evidence.

The ISO builder was rerun from current source. Its refreshed artifact is
`/mnt/10TB/backup/baseline-tests/pc401-headless-20261010/BaselineOS-platform-20261010-r246.iso`,
SHA-256 `4796b736c9f833ea30e6d8019c1a142effe1f8dd2d41812e2c51381f6c60563c`.
Independent xorriso inventory matched 985 expected files exactly, with zero
missing, extra or `.pyc` files. The packaged `hardware.py` was extracted and
byte-compared with the fixed repository file. A headless KVM boot with no
network or target disks reached the Proxmox VE Installer GUI, which displayed
“No Hard Disk found!” as expected because no target was attached. The captured
screen is `iso-installer-screen.png` in the evidence directory. This proves the
ISO reaches the installer interface, not that an installation completes.

These code changes are in the repository source only. PC401 has not yet been
rebuilt or updated with the inxi parser fix. The live QEMU guest still lacks a
verified IPv4/internet path, and Proxmox HTTPS 8006 is unreachable in this test.
Native cold boot, physical NIC/DHCP, firewall, browser GUI, service health,
drivers and retained overlay/user-data behavior remain open under queue row78
and the independent-drive checklist. DR245's guarded physical update remains
valid; this record adds virtual boot findings without changing its claim.

Evidence directory on the backup drive contains selected QEMU framebuffer
captures, the qcow2 overlay, the refreshed ISO/hash, the `inxi` package and
live JSON output, and a manifest with exact scope and results. The directory also contains build staging, extracted package files, duplicate
raw framebuffer captures and a comparison copy (about 1.8 GiB of staging data).
A cleanup command was rejected by the command safety layer before execution;
these artifacts remain untouched.
