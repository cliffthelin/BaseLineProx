# Archived: USB challenge-response recovery trust

Status: **removed from the active codebase by direct decision - "We
decided not to do the usb recovery option."** Archived here verbatim,
not deleted outright, in case this exact design is wanted again later.

## What this was

A real, working Ed25519 challenge-response mechanism (`recovery_trust.py`
+ `test_recovery_trust.py`) for recovering access to a specific
persona's `USER_PERSISTENCE` when there is no credential to check
against at all - a missing/corrupted volume has no password store.
Built in decision record 76, alongside the multi-persona
`USER_PERSISTENCE_<PERSONA>` model, `settings_store.py`,
`admin_elevation.py`, and `recovery_tiers.py` - those four are
unaffected by this removal and remain active.

Design summary: enrollment writes a real private key to a trusted
USB storage device's own filesystem; a manifest recording the public
key plus multiple real identifiers (device serial, persona, an
install-id unique to the installation) lives on `INSTALLER_CACHE` - a
different volume from the one being recovered. Recovery signs a
fresh, single-use random challenge with the device's private key and
verifies against the recorded public key. Every step is local file
I/O and `openssl` subprocess calls, never a network operation - the
design was explicitly meant to be structurally immune to remote
spoofing, not just policy-immune.

It was real and tested: 17 unit tests against a dedicated fake, plus a
genuine end-to-end smoke test against actual `openssl` on the dev
machine (real keygen, real signing, real verification succeeding on
the correct challenge and failing on a tampered one - see decision
record 76 for the full verification record).

## Why it was removed

Direct instruction: "We decided not to do the usb recovery option if
you were thinking that was blocking the recovery mode." Recovery mode
itself was never actually blocked on this piece in the work queue
(item 26 was blocked on item 25 and a UI decision, not on item 24) -
but the USB mechanism itself was withdrawn as a feature, not merely
deprioritized. This module was never wired into `provision.sh` and had
no other real dependents (confirmed via `grep` before removal), so
removing it has zero ripple effect on anything else built this
session.

## If this is wanted again

The two files in this directory are the exact, working, tested code as
it stood at removal (matching git commit `854db50` / decision record
76). Copy them back to `baseline/lib/recovery_trust.py` and
`tests/unit/test_recovery_trust.py`, confirm the full suite still
passes, and pick up the real, still-open follow-up noted at the time:
real USB block-device attach detection (`udev`/`lsblk` enumeration)
was never wired in - only the cryptographic mechanics were proven.
