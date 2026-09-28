# Decision record: merged Baseline web app + Drive Administration tab, real privilege via password modal

Status: **implemented, tested, and staged for real deployment (1282/1282
suite passing). Verified live against real attached hardware in this
dev session (12 real drives correctly enumerated/classified); the
actual privileged actions have not been exercised as root on real
hardware - deliberately, see below.**

## Direct instructions, in sequence

1. "merge those two together and add a Drive administration tab and
   add all of the things that we would want to consider and make them
   require SUDO password through standard Ubuntu designs. Then run the
   web app with what you want to do have it give modal for what is
   being authorized to change with the sudo request... this
   application will never get off the ground if your solution is
   terminal commands."
2. "good start, give the drive type if its HDD,SSD,NVME,USB, or Other.
   Give the brand and model of the identified Drive. But before all of
   that first you need to actual be able to select the drive and if
   determined elsewhere the target then that is default but not locked
   to just that drive"
3. "As a human i do not want to see serial numbers"
4. "Dark mode only uses light to medium colored fonts. absolutely
   NEVER dark colored fonts" / "That is not dark mode" (after an
   initial fix switched to light mode instead of a real dark theme)
5. "Are you making a fake root password or are you using my actual
   password?" - a direct, pointed question that surfaced two real bugs
   in the same turn it was asked (see below).
6. "yes, continue with production wiring."

## What was built

**`baseline/lib/drive_admin.py`** (new) - real Drive Administration
actions, all Runner-injectable, no real device ever touched by a
test:
- `list_candidate_drives` - real `lsblk -d -n -P -o
  NAME,SIZE,MODEL,TRAN,ROTA,SERIAL,TYPE` enumeration of every attached
  block device, `-P` (key="value" pairs) specifically because MODEL
  strings routinely contain spaces. Excludes the machine's own boot
  device by construction (via `physical_device_safety.get_boot_device_serial`,
  never re-derived).
- `classify_drive_type` - HDD/SSD/NVMe/USB/Other. Real finding this
  project's own two target drives exposed: their USB-NVMe bridge chips
  report `ROTA=1` (rotational) for genuinely solid-state media - `ROTA`
  is trustworthy only on a direct, non-USB transport. Classification
  checks the model string for an explicit NVMe/SSD claim first
  (trustworthy regardless of transport), only trusts `ROTA` off USB,
  and reports "USB" honestly - never guessing HDD or SSD - when a
  USB-attached device gives no real hint either way. Verified against
  all 12 real drives on this dev machine, correctly classifying an
  NVMe-behind-USB-bridge as NVMe (model string), a Samsung 980 PRO as
  SSD, and three real external Seagate/WD drives as the honest "USB"
  fallback since their model strings give no media-type hint.
- `resolve_target`/`rebuild_persistence_lvm`/`create_baseline_volumes`/
  `switch_persona`/`apply_volume_mode` - real actions. Critically,
  `resolve_target` takes an operator-selected `device_path`, validated
  via `physical_device_safety.validate_target_device` with **no
  serial restriction** - per that module's own already-documented,
  direct-instruction design ("Expected serial doesn't seem like it
  should be forced... Default is not and I do not want it
  restricted"). `DEFAULT_TARGET_SERIALS` (this project's two
  pre-authorized drives) only marks which candidate the picker
  pre-selects - never which ones are accepted. Directly answers
  "not locked to just that drive."
- `apply_volume_mode` is the real enforcement half of decision record
  80's `volumes.*_mode` settings (storage-only when built) - reads the
  live setting and issues a real remount.

**`baseline/lib/baseline_web.py`** (new) - the merged server. Every
route is a thin dispatcher into `settings_web.py`/`control_panel_web.py`/
`drive_admin.py`'s own already-tested `handle_*` functions - this
module reimplements none of their logic, only composes them under one
`http.server.HTTPServer`, one shared nav bar, and the new Drive
Administration page.

**The sudo-password modal, and why no `sudo` subprocess is involved**:
`baseline.service`/`baseline-settings-web.service` (now
`baseline-web.service`) already run as root - no `User=` in either
unit. So the "sudo password" is a real *identity/intent* check, not a
technical privilege bridge: `settings_web.SystemPasswordVerifier`
reads `/etc/shadow` directly (not the stdlib `spwd` module, removed in
Python 3.13, the same real constraint this file's own `_sha512crypt`
already documents for `crypt`) and verifies the submitted password
against the real account hash via the same `_sha512crypt` technique
`FileBackedPasswordVerifier` already used. `SystemElevationVerifier`
adapts that two-argument `.verify(username, password)` login contract
to the single-argument `verify_fn(password) -> bool` shape
`admin_elevation.attempt_elevation` and the Drive Administration
action route actually call.

