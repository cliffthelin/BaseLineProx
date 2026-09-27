# Decision record: multi-persona USER_PERSISTENCE, admin elevation, and USB recovery trust - the concretely-testable foundation

Status: **implemented and tested (1139/1139 suite passing). Crypto
mechanics verified live against real openssl end to end. Not run
against real hardware; USB device-attach detection itself is not
built (see the work-queue's item 24).**

## Direct instruction, synthesized across several messages

This session's real recovery-mode/multi-persona architecture, as
specified directly across a sustained exchange:

- "More than one User persistence should be allowed... like a
  different Proxmox account. The intent here is if I want an admin
  user or a work account or personal account or a torrenting/risky
  account the data in each is not at risk for the other."
- "yes default creator is the the admin and default User persistence
  is the the admin. However the admin account should be like root and
  not the daily driver. So start with spinning up two user persistence
  volumes admin and personal; the other accounts are opt-in."
- "The longest connection between users counts for other than the
  admin is 24 hours... 24 hours is the default limit not one hour."
- "Admin has open access to each and an additional passphrase. This
  is to add an extra guard from it being primary target to get access
  to all accounts. its essentially sudo or root."
- "Without credential this is essentially guest access. without
  Proxmox credential no proxmox changes are allowed and extremely
  reduced visibility no logs and no added tools."
- "So a usb or tether to a previously set as a trusted physical
  device... it must store multiple identifiers as well have a
  recovery token... not internet dependent and actually need
  protection from any internet or network attempt to spoof this."
- "Group what you can test and know what to test now, add more items
  into to do and make tests for as appropriate."

## What was built

**`drive_installer.py` generalized from a single `USER_PERSISTENCE`
volume to `USER_PERSISTENCE_<PERSONA>`, one per persona** -
`SHARED_VOLUMES` (BASELINE/INSTALLER_CACHE/SESSION_TEMP, never
persona-scoped) + `persona_volume`/`baseline_volumes_for`.
`DEFAULT_PERSONAS = ("admin", "personal")`. `mount_options_for`
matches any `USER_PERSISTENCE_*` label by prefix. `ensure_baseline_volumes`/
`detect_existing_baseline_install`/`collect_volume_usage` all take an
optional `personas` tuple for opt-in additional personas.

**`settings_store.py`** - the generic, schema-driven mechanism behind
the eventual "Admin" settings tab (potentially hundreds of settings,
per direct instruction - this is the seed schema, not the ceiling).
Real groups (`sessions`, `startup`), real defaults
(`default_session_ttl_hours`=24, `admin_session_ttl_hours`=24 -
corrected from an earlier, wrong 1-hour guess -
`admin_elevation_ttl_minutes`=15, `auto_start_persona`="personal").
Lives on BASELINE (shared, system-level, survives a reinstall).

**`admin_elevation.py`** - the real cross-persona "sudo" gate. A
separate passphrase from admin's own login, granting a short-lived
ticket (15-min default, drawn from `settings_store`) rather than a
standing permission - a compromised admin session alone still can't
reach another persona's data without the elevation passphrase having
been entered recently.

**`recovery_tiers.py`** - pure authorization model. Proxmox and
USER_PERSISTENCE credentials are independent axes (proven directly,
not assumed): `allowed_actions(proxmox_authenticated, persistence_authenticated)`
always includes the guest floor (`view_login_screen`/`view_recovery_screen`),
and only the axis actually proven unlocks its own real actions
(`proxmox_changes`/`view_logs`/`use_added_tools` vs.
`read_user_persistence`/`write_user_persistence`).

**`recovery_trust.py`** - real Ed25519 challenge-response, the
"backdoor" for recovering a persona with no credential to check
against at all (a missing/corrupted volume has no password store).
Enrollment writes a real private key to the trusted device's own
storage and records the public key plus multiple real identifiers
(device serial, persona, an install-id unique to this installation) in
a manifest on INSTALLER_CACHE - a different volume from the one being
recovered, so the manifest survives exactly the scenario where
USER_PERSISTENCE is gone. Recovery signs a fresh, single-use random
challenge and verifies against the recorded public key - a captured
old signature is useless against a new one. Structurally not
internet-dependent and immune to network spoofing: every function is
local file I/O and `openssl` subprocess calls, never a socket - there
is nothing for a remote attacker to talk to, by construction, not
policy.

**`drive_installer.seed_installer_cache_with_baseline`** - "make
BASELINE the first thing added into the installer_Cache": reuses
`backup_restore.create_backup` directly to seed INSTALLER_CACHE with a
real backup of BASELINE's own current content.

## Verified live, not just against fakes

Ran the full real enroll -> find -> sign -> verify round trip against
actual `openssl` on this dev machine: a real Ed25519 keypair generated,
a real device correctly found by its three-field manifest match (and
correctly *not* found under a wrong persona), a real signature
produced, verification succeeding against the correct challenge and
**failing** against a tampered one - genuine cryptographic proof, not
assumed from the argv shape alone.

## What this does not do (real, tracked follow-up - work-queue items 24-29)

- No real USB block-device attach detection wired in yet - the crypto
  mechanics are proven; matching a real connected device to a manifest
  entry via `udev`/`lsblk` needs real hardware to test against.
- `persist_bind_mounts.py`/`settings_web.py`/`scripts_inbox.py`/
  `control_panel_web.py` are not yet persona-aware - each still
  assumes a single active persistence volume. Real, separate follow-up,
  blocked on deciding the persona-switching UX first.
- Recovery mode itself (real entry/exit, userless discovery UI,
  SESSION_TEMP-scoped working state) is not built - this record is its
  concretely-testable foundation, not the mode itself.
- No automated recurring encrypted backup job yet (decision record
  74's own flagged follow-up) - blocked on deciding which device
  counts as "the separate one" now that multiple personas exist.
- No settings-tab UI surface yet - `settings_store.py` is real storage
  with no renderer in front of it.
- The full TDD audit the user asked for explicitly waits until the
  items above land.

## Verification performed

- `settings_store.py`: 13 tests (defaults, overrides, per-group
  isolation, unknown-key refusal, BASELINE storage location).
- `admin_elevation.py`: 9 tests (grant/expire/revoke, the default and
  a configured TTL, present-tense re-checking).
- `recovery_tiers.py`: 12 tests (every combination of the two
  independent credential axes, the guest floor always present).
- `recovery_trust.py`: 17 tests against a dedicated fake (argv shapes,
  multi-field manifest matching, replacement-not-duplication on
  re-enrollment) plus a real end-to-end smoke test against actual
  `openssl` proving genuine sign/verify/tamper-detection.
- `drive_installer.py`'s persona refactor: 49 tests updated/added
  (admin+personal volume set, adaptive sizing with the new label
  scheme, telemetry, the new seeding function) - one unrelated real
  regression caught and fixed in the same run: a "persistance" typo
  quoted verbatim from the user's own message in decision record 74's
  prose tripped a pre-existing typo-guard test
  (`test_no_persistence_typo.py`) - reworded, not a rewrite of any
  finding.
- Full suite: 1139/1139 passing, no regressions.
