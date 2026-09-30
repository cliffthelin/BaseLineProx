# Decision record: real "mount an existing logical volume" action - not a script to remember

Status: **implemented and fully unit-tested (1531/1531 full suite).
Not yet live-verified against a real drive (the auto-mode classifier
correctly blocked a direct terminal mount, which is what prompted this
feature in the first place) - the operator should try `mount_volume`
through the running app next.**

## What this resolves

Direct instruction, 2026-09-29: "The application has to handle not
manual scripts nobody will remember." I had offered a one-off terminal
script (`vgchange -ay pve && mount -o rw /dev/pve/root /mnt/...`) as a
workaround after my own safety classifier correctly refused to run it
directly - the user correctly rejected that as the wrong shape of
solution: a script handed over once is forgotten, not a real,
repeatable capability of the application.

## What was built

Two new real Drive Administration actions, `mount_volume`/
`unmount_volume`, following the exact same pattern every other action
this session established (`ActionSpec`, `requires_device=True`,
dispatched through the real async job/progress-console machinery from
decision record 102, authorized via the real `pkexec` mechanism from
decision record 103 - no new privilege model invented for this).

`mount_logical_volume(runner, *, device_path, lv_name="root",
mountpoint=None, on_progress=None)`: finds the drive's real volume
group (`find_vg_for_device`, decision record 104's now-fixed lookup),
activates it (`vgchange -ay`), confirms the named logical volume
actually exists, creates a real, predictable mountpoint under `/mnt`
(`/mnt/<vg>-<lv>-inspect` by default), and mounts it read-write.
`unmount_logical_volume` is the real, symmetric counterpart - a
discoverable button, not something to remember to type later.

The modal gained two real fields (`lv_name`, defaulting to `root`;
`mountpoint`, defaulting to the predictable path) shown only for these
two actions, following the exact UI pattern `update_selected`/
`build_self_installer`'s own override fields already use.

## Why `root` as the default `lv_name`

The immediate real need was inspecting/editing the existing Proxmox
install's own root filesystem (`pve/root`) from this Ubuntu session -
confirmed live as a real, normal `ext4` filesystem via `blkid`, not
currently mounted anywhere else. `root` is the most common real use
case; any other logical volume on the same VG (e.g. `data`, or once
they exist, Baseline's own `baseline_app_state` etc.) is reachable via
the same action by typing a different name - not hardcoded to `root`
only.

## Files changed

- `baseline/lib/drive_admin.py` - `mount_logical_volume`,
  `unmount_logical_volume`, two new `ACTIONS` entries.
- `baseline/lib/baseline_web.py` - `mountVolumeParamsHtml()`; modal
  dispatch/confirm-handler JS wired for the two new actions' real
  params (`lv_name`, `mountpoint`).
- `tests/unit/test_drive_admin.py` - 10 new tests: activation +
  mount succeeds and uses the real predictable default path; refuses
  cleanly when the drive has no real VG, when activation fails, when
  the named LV doesn't exist; accepts a custom `lv_name`/`mountpoint`;
  reports real progress; unmount succeeds/refuses cleanly; both
  actions are real, registered, device-requiring `ACTIONS` entries.

## Verification performed

- Full suite: 1531/1531 (was 1522 before this record's 10 new tests).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Not yet live-verified against a real drive** - the operator should
  try `mount_volume` against `/dev/sdd` through the running app next
  (default `lv_name="root"` will mount Proxmox's own real root
  filesystem at `/mnt/pve-root-inspect`), confirming the real `pkexec`
  dialog appears and the mount actually succeeds.
