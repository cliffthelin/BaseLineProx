# Decision record: opt-in drive restriction, computed minimum size, drive inventory, and an editing lock

Status: **implemented. Backend safety change (physical_device_safety.py)
is real and unit-tested, 812/812 suite passing. The configurator
changes (computed size, drive inventory CRUD, password-gated editing
lock) are real, working browser-side code, but - like every other
configurator feature this session - not yet wired to any automated
installer entrypoint.** Not run against real hardware.

## What was asked

A dense, multi-part direct instruction, addressed piece by piece:

1. *"Minimum accepted size should literally be the minimum size based
   on the marked for install items in addition to standard build."*
2. *"Each driver and application and OS should have a setting that is
   looked up and stored for each selected for the install... include a
   potential buffer space that should also be a stored value and
   available per each driver, application, OS. That should be shown."*
3. *"Expected serial doesn't seem like it should be forced but that it
   should be a restricted."*
4. *"If a user wants a backup made or requires changing drives...all it
   should take to authorize a new one is to provide that password. Any
   field should be allowed to be changed with that password
   provided... the number of drives and what drives should be
   detected and able to be accessed."*
5. *"Drivers for drives should likely be covered with Proxmox and how
   they are setup if they should be auto load, Read only, or read and
   write."*
6. *"These should not locked or restricted to the list unless a
   selection is made that indicates that is desired. Default is not
   and I do not want it restricted in my current builds."*
7. Mid-turn: *"Also note the crud of other drives only effects the
   config do not make changes to those drives"* - the drive-inventory
   CRUD must never itself perform any real destructive action.

## 1-2: computed minimum size, per-item size/buffer

Real selectability was checked first, not assumed: the five diagnostic
tools and the kiosk (cage/chromium) are NOT independently toggleable in
real code - `firstboot_statemachine.DIAGNOSTIC_PACKAGES` installs all
five unconditionally, and `provision.sh` installs cage/chromium
unconditionally too. Giving them their own selectable size fields would
have been decorative, not real - so their real, measured combined size
(~6 MB for the five tools + cage, via `dpkg-query`/`apt-cache` on this
machine) is folded into one `standard_build_size_mb` field alongside
Proxmox VE's own footprint (~3072 MB, a documented estimate - not
measured on real hardware this session) and Chromium's (~250 MB,
likewise a commonly-cited estimate, not measured here - chromium isn't
installed on this dev machine).

What IS really selectable got its own size + buffer fields:
`cpu_microcode_size_mb`/`cpu_microcode_buffer_mb` (0.9 MB real,
measured via `dpkg-query` on this machine, + 5 MB buffer),
`wifi_firmware_size_mb`/`wifi_firmware_buffer_mb` (2 MB estimated -
firmware-mediatek isn't installed here either, honestly flagged as an
estimate, + 5 MB buffer), and `vm_debian_buffer_gb`/`vm_ubuntu_buffer_gb`
alongside the disk-size fields that already existed. Each of the
driver-inventory CRUD's records also got a `size_mb` field (0 for
anything in-kernel or already covered by a dedicated field, to avoid
double-counting).

`computeMinSizeBytes()` sums all of it live - standard build + a global
safety buffer + whichever driver toggles are on + whichever VMs are
included + every active driver-inventory record's size - and the
Drive & Target tab's `min_size_bytes` field is now `readonly`,
recomputed on every render and shown as both raw bytes and ~GB. This
literally is the minimum for what's actually marked for install, not a
flat guess - the whole point of the instruction.

## 3, 6: serial restriction made opt-in in the real backend

Covered in the paired implementation commit
(`physical_device_safety.py`): `validate_target_device()`'s
`expected_serial` is now optional, defaulting to `None` (unrestricted -
the real default, matching "I do not want it restricted in my current
builds" exactly). A string still means exact-match; a list means "any
of these" - the real shape needed for point 4's "number of drives."
The boot-device exclusion and size-range checks are unaffected and
always enforced regardless of the restriction setting. The
configurator's Drive & Target tab now has a matching
`restrict_to_serial_allowlist` toggle, off by default.

## 4-5, 7: drive inventory CRUD, access mode, config-only guarantee

A new `driveRecords` CRUD (mirroring the existing driver-inventory
CRUD's pattern) replaces the old single hardcoded `expected_serial`
text field - "the number of drives... should not be locked to exactly
one or two." Each record: label, serial (only enforced when the
allowlist toggle is on), and a Proxmox `access_mode`
(auto-load/read-only/read-write) - the real shape point 5 asked for,
honestly marked `coded: false` since no Proxmox storage-config apply
function exists yet to actually act on it.

**The mid-turn correction, addressed directly**: the drive-inventory
CRUD's own description now states explicitly that adding, editing, or
deleting a row here only ever changes stored config - it cannot run
`wipefs`/`sgdisk`/`mkfs` or anything else against a real drive. This
was already true by construction (the CRUD is pure browser-side JS
against the Artifact's own `db` store; nothing in this page can reach
real hardware), and this fix makes that guarantee visible in the UI
rather than leaving it merely true-but-unstated.

## 4: the password-gated editing lock

A real, working feature, with an explicit honesty caveat stated in its
own code comments and this record: before any password is ever set,
the whole form is fully open, exactly as asked. Once a password is set
(via the new 🔑 header control; changing an existing one requires the
old password first), the form locks on every fresh load and every
field - including the driver/drive-inventory CRUD rows and the
screenshot-AI modal's own "add to config" action, not just the
plain F()-based fields - is disabled until unlocked with that password
for the current browser session (🔓/🔒 header control).

**What this is not**: a production security boundary. This is a static
page with no server - the check is client-side JavaScript, and
anyone with browser devtools can view or bypass it trivially. It is a
real, useful edit-guard for a review tool one operator uses on
themselves, not authentication. The actual security boundary for any
real destructive drive operation remains `physical_device_safety.py`'s
own validation, which runs host-side against real hardware - stated
this plainly rather than oversold.

## Verification performed

- RED confirmed first for every new `physical_device_safety.py`
  behavior: the four new opt-in-restriction tests failed against the
  old forced-exact-match code before the fix.
- 5 new backend tests (`test_unrestricted_by_default_when_expected_serial_is_omitted`,
  two boot-device/no-serial edge cases under unrestricted mode, and two
  for the list-of-serials shape).
- Full suite: 812/812 passing (807 before this change), no regressions.
- Configurator changes verified by direct JS syntax check
  (`node --check`) and a full re-scan for the select-with-no-options
  bug class from decision records 52/53 (zero remaining issues) before
  each republish - no live-browser interaction test was performed
  beyond that (this session's established discipline: static review,
  not a browser test harness, for this artifact).