The modal itself (`render_drive_admin_page`'s JS) shows the exact
description text `drive_admin.ACTIONS` associates with the button
clicked - one source of truth, never a second copy that could drift
from what actually runs - then a password field, then `POST
/drive-admin/action`. The backend verifies the password before calling
`drive_admin.perform_action` at all; a wrong password never reaches
the action layer.

## Real bugs found by direct scrutiny, not code review

Asked plainly "Are you making a fake root password or are you using my
actual password?" while build was mid-flight - re-checking the answer
surfaced two real defects in the same turn, both fixed before this
record was written:

1. `SystemPasswordVerifier` implements `.verify(username, password)`
   (two arguments, the `PasswordVerifier` login contract) but was
   wired directly as `elevation_verify_fn`, which every caller
   invokes as `verify_fn(password)` - a single argument. As wired,
   this would have raised `TypeError` the first time anyone actually
   tried it, not silently passed or failed - but it had never been
   exercised end-to-end before the question was asked. Fixed by adding
   `SystemElevationVerifier`, a real adapter bound to one specific
   username.
2. `describe_actions()` never included `requires_device` in its
   output dict at all, despite `ActionSpec.requires_device` being set
   correctly on `rebuild_persistence_lvm`. Found by actually driving
   the running page in the browser and discovering the device picker
   never appeared - `requiresDeviceById[pendingActionId]` was always
   `false` regardless of the real flag. Neither bug was caught by unit
   tests written before the live check, because the tests exercised
   each layer in isolation and never asserted the two layers agreed
   with each other - a real, useful lesson about what isolated
   Runner/FakeRunner tests do and don't prove.
3. (Also found live, not by inspection) two default-flagged drives
   both rendering the `.selected` CSS class, when a radio group can
   only have one genuinely checked option - fixed by computing the
   single real default in `render_drive_admin_page` itself rather than
   per-card.

## Dark mode, corrected twice

First attempt at fixing invisible (dark-on-dark) text switched
`settings_web._PAGE_CSS` to an explicit **light** theme - technically
readable, but not what was asked. Direct correction: "That is not dark
mode." Rewritten as a real dark theme (light/medium text on dark
backgrounds throughout, `:root { color-scheme: dark }`, explicit dark
backgrounds so no host theme can override it) matching the Drive
Administration page's own palette, applied consistently across
Settings/Admin/Recovery/Login/Master Config via the shared `_PAGE_CSS`
and `control_panel_web.py`'s own stylesheet.

## Production wiring completed this pass

- New `baseline/bin/baseline-web` entry point, new
  `boot/baseline-web.service` (`After=`/`Requires=
  baseline-persist-bind-mounts.service`, gated on
  `baseline-settings-web-gate` reusing `firstboot_statemachine
  .already_completed()` unchanged - no new gate module needed).
- `baseline-web.service` **supersedes** `baseline-settings-web.service`
  for systemd-managed auto-start (staged/enabled in its place,
  default port 8100 unchanged) - a strict superset, every existing
  route still works. `baseline-settings-web`/`baseline-control-panel`
  remain staged as standalone, directly-invokable tools per their own
  docstrings; neither is systemd-managed any more.
- `baseline_web.build_real_server` wires a real
  `SystemElevationVerifier("root")` (overridable via
  `elevation_username`) for the real deployment - never the DEV-ONLY
  JsonFileStore-seeded elevation `settings_web.build_real_server`
  itself defaults to for standalone, no-root evaluation.
- `drive_admin.py`/`baseline_web.py` staged in `provision.sh`; the
  stale comment claiming control_panel_web.py's routes are
  unauthenticated and deliberately unwired was corrected in place -
  they are no longer either, now that the merge puts them behind
  `settings_web.py`'s own real login.

## What this does not do

Has not been run as root against real hardware - the actual
`rebuild_persistence_lvm`/`create_baseline_volumes`/etc. privileged
paths remain verified only via `FakeRunner`, plus one real, safe
demonstration that they correctly refuse for lack of privilege when
run as a normal user (this dev session's own demo). Real destructive
verification needs a real boot of `baseline-web.service` as root on
disposable hardware - not done here, deliberately, given the
blast radius. `apply_volume_mode`'s "write-only" setting still has no
real Linux mount-option equivalent (mapped to the closest honest
approximation, `rw`, matching decision record 80's own disclosed
storage-only limitation for that value).

## Verification performed

- `drive_admin.py`: 36 tests (argv builders, `resolve_target`'s
  serial-unrestricted validation including a real boot-device refusal
  and a below-minimum-size refusal, `rebuild_persistence_lvm` on both
  the default and a completely different real drive,
  `classify_drive_type` against this project's own real hardware data
  for every category including the honest USB fallback,
  `list_candidate_drives`'s boot-device exclusion and default-marking,
  `describe_actions`'s `requires_device` regression coverage).
- `baseline_web.py`: 20 tests (nav/dispatch composition, real drive/
  volume state via `drive_admin` directly, the single-checked-radio
  fix, real-socket dispatch for GET/POST including the sudo-password
  refusal and success paths, `build_real_server`'s real
  `SystemElevationVerifier` wiring and its username override).
- `settings_web.py`: `SystemPasswordVerifier`/`SystemElevationVerifier`
  real `/etc/shadow`-shaped hash verification, including the crash
  that would have happened without the adapter.
- Live browser verification against this session's own real attached
  hardware: all 12 real drives correctly enumerated and classified
  (including the two pre-authorized NVMe-behind-USB-bridge drives),
  the boot device (`nvme0n1`) correctly excluded, the device picker's
  default correctly following whichever drive is selected on the page,
  the password-refusal path exercised for real.
- `tools/check_provision_deploys_all_imports.py`: zero gaps.
- `bash -n boot/provision.sh`: valid syntax.
- Full suite: 1282/1282 passing.
