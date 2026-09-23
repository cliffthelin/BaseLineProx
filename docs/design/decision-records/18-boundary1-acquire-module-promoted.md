# Decision record: Boundary 1 (`drive_setup_acquire.py`) promoted from decision record 01's ad hoc commands to real, tested production code — Gate B work begins

Date: 2026-09-22
Investigator: Claude Code
Status: complete. `baseline/lib/drive_setup_acquire.py` reproduces decision record 01's GPG-signed-`Release` -> hash-pinned-`Packages` -> hash-pinned-`.deb` chain as real, `Runner`-injectable, unit-tested code. Verified twice: 11 `FakeAcquireRunner`-scripted unit tests (98/98 total passing), then for real against Proxmox's actual live repository — full chain success, extraction confirmed, no host package database touched.

## Scope discipline

No push to `cliffthelin/baseline`. No physical device. No host package installation (`dpkg-deb -x` extracts without touching `dpkg`'s database — confirmed directly, before/after). No privilege escalation. No authorization-triggering host call. Real network access to Proxmox's own public repository (a read-only GPG/hash verification chain, not a write or an account action) — the same kind of access decision record 01 already used without objection.

## What was built

`baseline/lib/drive_setup_acquire.py`: an `AcquireRunner` injectable boundary (deliberately separate from `repair.py`'s own `Runner` - that one is scoped to text-based interfaces-file editing; this one is scoped to binary artifact fetch/verify/extract, a different domain), plus:

- `verify_release_signature` - `gpgv` against the fetched keyring, the actual trust anchor (TLS is not, per decision record 01's own finding that `download.proxmox.com`'s cert doesn't match its hostname from this network path).
- `find_release_hash` - parses a Release file's `SHA256:` block to find the pinned hash for a given relative path.
- `parse_packages_index` - Debian control-file format, returns every version of a named package so the caller picks which one it wants (matching decision record 01's observation that multiple versions coexist in the index).
- `acquire_and_verify` - the full orchestrated chain, stopping immediately at the first failed step; a later step is never attempted against unverified input (bad signature stops before `Packages.gz` is even fetched; a bad `Packages` hash stops before the `.deb` is fetched).
- `extract_deb` - `dpkg-deb -x`, confirmed not to touch the host's own package database.

## Real verification, not just unit-tested

Ran the module for real against `download.proxmox.com`'s actual live repository (a disposable workspace under `experiments/`, deleted afterward):

- Fetched the real keyring, `Release`, `Release.gpg`.
- `gpgv` succeeded for real: `gpgv: Signature made Mon 21 Sep 2026 03:30:14 AM MDT ... Good signature`.
- Fetched real `Packages.gz`, hash matched the live `Release` file's own pinned value.
- Located `proxmox-auto-install-assistant` 9.2.8 in the live index.
- **First attempt failed** — caught a real bug, not a false pass: the downloaded ".deb" was actually a 404 HTML error page (`<html><head><title>404 Not Found</title>...`), because the test call's `mirror_base_url` was wrong (passed `.../dists/trixie`, but the Packages index's own `Filename` field is already relative to the repo root and includes `dists/trixie/...` itself — a doubled-path caller error, not a module defect). **The hash-verification step correctly refused to accept it** — `deb_hash` failed exactly as designed, rather than silently proceeding with a wrong file. This is the mechanism working as intended, caught on its very first real use.
- Corrected the caller's `mirror_base_url` to the actual repo root and re-ran: full chain succeeded, `deb_hash` matched.
- Extracted via `dpkg-deb -x`; `dpkg -l | grep proxmox-auto-install-assistant` confirmed empty both before and after; `--version` reported `proxmox-installer-common v9.2.8`, exactly matching decision record 01's own finding.

## Tests added

`tests/unit/test_drive_setup_acquire.py`, 11 tests, all `FakeAcquireRunner`-scripted (no real network/gpg/dpkg-deb in the test suite): full chain success; stops at bad GPG signature (and never fetches `Packages.gz` afterward); stops when the `Packages` hash doesn't match `Release`'s pinned value (and never fetches the `.deb` afterward); stops when a downloaded `.deb`'s hash doesn't match the verified index (the tampered-content case, mirroring the real 404 bug found above); stops when a requested version isn't in the index; stops cleanly on a network failure at the very first step; `Packages` index parsing returns every matching version; `Release` hash lookup finds a pinned path and correctly returns `None` for an unlisted one; extraction never issues an install-style command and correctly reports a `dpkg-deb` failure.

## Security implications

The real-run failure is itself a small, useful confirmation of this module's actual security property: it does not trust a successful HTTP fetch as proof of correct content — every fetched artifact is independently hash- or signature-verified before being used for the next step, and a mismatch (whatever its cause — tampering, a wrong URL, a stale mirror) is refused rather than silently accepted.

## Whether Gate B work is unblocked

Yes for this piece. Boundary 1 is done, real-verified. Gate B's own evidence requirement ("Prepared ISO verified without booting - `inspect-iso` output and a raw byte scan confirm fetch mode, URL, cert fingerprint, and the absence of forbidden strings") additionally needs boundary 2 (`drive_setup_answer.py` - credential generation, the ephemeral answer server, `prepare-iso`'s defensive wrapper) promoted the same way before Gate B itself can be attempted end-to-end. That work continues next, not attempted in this record.
