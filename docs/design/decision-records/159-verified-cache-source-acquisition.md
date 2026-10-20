# DR159 — Web cache acquisition and Ubuntu base provenance

Date: 2026-10-04. Status: accepted implementation boundary.
Continues the installer acceptance checklist, queue72/74/76/78 and DR158
installer-input-preparation. Does not complete the seven installation outcomes.

Installer Cache now has an options-first source selector and Acquire / verify
selected source action, plus an authenticated download link to the actual file.
The currently supported acquisition is the existing pinned Ubuntu 24.04 cloud
image. The worker is a native RealRunner production job, same-origin authenticated
and signed, durably recorded and request-deduplicated. The handler creates no VM,
formats no drive and executes no installation stages. Other publisher acquisition,
Proxmox ISO verification, assistant lock integration and package closure remain open.

The cache must be an exact findmnt-reported mounted filesystem with a UUID and
INSTALLER_CACHE label. Plain root directories and symlink redirects are refused.
The cache identity is rechecked before publication. Download writes use an open
cache file descriptor, avoiding root-filesystem fallback if the mount disappears.
A verified file is atomically published without replacing any existing bytes;
bad partial downloads are removed. Existing files must match the publisher SHA256.
Installer Plan preparation automatically resolves the actual pinned cache source
and reports cache mount/identity failures. Download links recheck bytes.

Native VM Ubuntu preparation uses the same acquisition handler. Imported base
images now get source and resulting-image SHA256 receipts. Reuse refuses missing,
mismatched or changed receipts/images instead of blindly trusting existence.
Existing unknown bases are not overwritten; their established guests are not
changed. This may refuse preparation of legacy bases lacking a receipt, which
requires independent verification/reimport rather than an invented trusted result.

Canonical's actual HTTPS checksum list was rechecked and matches the existing
6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2 pin:
https://cloud-images.ubuntu.com/releases/noble/release-20260926/SHA256SUMS
This proves the publisher metadata observation, not a completed cloud-image
download or detached-signature verification. The latter remains explicitly false.
Corrected the catalog's claim that drive_setup_acquire verified the Proxmox ISO:
that chain verifies the assistant package, not the ISO. Publisher domain retained.

TDD RED confirmed missing HTTP/catalog controls, unverified-base reuse, missing
receipts, source routing, symlink redirects and unstable output paths before fixes.
Unit/HTTP tests use injected test-only cache metadata and downloaded bytes; no
fake production runner. Actual temporary SQLite/files and HTTP responses were
checked. Real Chromium exercised source selection, submit/status and file link
against fixtures. Actual qemu-img created/converted/checked a disposable image;
its receipt passed and changed-image reuse failed. Actual Linux findmnt refused
an ordinary temporary directory before source writes. No guest boot or physical
target action. Full final suite: 3364 passed, no failures/skips/deselections. Focused affected
checks: 140 passed. Production web reload PID1598679 serves login HTTP200 with
same-origin policy. Evidence is in INSTALL.md and verification/159. Earlier decision records remain history.
