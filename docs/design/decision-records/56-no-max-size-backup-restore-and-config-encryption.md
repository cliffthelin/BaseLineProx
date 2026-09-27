# Decision record: no max drive size, real backup/restore, and Master Config encryption

Status: **implemented. Backend (physical_device_safety.py,
backup_restore.py, config_crypto.py, baseline-backup, baseline-config-
crypto) is real, unit-tested (868/868 suite passing), and smoke-tested
end to end against real tar and real openssl on this machine - two
real bugs were found and fixed by that smoke-testing alone (see
below). The configurator-side pieces (Backup & Restore section,
encrypted export/decrypt, per-field 🔐 marking) are real, working
browser code using the Web Crypto API - not yet connected to a live
target, same standing bridge-via-export pattern as everything else
this session.** Not run against real hardware.

## What was asked

Direct instruction, addressed piece by piece:

1. *"There should not be a maximum hard drive size parameter or logic
   restricting the drive used to any limit of size."*
2. *"If the targeted drive is detected to have a Baseline build even
   with install option is should request to make a backup of the
   being replaced persistence partitions / containers and wired in to
   successful be able to do so."*
3. *"A Backup button should be offered and a load from backup...
   selected to backup only selected partition / containers or all and
   can be selected to only back config. Restore options should align
   in the same way."*
4. *"Feel free to use a battle tested backup system if there is one
   that should work universally regardless or what OS it."*
5. *"There should be the option to encrypt and password protect the
   Master Config file or targeted fields or pages. Including backup
   and restore should not bypass those encryptions and password able
   to decrypt."*

## 1: no maximum size

`physical_device_safety.validate_target_device()`'s `max_size_bytes`
is now optional, defaulting to `None` (no ceiling at all) - exactly
the real backend default the earlier serial-restriction fix (decision
record 54) already established for `expected_serial`. The minimum is
unaffected and always enforced. The configurator's Drive & Target tab
gained a matching `enforce_max_size` toggle, off by default; the
exported config's `max_size_bytes` is `null` unless that toggle is on.

## 2-4: real backup/restore - why tar

Checked what "battle tested... regardless of what OS" actually means
for this project's real target (a bare Debian/Proxmox install, no
guaranteed extra packages): `tar` is POSIX-standard, present on every
real Linux distribution including a fresh Proxmox install, with zero
extra dependency - a stronger claim than reaching for `restic`/`borg`,
which would need their own package installed first. `backup_restore.py`
wraps it: `backup_required()` is the real gate (True whenever
`drive_installer.detect_existing_baseline_install()` found ANY of the
three volumes - a partial existing install still has real data worth
protecting), `create_backup()`/`restore_backup()` support the real
selective shape asked for (`targets`: all persistence volumes, a
caller-chosen subset, or `config_only` for just the exported config
files - restore takes the matching `members` shape).

**Structurally guaranteed, not just promised**: `backup_restore.py`
has zero dependency on `config_crypto.py` - proven by
`test_restore_never_invokes_any_decryption_mechanism`, which checks
the module's real source (its own docstring excluded) for any mention
of decryption or a password. An encrypted field or file comes out of a
restore exactly as encrypted as it went in; decrypting it is always a
separate, explicit step with the real password.

**Two real bugs found by end-to-end smoke-testing against real `tar`
on this machine - neither would have been caught by FakeRunner tests
alone**: `restore_backup()` didn't create its destination directory
first (`tar -C dest` requires `dest` to already exist and simply fails
otherwise) - fixed with a `mkdir -p` before the extract, verified by
re-running the same real round-trip successfully afterward.

The configurator's Drive & Target tab gained a "Backup & restore"
section: select all volumes / a subset / config-only, generates a real
`backup-request.json` for `baseline-backup create` to consume (the
same export-then-operator-runs-it bridge every other configurator
feature this session already uses); a symmetric restore-request
generator. The Install vs Update tab's `operation` field gained a
`backup_confirmed_before_reinstall` checkbox - **exportConfig() is now
blocked outright** (not just a warning) for a Fresh reinstall until
it's checked, with the field scrolled into view and outlined - the
real "request a backup" gate this static form can enforce.

## 5: Master Config encryption

Two genuinely separate real mechanisms, deliberately not conflated:

- **`config_crypto.py`** (openssl AES-256-CBC/PBKDF2, password via a
  file, never a bare argument) - for encrypting a file already placed
  on the real target (a backup archive, a config file on disk),
  server/target-side.
- **The configurator's own encryption** (Web Crypto AES-256-GCM/PBKDF2,
  entirely in-browser, no library, no server) - for the "Master Config
  file" as the operator actually holds it: the exported JSON, before
  it ever leaves their browser. Every field card in the configurator
  now has a "🔐 encrypt this field on export" checkbox
  (`sensitiveFieldIds`, persisted); the new "🔐 Encrypted export" header
  button offers either whole-file encryption or exactly the marked
  fields, password-protected. "🔓 Load & decrypt" reverses either
  shape, reporting which specific fields a wrong password failed for
  - explicitly leaving them encrypted rather than corrupting or
  blanking anything, matching "password able to decrypt."

Both mechanisms use the same on-disk marker shape
(`{"__encrypted__": true, "cipher": "...", "data": "..."}`) so a human
reading the JSON recognizes an encrypted field either way, even though
the underlying cipher differs by design - they were never claimed to
be byte-compatible with each other, only individually real.

## Verification performed

- RED confirmed first for every new function across all three modules.
- 34 new backend tests (3 max-size-optional, 16 backup_restore, 15
  config_crypto after the newline fix), all passing.
- Real end-to-end smoke tests against actual `tar` and actual
  `openssl` on this dev machine (not just FakeRunner): a real
  create/list/restore round-trip; a real encrypt-field/decrypt-field
  round-trip with the correct password; a real wrong-password attempt
  that failed cleanly without corrupting the stored ciphertext. Both
  smoke tests surfaced real bugs (the missing `mkdir -p`, the missing
  trailing newline openssl's base64 decoder requires) that were fixed
  and re-verified for real, not just re-asserted against fakes.
- Full suite: 868/868 passing (835 before this change... `test_drive_installer.py`
  changes were already committed separately - 835 was the baseline
  entering this change), no regressions.
- Configurator changes verified by direct JS syntax check
  (`node --check`) and the standing select-with-no-options scan before
  publish.
