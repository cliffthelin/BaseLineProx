# Decision record: SUBSTRATE_PERSISTENCE volume added; every shared/persona volume moves from a single "desired size" to a real (min_gb, max_gb) range

Status: **implemented and fully unit-tested (1476/1476 full suite).
Not yet run for real against any live drive - the real machine this
was scoped against (`/dev/sdd`'s existing `pve` VG) has only ~16GiB
genuinely free, below the new combined real minimum (161GB across all
6 shared/default-persona volumes) - see "Real capacity finding" below.**

## What this resolves

Direct instruction, 2026-09-29: a new required volume
(`SUBSTRATE_PERSISTENCE`), plus concrete size defaults for every
volume this project's installer ever creates, given as explicit
numbers rather than left to this codebase's own adaptive guessing
("You seem really bad at sizing the volume so I will give you
defaults").

## SUBSTRATE_PERSISTENCE - a new, separate shared volume

Direct instruction: "Substrate Persistence is where all recovery
configurations and Substrate configurations not user hardware based
Persistence, Installer's admin's provided passphrase that is
encrypted." Deliberately separate from `BASELINE` (which holds real
app/VM/LXC *state*, not this kind of small, security-relevant
configuration data) and separate from any `USER_PERSISTENCE_<PERSONA>`
(explicitly *not* persona/user-hardware-based). Added to
`drive_installer.SHARED_VOLUMES` as `("baseline_substrate_persistence",
1, 1, "SUBSTRATE_PERSISTENCE", "/mnt/SUBSTRATE_PERSISTENCE")` - fixed
1GB, no growth ceiling above that (this volume's whole point is to
stay small, non-persona, and always-present). Mount options match
`INSTALLER_CACHE`/`SESSION_TEMP`'s existing `noexec` discipline -
config/recovery data only, never anything meant to run.

**Not yet done, flagged for a future pass, not silently assumed**:
`registry.py`'s existing `GLOBAL` scope currently still writes to
`/mnt/BASELINE/registry/foundation.db` - moving that onto the new
`SUBSTRATE_PERSISTENCE` mountpoint (a more architecturally honest home
for "recovery configuration," matching this record's own stated
purpose for the volume) was not done in this pass. The volume exists
and is created; nothing has been migrated onto it yet.

## Real (min_gb, max_gb) sizing model, replacing the old single "desired size"

Every volume definition (`drive_installer.SHARED_VOLUMES`,
`persona_volume()`) changed shape from `(lv_name, size_str, label,
mountpoint)` to `(lv_name, min_gb, max_gb, label, mountpoint)`, per
these direct defaults:

| Volume | min_gb | max_gb |
|---|---|---|
| BASELINE | 5 | 50 |
| INSTALLER_CACHE | 50 | 200 |
| SESSION_TEMP | 5 | 50 |
| SUBSTRATE_PERSISTENCE | 1 | 1 |
| USER_PERSISTENCE_\<PERSONA\> (each) | 50 | 200 |

`compute_adaptive_plan` was rewritten around this: every volume gets
its own `min_gb` first (refusing outright - every volume 0 - only if
real free space can't even cover every volume's combined minimum,
never a partial-minimum compromise); remaining space above that
combined minimum is handed out proportionally to each volume's own
room-to-grow (`max_gb - min_gb`), capped at its own `max_gb` - real
available space still wins between those two bounds, it just no
longer means "grow without limit." Documented honestly as a single
proportional pass, not a perfect bin-packing solve: a volume that
hits its cap early doesn't have its unclaimed share redistributed to
the others in the same pass.

`persist_bind_mounts.py`'s own local USER_PERSISTENCE self-install
fallback (`_local_fallback_size_gb`) updated to the same real (50,
200) range instead of its old hardcoded 300.

## Proxmox's own root sizing - a new "minimal" preset, now the default

Direct instruction: "ProxMox 5GB - Expandable to 50GB." Added a new
`self_installer.LVM_SIZE_PRESETS["minimal"]` entry
(`lvm_maxroot=5, lvm_maxvz=30, lvm_swapsize=2` - `maxvz`/`swapsize`
kept at `"small"`'s own already-real values, not guessed at, since the
instruction only specified root's own figure), made the new default
both in `build_and_write_self_installer`'s own plain parameter default
and in `settings_store.py`'s `self_installer.lvm_size_preset`
`SettingDef` (was `"medium"`). "Expandable to 50GB" is disclosed
honestly as a real, later `lvextend`+`resize2fs` action this project
intends to make against a live install - not something this preset
enforces by itself, and only practical if `lvm_maxvz` doesn't consume
the whole disk (why `maxvz` was left alone rather than shrunk further).

**Not addressed - "Boot: 1GB"**: there is no code path anywhere in
this codebase (`self_installer.py`'s `ANSWER_TEMPLATE`, or anywhere
else) that sets a boot/ESP/BIOS-boot partition size - Proxmox's own
installer fixes that internally and does not expose it as an
answer-file field. Said plainly here rather than silently dropped or
faked as "handled."

## Real capacity finding (not a code bug - real hardware state)

While verifying this end-to-end, `vgs`/`lvs`/`pvs` against this
session's own real machine showed `/dev/sdd`'s `pve` VG has only
~16GiB genuinely free. The new combined real minimum for just the 4
shared volumes plus the 2 default personas (admin+personal) is 161GB
(5+50+5+1+50+50). 16GiB is far below that - `compute_adaptive_plan`
now correctly, honestly refuses every volume in this exact real
scenario (see the new
`test_compute_adaptive_plan_refuses_every_volume_when_space_cannot_cover_every_minimum`
and `test_ensure_baseline_volumes_refuses_all_when_space_cannot_cover_every_real_minimum`
tests, which assert this directly). This means the
`create_volumes_on_existing_vg` web action, pointed at `pve` on this
real machine, will refuse rather than succeed until either more real
free space exists in that VG or the target changes - not yet verified
against a real drive with adequate free space.

## Files changed

- `baseline/lib/drive_installer.py` - `SHARED_VOLUMES`/`persona_volume`
  tuple shape changed; `MOUNT_OPTIONS["SUBSTRATE_PERSISTENCE"]` added;
  `compute_adaptive_plan` rewritten for the (min_gb, max_gb) model;
  `detect_existing_baseline_install`/`ensure_baseline_volumes`/
  `collect_volume_usage` unpacking updated for the new 5-tuple shape.
- `baseline/lib/persist_bind_mounts.py` - local fallback sizing call
  updated to the new (50, 200) range.
- `baseline/lib/backup_restore.py`, `baseline/lib/drive_admin.py` - the
  two other real callers that destructure `SHARED_VOLUMES`/
  `BASELINE_VOLUMES` tuples, updated for the new 5-tuple shape.
- `baseline/lib/self_installer.py` - new `"minimal"` LVM size preset,
  made the plain-parameter default.
- `baseline/lib/settings_store.py` - `self_installer.lvm_size_preset`
  default changed from `"medium"` to `"minimal"`; options list gained
  `"minimal"`.
- Tests updated across `test_drive_installer.py` (new dedicated
  SUBSTRATE_PERSISTENCE/range tests, plus every existing test whose
  fixed expectations depended on the old sizes/tuple shape),
  `test_drive_installer_telemetry.py`, `test_persist_bind_mounts.py`
  (new test capturing the real "16GiB is now below the new minimum"
  finding), `test_backup_restore.py`, `test_sensors_collect.py`,
  `test_self_installer.py`, `test_settings_store.py`,
  `test_dependencies.py`.

## Verification performed

- Full suite: 1476/1476 (was 1471 before this record's own additions).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- Not yet run for real against any live drive - see "Real capacity
  finding" above for why the obvious real target (`pve` on `/dev/sdd`)
  can't currently prove this end-to-end.
