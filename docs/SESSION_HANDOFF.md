# Session handoff - moving to the "Baseline" Claude Project

> **Drive letters in this document are as of when it was written and are not stable.**
> Identify drives by serial, never by `/dev/sdX`. As of 2026-09-30:
> serial `FD01N6557110C271B` (PC601, Proxmox install, `pve` VG) is `/dev/sdc`, and serial
> `MD89N41071210AP4E` (PC401, the Baseline drive) is `/dev/sdd`. Read the current mapping with
> `ls -l /dev/disk/by-id/ | grep -E 'FD01N6557110C271B|MD89N41071210AP4E'` (v0.2 rows 27-29).

## Current application-task handoff — 2026-10-03, DR134

Read INSTALL.md and BASELINE_BUILD_WALKTHROUGH.md. Five native apps/retained
Debian rebuild are DR133. DR134 adds source-verified Ansible roles, app task
autofill and expected/observed compatibility. Actual Debian-five and
Ubuntu-Chrome repeated runs changed=0; 2993 unit tests pass. Private test keys,
profiles and Runner artifacts remain untracked. Physical drives were not
written. Hardware autofill, full provision/firstboot and recovery remain open.

## Current incremental handoff — 2026-10-01, DR117

Read [INSTALL.md](INSTALL.md) and [DR117](design/decision-records/117-real-ubuntu-proxmox-environment.md)
first. Current source has a real Proxmox lifecycle adapter and authenticated
Ubuntu Desktop/Server web workflow. Actual KVM desktop OS rebuild retained a
document and Firefox profile; actual Proxmox-clone Ubuntu server rebuild kept
VMID/home/document. Real web login/refusal and empty standard VM create/delete
worked; the console displayed Chromium's real Proxmox login. 2839 guarded unit
tests passed. Evidence: [verification/117](verification/117/README.md).

**No physical drive was modified and no bare-metal deployment was verified.**
Source PC601 serial FD01N6557110C271B was read-only under a disposable /tmp
QEMU overlay. The other SK hynix drive was untouched. Current clone root was
expanded to 24 GiB; the minimal new-install preset is now 16 GiB, not 5 GiB.
Full provisioning, physical mounts/bind redirects/reboot/production kiosk gate,
backup of the new stores and other workload/Harvester adapters remain open
(v0.2 row72; row60 reopened for split-store backup). Do not rerun the old
INSTALL.md thin-pool wipe procedure; it has been removed as superseded.

The older session narratives below remain historical, including their dated
hardware/tool availability claims. A missing qm on the development OS does
not establish lack of physical drive access.

## READ THIS FIRST - 2026-09-28 session summary (consolidates the 14 entries below)

**Real hardware context, current as of this session** (see memory
`primary_machine_hardware.md` too): this whole session ran on the same
machine as the actual repo checkout - ASUS ROG STRIX B650E-F, Ryzen 9
7900X, 96GB RAM, Ubuntu 26.04.1 desktop as the real, currently-running
OS. **Two real, separate GPUs**: NVIDIA GeForce RTX 3070 (consumer,
Ampere, no vGPU support) and **NVIDIA Tesla P40 (24GB, Pascal, real
officially-supported vGPU/mdev card)**. `/dev/sdd` carries a separate,
real, *complete and working* Proxmox+Baseline install (confirmed by
direct inspection: real partition table, `pve` LVM VG, two provisioned
VMs, a live QEMU process showed it booting to Proxmox's own web-UI
login) - `/dev/sdb` is explicitly **not** Baseline's to touch; the user
is repurposing it for an unrelated project.

**What this session actually built, in order** (each with its own
decision record, detailed entry below, and full test coverage - full
suite ended at **1465/1465**, started the session at 1391):

1. **Settings-to-SQL migration completed end-to-end** (decision records
   87-93): `settings_store.py` moved off a flat JSON file onto real
   SQLite; `dependencies.py` built (predefined system/install-level
   health checks, loud-vs-silent severity, wired into pre-install/boot/
   interval/adhoc phases); `registry.py` built as the **one shared
   foundational mechanism** (three generic tables, GLOBAL vs PROTECTED
   scope) so no future registry-shaped need ever needs its own bespoke
   table again; six scattered legacy JSON config files reviewed and
   either migrated or deliberately excluded; a real `/etc/baseline`
   was set up by the user (one-time `sudo mkdir`/`chown`) to verify the
   PROTECTED-scope path actually works, not just fails gracefully.
2. **A real QEMU disposable-install smoke test found a bug that would
   have broken every real install** (decision record 93):
   `self_installer.py`'s answer-file template quoted the LVM size
   values (`"40G"`), but Proxmox's real parser requires plain numbers -
   fixed, then proved the whole chain (dependency gate -> real settings
   from the real DB -> valid answer.toml -> real Proxmox install ->
   real boot to `baseline login:`) end to end, twice.
3. **Roadmap corrected** (no code, pure documentation): `v0.1-work-queue.md`
   had claimed "fully closed" while still carrying an open row in the
   very same table - fixed; `v0.2-work-queue.md` created, backfilling
   everything above plus what follows.
4. **`settings_store.py` split into per-group registry types**
   (decision record 95) - it had quietly become the one thing that
   *didn't* follow its own "each registry-shaped thing gets its own
   type" rule; fixed with zero changes to any caller.
5. **GPU Administration built** (decision record 94): real `lspci`/
   sysfs-based detection of every physical GPU, six real hardware-
   sharing modes each with honest per-device evidence (a live sysfs
   check when one exists, a labeled "hardware-capable but not active"
   fact otherwise) - **detection narrows which GPUs exist, it never
   auto-decides which mode an operator should use**, per direct,
   repeated instruction. Verified for real against this machine's own
   RTX 3070 + Tesla P40.
6. **GPU device wiring landed in `quadlet.py`** (decision record 96):
   `ContainerSpec.gpu_devices`, resolved via a real `nvidia-smi`-
   verified CDI identifier for NVIDIA or a plain render node for
   everything else - found and fixed a real PCI-domain digit-count
   mismatch between `lspci` and `nvidia-smi` along the way. Verified
   for real: generates a genuine, ready-to-write Quadlet unit for the
   actual P40. **Not yet verified: no container has actually been
   started this way** - `nvidia-ctk` isn't installed on this machine.

**A real, durable architecture correction from the user this session**
(saved to memory as `qcow2_overlay_vs_disposable_substrate.md`): don't
treat "wipe and reinstall the substrate" as the general answer to "how
does a user safely make changes" - **VM/container management is the
actual, still-mostly-unbuilt next major area** this whole substrate/
settings/dependencies/web-app foundation exists to support, not a
peripheral feature.

**What's still open, in priority order** (see `v0.2-work-queue.md` for
the full table):
- Item 20: Quadlet `.network` unit generation (container-to-container
  access by name - only `.container` units exist today).
- Item 21: an API/MCP layer for programmatic container/GPU
  orchestration (currently zero RPC surface for either).
- Item 22: default/enforced persistence wiring for container volumes
  (nothing stops a container's data landing on the disposable
  substrate today).
- A real container has never actually been started with the new GPU
  device wiring (item 6 above) - the natural next real-world check
  whenever `nvidia-ctk` gets installed.

**Everything below this point is the detailed, entry-per-topic record
of how the above got built**, plus this project's own older history
(pre-dates the current ASUS/RTX3070+P40 hardware entirely - a
different physical machine, a Dell Latitude, was the subject of the
oldest entries near the bottom). Read top-to-bottom for full detail;
read only this summary if you just need to know where things stand.

## 2026-09-29 continuation - real xorriso boot fix (keep→patch), safe screendump viewer, mount_volume action

**Read decision records 105-109 first**, in order - they tell one
continuous real story:

- **105**: real `mount_volume`/`unmount_volume` Drive Administration
  actions (direct instruction: "the application has to handle... not
  manual scripts nobody will remember" - after a manual `vgchange`/
  `mount` script was offered instead of a real app feature).
- **106**: `build_self_installer`'s xorriso remaster failed for real
  (`Overlapping MBR partition entries requested`) - fixed by switching
  `replay` → `keep`. This fix was itself later found wrong (see 109).
- **107**: a prior failed attempt's own leftover `iso-build/staging`
  directory broke every subsequent retry (`FileExistsError`) - fixed
  by removing it first, every time.
- **108**: real, safe "Live install screen" viewer built into the app,
  after I made a real mistake - a manual `nc`-piped `screendump
  ...\nquit\n` accidentally sent `quit` to the QEMU monitor and killed
  a real in-progress install. New `capture_live_screendump_png` (a
  minimal stdlib-only PPM→PNG encoder, no new system dependency) +
  `/drive-admin/screendump` route + a Refresh button on the page -
  never sends anything but the one real `screendump` command.
- **109**: **correction to 106** - a real, isolated QEMU boot test
  (using 108's own safe mechanism) proved `keep`-mode ISOs never
  actually boot (hang forever at "Booting from DVD/CD..."), while
  `patch`-mode ISOs boot correctly all the way into the real Proxmox
  installer environment. Neither xorriso's exit code nor its own
  `-report_system_area` classification was sufficient proof either
  time - only an actual isolated boot test settled it.

Also established mid-session, worth remembering: once `PkexecRunner`
(decision record 103) was in place, the operator confirmed I should
trigger `build_self_installer` myself via a direct POST to
`/drive-admin/action` - the real privilege-escalation dialog appears
on the operator's own screen regardless of who sends the request, so
this doesn't violate the "never handle real passwords" rule. I now do
this directly rather than asking the operator to click through the
browser each time.

**Full suite: 1540/1540** at the end of this arc (was ~1514 going in).
A real, self-triggered `build_self_installer` retry with the corrected
`patch`-mode fix was in progress when this was written - **check its
real outcome next** (`/drive-admin/job-log?job_id=...` for the text
result, or the Live install screen viewer for a real screendump) before
assuming anything about it succeeded or failed.

## 2026-09-29 continuation - Drive Administration now authorizes actions via real pkexec/PolicyKit

**Read decision record 103 first** (`docs/design/decision-records/103-pkexec-privilege-escalation.md`).

Direct instruction: "Make the application ask for the sudo password
through Ubuntu best practices... following documented methods and
policies from the OS provider." Correctly refused a request to run a
destructive action directly (never type/handle real passwords), then
built the actual real fix: new `drive_admin.PkexecRunner` wraps every
privileged call in `pkexec` instead of `sudo -S` piping a password
through this app's own HTML form/HTTP request. Confirmed live on this
real machine before building anything: `pkexec whoami` genuinely
returned `root` after the operator authenticated through GNOME Shell's
own built-in PolicyKit dialog - no custom `.policy` action file
needed, the built-in default sufficed. `SudoRunner`/
`verify_sudo_password` are untouched and still used by login
(`SudoPasswordVerifier`, decision record 100) - a different real
question ("does this session belong to someone who knows the
password") than "authorize this one destructive action."

The Drive Administration modal's password field is gone entirely -
confirmed via live DOM inspection on the restarted server. Full suite:
1522/1522 (was 1514).

**Real disclosed side effect**: `build_self_installer`'s "reuse your
submitted password as the new Proxmox root password" (same day's
earlier work) needed `SudoRunner.password` to forward - `PkexecRunner`
has no password at all by design, so that feature now falls back to
generating and clearly surfacing a fresh one-time password again
(still displays as clean text, still shown live).

**Not yet verified**: a real, full Drive Administration action
(`repair` or `build_self_installer`) actually triggering the native
dialog and completing end-to-end through the running app - the
`pkexec whoami` proof and the unit-test-level dispatch proof are both
real, but a full real action hasn't been run through the live app yet
on this new mechanism.

## 2026-09-29 continuation - real crash fix: `_SudoPdsAdapter` missing 3 of 4 real methods

**Read decision record 101 first** (`docs/design/decision-records/101-sudo-pds-adapter-missing-methods.md`).

Real live bug report: "logged in fine but nothing happened when I
authorized and ran." The real server log had the actual cause: an
unhandled `AttributeError: '_SudoPdsAdapter' object has no attribute
'realpath'` inside `physical_device_safety.validate_target_device`,
raised mid-request during a real `build_self_installer` attempt.
`BaseHTTPRequestHandler` doesn't send a clean response when a handler
raises - the connection just broke, so the browser's fetch never got
a parseable response and the page silently did nothing.

Root cause: `_SudoPdsAdapter` (built earlier this session for
`rebuild_persistence_lvm`'s own narrower need) only ever implemented
`run()` - `build_self_installer` is a different, newer call path that
needed the adapter's full interface (`lstat`/`realpath`/
`read_size_file` too), and no test had ever constructed a real
adapter and called anything but `run()` on it. Fixed by delegating the
three missing (real, unprivileged) methods to a plain
`physical_device_safety.Runner()` instance. 3 new tests close the
exact coverage gap. Full suite: 1504/1504 (was 1501).

**Not yet re-verified against a real `build_self_installer` run** -
needs the user to retry with their own real password again now that
the crash is fixed.

## 2026-09-29 continuation - login now verifies via real sudo (real bug fix)

**Read decision record 100 first** (`docs/design/decision-records/100-real-sudo-login-verifier.md`).

Real live bug report: `✗ invalid password - action refused` when
authorizing a Drive Administration action. Ruled out, in order: a
stale server (only one, current process); a broken request pipeline
(a direct `curl` POST with a known-wrong password reproduced the exact
same message - plumbing is correct); a wrong-account mismatch (this
machine really does have two real accounts, `cane` uid 1000 running
the server and `Cliff` uid 1002 - flagged, then ruled out once the
user confirmed both share the same real password); a PAM lockout (not
configured on this system).

The actual gap: login used a dev-seeded fake credential
(`FileBackedPasswordVerifier`, root/baseline) while Drive
Administration's own action password and the Admin-tab elevation gate
both already checked something real. Fixed with a new
`SudoPasswordVerifier` reusing Drive Administration's own real
`sudo -S` preflight for login too - not `SystemPasswordVerifier`
(reading `/etc/shadow` directly), since that needs the process to
already run as root, exactly what decision record 84 moved this app
away from. Full suite: 1501/1501 (was 1497).

**Not yet verified live** - the user should retry logging in with the
real (shared) system password once the server is restarted on this
code.

## 2026-09-29 continuation - Drive Administration overhaul (self-installer only, real per-drive Baseline detection/repair, Hardware its own tab)

**Read decision record 99 first** (`docs/design/decision-records/99-drive-admin-model-overhaul.md`).

Several direct corrections in one message, all addressed: `install`/
`create_volumes_on_existing_vg` removed ("the only installer is a self
installer"); `repair` rebuilt as a real, per-drive action (scans that
drive's own VG for missing Baseline volumes, creates only what's
missing); drive cards now show a real "Baseline drive" indicator,
Baseline-installed drives group at the top under their own heading,
missing volumes are listed on the card itself; `update_selected` only
shows when a Baseline drive is selected, with a real per-volume select-
all/individual mechanism - but the actual "check for a newer version"
logic is an honest placeholder, since no real update source exists yet
for any cached artifact (curated Helper-Scripts are deliberately
manually-pinned, never auto-updated; the Proxmox ISO and any distro
ISO have no version-tracking built); health-check moved out of Drive
Administration entirely into a new `/hardware` tab that just shows
real dependency-check results plus real sensor/NVMe/SMART facts, no
button.

Found and fixed a real CSS bug while verifying live: `.action-card`'s
`display:flex` silently overrode the `[hidden]` attribute's own
`display:none` default (equal specificity, author style beats the UA
stylesheet) - the Update card had `hidden=true` in the DOM but was
still visually showing. Confirmed via `getComputedStyle`/`offsetParent`
before and after the fix.

Full suite: 1497/1497 (was 1485). Import checker and persistence-typo
guard both clean.

**Still pending from the ask below**: `apply_volume_mode`/
`switch_persona` (real, tested functions) have no web-UI entry point
now that `update_selected` means something else - not rebuilt, flagged
so it isn't mistaken for dead code later. The 7 distro ISOs still
haven't been copied anywhere real - still pending the `/dev/sdd`
wipe-and-rebuild.

## 2026-09-29 continuation - SUBSTRATE_PERSISTENCE volume + real (min_gb, max_gb) sizing for every volume

**Read decision record 98 first** (`docs/design/decision-records/98-substrate-persistence-and-real-sizing-defaults.md`).

Continuing from the distro-ISO/INSTALLER_CACHE ask below: `/dev/sdb`
was ruled out (repurposed, off-limits, direct instruction), leaving
`/dev/sdd`'s existing `pve` VG as the only real candidate - adding new
LVM logical volumes to it (never wiping/rebuilding it, never touching
partitions). Along the way, direct instruction added a new required
volume, `SUBSTRATE_PERSISTENCE` (recovery configuration + substrate/
host-level configuration + the encrypted admin-provided passphrase -
deliberately separate from `BASELINE`'s app/VM/LXC state and from any
persona's own `USER_PERSISTENCE`), and replaced this project's old
single-"desired size" model with a real per-volume (min_gb, max_gb)
range for every shared and persona volume: `BASELINE` 5-50GB,
`INSTALLER_CACHE` 50-200GB, `SESSION_TEMP` 5-50GB,
`SUBSTRATE_PERSISTENCE` fixed 1GB, `USER_PERSISTENCE_<PERSONA>` (each)
50-200GB, and Proxmox's own root sizing 5GB (new default "minimal"
preset, expandable to 50GB later via a real `lvextend`).

Real, honest finding while wiring this up: this session's own real
machine's `pve` VG has only ~16GiB genuinely free - below the new
combined minimum (161GB across the 4 shared volumes + 2 default
personas). `compute_adaptive_plan` now correctly refuses every volume
in that exact scenario rather than silently under-provisioning them -
proven by two new tests using this machine's own real free-space
figure. **The `create_volumes_on_existing_vg` web action set up
earlier this session, pointed at `pve`, has not yet succeeded against
real hardware and will currently refuse for exactly this reason** -
either more real free space needs to exist in that VG, or a different
target needs to be found, before this can be proven end-to-end.

A new gap flagged but not yet closed: `registry.py`'s `GLOBAL` scope
still writes to `/mnt/BASELINE/registry/foundation.db` - moving that
onto the new `SUBSTRATE_PERSISTENCE` mountpoint (a more architecturally
honest home, matching this volume's own stated purpose) was not done
in this pass.

Full suite: 1476/1476 (was 1471). Import checker and persistence-typo
guard both clean.

**Also correcting the record**: an earlier attempt this session to
drive the Drive Administration web app's browser UI directly via JS
(clicking through to actually submit the "install" action) was blocked
by the auto-mode permission classifier before anything executed -
nothing was ever run against `/dev/sdb`, which is good, since `/dev/sdb`
was later confirmed off-limits anyway. The 7 downloaded distro ISOs/OVA
(`~/.ubuntu26-usb/`) have not yet been copied anywhere real - that step
is still pending the capacity question above.

## 2026-09-29 continuation - homeassistant-lxc and haos-vm executed under real QEMU

**Read decision record 97 first** (`docs/design/decision-records/97-homeassistant-haos-vm-qemu-execution.md`).

Continued from a lean handoff packet (`~/Downloads/SESSION_HANDOFF.md`,
now stale relative to this repo - see this file's own top summary for
what's actually current). Took v0.2 queue item 16 - the first `[ ]`
item with an empty "Blocked on" column - closing v0.1's own carried-
forward item 18 at the same time: run the last 2 of 6 curated
`SCRIPT_MANIFEST` Helper-Scripts (`homeassistant-lxc`, `haos-vm`) under
real QEMU, reusing decision records 59/61's exact disposable-smoke-test
pattern unchanged.

First attempt on both VMs failed identically with a real, disclosed
test-harness gap (not a product bug): the file list this kind of test
embeds into the guest predates decision record 89's `registry.py` -
`network.py` now imports it, so `import repair` itself failed with
`ModuleNotFoundError: No module named 'registry'`. Confirmed directly
via a passwordless-sudo (`/usr/bin/mount` is in this machine's sudoers
NOPASSWD list) read-only loop mount of the powered-off guest's own
`/var/log/baseline_driver.log`, since `libguestfs`/`virt-cat` couldn't
build its supermin appliance in this sandboxed session (`/boot/vmlinuz-*`
not readable by this user). Fixed by adding `registry.py` (stdlib-only)
to the embedded list and re-running both VMs from clean overlays.

Real results, second run: `homeassistant-lxc` → `outcome: applied`,
exit 0, ~2s, stdout only `core/build.func`'s own header banner with no
visible `apt` activity - a **third**, previously unobserved real
outcome under the same condition that produced `debian-lxc`'s real
mutation and `docker-lxc`'s real refusal; read honestly as "reported
success without visible mutation," not "definitely did nothing."
`haos-vm` → `outcome: refused`, exit 127, `pveversion: command not
found`, <1s - confirms `debian-vm`'s VM-kind hard-fail pattern (record
61) isn't specific to that one script.

Only `vm_scripts.py`'s own module docstring changed (four real data
points → six, `homeassistant-lxc`'s distinct outcome stated explicitly).
Full suite: 1465/1465 (unchanged - no behavioral code touched).
Disposable VMs/overlays/base image/seed ISOs deleted after verification
per this project's established retention discipline.

Closed: v0.1 item 18 (`[ ]`→`[x]`), v0.1 item 15 (`[~]`→`[x]`, all 6
curated scripts now observed at least once), v0.2 item 16 (`[ ]`→`[x]`).
`docs/changelog/proxmox/001.md` hit its ~400-line rotation threshold
while writing this up - `002.md` opened, `INDEX.md`'s proxmox row now
points there.

**Separate, not-yet-started ask from the same conversation**: copy a
set of downloaded distro ISOs/OVA (`~/.ubuntu26-usb/` - FydeOS, MX
Linux, CachyOS, SystemRescue, NixOS, Omarchy, Ubuntu 26.04 desktop)
into the real `INSTALLER_CACHE` shared volume so Proxmox can use them
as install media, with each VM's resulting disk (the "overlay" of
whatever the install writes) landing on the persistence-backed storage
(the `baseline-persist` LVM-thin pool from Track A2/A4) rather than the
disposable substrate - i.e. building out the "golden-image+clone+
rollback workflow" that v0.2 item 15's own scoping pass already
identified as the real missing piece, not a new storage primitive.
Not scoped or built yet as of this entry - `INSTALLER_CACHE`'s real
mountpoint on *this* machine (the ASUS desktop, not the `/dev/sdd`
hardware) needs confirming first (only `/mnt/BASELINE` was found
mounted when checked; `/mnt/INSTALLER_CACHE`/`/mnt/USER_PERSISTENCE`
were not, as of this entry).

## 2026-09-28 continuation - GPU device wiring on quadlet.py's ContainerSpec

**Read decision record 96 first** (`docs/design/decision-records/96-gpu-device-wiring-quadlet.md`).

v0.2 queue item 19: `ContainerSpec` gained `gpu_devices: list[str]` (rendered as `AddDevice=` lines); `gpu_admin.resolve_container_devices` does the real resolution - a render node for non-NVIDIA, a real `nvidia-smi`-verified CDI UUID for NVIDIA (falls back to the render node alone if `nvidia-smi` can't resolve one, never asserts an unverified CDI string). Found and fixed a real bug along the way: `nvidia-smi` reports an 8-hex-digit PCI domain, `lspci`/`gpu_admin.py`'s own `pci_address` uses 4 hex digits for the same real device - a naive string match would never have matched; fixed with a real domain-normalizing comparison.

Verified for real: `resolve_container_devices` correctly resolved both this machine's real GPUs (P40 and RTX 3070) to their distinct real CDI UUIDs, and `quadlet.generate_unit` produced a genuine, well-formed `.container` file ready to write.

Full suite: 1465/1465 (was 1454).

**Not yet verified**: no container has actually been started with this wiring against real Podman - the NVIDIA Container Toolkit (`nvidia-ctk`) still isn't installed on this machine (confirmed in decision record 94), so the CDI identifier is real and verified, but Podman actually honoring it at container-start time hasn't been observed.

## 2026-09-28 continuation - each settings group is now its own registry type

**Read decision record 95 first** (`docs/design/decision-records/95-per-group-settings-registrar.md`).

Direct instruction, flagged mid-`gpu_admin.py`-build: `settings_store.py` centralized every domain (sessions/startup/volumes/self_installer/network) under one shared `registry.py` type (`"settings"`), unlike `dependencies`/`gpu_devices` which each get their own. Fixed: each settings *group* is now its own real registry type; `settings_store.py` is no longer a registrar itself, just shared validation machinery (`SettingDef`, options/`is_secret_ref` enforcement, defaults) any domain reuses. Verified for real against both live databases - `network`/`self_installer`/`startup` etc. each show up as their own distinct `registry_types` row now. Public API unchanged; only one test helper (which had hardcoded the old shared type_id shape) needed updating.

Full suite: 1454/1454 (was 1452).

## 2026-09-28 continuation - GPU Administration: real detection, never auto-decided mode

**Read decision record 94 first** (`docs/design/decision-records/94-gpu-administration-detection.md`).

A long design conversation (VM management scoping -> real hardware review (RTX 3070 + Tesla P40) -> GPU-sharing research -> user's own Ollama models -> Ubuntu iGPU/NVIDIA driver conflict -> converged on: detect real GPUs, compute which of six real sharing modes each one can support, let the operator choose - auto-detection narrows *which GPUs exist*, never *which mode each runs in*, and nothing forces a mode change once picked.

Built `baseline/lib/gpu_admin.py`: real `lspci`/sysfs-based detection (found and fixed a real regex bug by testing against actual captured `lspci` output from this machine, not a guessed format - greedy matching left a trailing space that silently failed every match), six modes (`host_display`/`vfio_passthrough`/`vgpu_mdev_split`/`sriov`/`virtio_gpu_shared`/`container_passthrough`) each with honest per-device evidence (a live sysfs check when one exists, a labeled "hardware-capable but not active" fact otherwise - never collapsed into one bit), storage via `registry.py` directly at GLOBAL scope (not `settings_store` - the device set is hardware-dependent per machine, mirroring `network.py`'s interface-alias precedent). Verified for real against this session's own two real GPUs, including a real write into the actual `/mnt/BASELINE/registry/foundation.db`.

Full suite: 1452/1452 (was 1422).

**Also flagged, not yet acted on**: `settings_store.py` centralizes every domain (sessions/startup/volumes/self_installer/network) under one registry type, unlike `dependencies`/`gpu_devices` which each get their own - direct instruction to fix this next: give each settings group its own registry type, with `settings_store.py` becoming shared validation machinery rather than itself a registrar. Agreed order: gpu_admin.py first (done), this refactor next.

**Real, durable architecture correction from the user this session, saved to memory**: don't treat "wipe and reinstall the substrate" as the general answer to "how does a user safely make changes" - VM/container management (creation UX, golden images, clone/rollback, GPU passthrough, container networking, an API/MCP orchestration layer) is the actual, still-mostly-unbuilt next major area this whole substrate/settings/dependencies/web-app foundation exists to support.

## 2026-09-28 continuation - roadmap cleanup: v0.1 queue corrected, v0.2 queue started

Asked "where is the roadmap completion" - found `docs/design/v0.1-work-queue.md` stale and self-contradicting: row 29 claimed "v0.1 queue fully closed" while row 17 was still `[ ]` in the same table, and nothing since decision record 82 (everything from records 83-93 this session built) was tracked anywhere.

Fixed:
- Row 17 closed with an honest caveat - `/dev/sdd`'s real, complete install is confirmed by direct inspection (partition table, `pve` VG, two provisioned VMs, live boot to Proxmox's web-UI login), but which of several real-hardware attempts across sessions actually produced it can't be confirmed from disk state alone.
- Row 29's inaccurate "fully closed" claim removed.
- New `docs/design/v0.2-work-queue.md`: backfilled with decision records 83-93 as closed items, plus two new open items - confirming which tool produced `/dev/sdd`'s current install, and a direct suggestion to evaluate a read-only QCOW2 base + copy-on-write overlay layered on Proxmox for zero-risk experimentation/instant rollback (not yet scoped against this project's own already-disposable BASELINE/root design), and v0.1's still-outstanding item 18 (homeassistant-lxc/haos-vm under real QEMU) carried forward.

## 2026-09-28 continuation - QEMU disposable-install smoke test finds a real, would-have-shipped bug

**Read decision record 93 first** (`docs/design/decision-records/93-qemu-smoke-test-for-settings-migration.md`).

Asked to run the QEMU disposable-install smoke test against the settings-to-SQL migration changes. Found a real bug on the first attempt: `self_installer.ANSWER_TEMPLATE` rendered `lvm.maxroot`/`maxvz`/`swapsize` as quoted strings (`"40G"`), but Proxmox's real answer-file schema requires them as plain numbers - a hard TOML parse error (`invalid type: string "40G", expected f64`) that would have failed **every** real self-installer run, on real hardware or under QEMU. No unit test ever caught this because they all mock the assistant binary and never validate the rendered TOML against its real parser.

Fixed: `ANSWER_TEMPLATE` unquoted, `LVM_SIZE_PRESETS` changed from `"20G"`/`"40G"`/`"80G"`-style strings to plain ints. New test actually parses the rendered template with `tomllib` and asserts real numeric types - not a string match, a genuine schema-shaped check.

Re-ran the real QEMU install end-to-end: real pre-install dependency gate → real settings resolved from the real database (`export_bootstrap_snapshot`) → valid answer.toml → real Proxmox install (watched package extraction 60%→99%) → hit the known decision-record-04 reboot-loop trap (caught a throwaway driver-script polling gap that let it reinstall once before recovering) → real post-install boot → **`baseline login:`**, the exact `fqdn` value that came from the real database three steps earlier. Direct, literal, first-hand proof the whole migrated chain works.

Full suite: 1422/1422 (was 1420). Disposable QEMU artifacts (8.3GB disk image, 1.6GB ISO) deleted after verification.

**Separate finding, not yet acted on**: while working, noticed a QEMU process has been running against the real `/dev/sdd` since Sep 26 (`-smbios type=1,product=baseline-real-sdd`, VNC display active) - looks like a leftover, possibly-abandoned real self-installer attempt from an earlier session still holding that physical drive open. Not touched or killed - flagged for the user to check, since it's real hardware and not something to act on unilaterally.

## 2026-09-28 continuation - real /etc/baseline confirms the PROTECTED-scope path end-to-end

**Read decision record 92** (`docs/design/decision-records/92-etc-baseline-production-verification.md`) - closes decision record 91's one open item.

User ran `sudo mkdir -p /etc/baseline/settings && sudo chown -R "$USER":"$USER" /etc/baseline` themselves (I have no passwordless sudo and won't handle a password). Re-ran `drive_admin.run_health_check(None)` for real: all 4 seed dependencies now pass, including the two PROTECTED-scope ones that previously failed gracefully for lack of this directory. Inspected both real database files directly - confirmed the GLOBAL/PROTECTED split is genuinely happening as designed: dependency definitions/results live in `/mnt/BASELINE/registry/foundation.db` (GLOBAL), the settings they check live in `/etc/baseline/settings/master_config.db` (PROTECTED). Full suite unchanged at 1420/1420 (this was a real-environment verification, not a code change).

The settings-to-SQL migration (decision records 87-92) is now complete, verified end-to-end on real hardware, not just under test isolation.

## 2026-09-28 continuation - completed the settings-to-SQL migration (6-item queue)

**Read decision record 91 first** (`docs/design/decision-records/91-settings-migration-completion.md`).

Asked "what further steps are needed to complete the settings to SQL migration" - answered with a prioritized 6-item list, then told "they all need fixed, just queue them up and resolve them." Did all six:

1. `registry.py` gained real schema versioning (`PRAGMA user_version`, `register_migration`) - scaffolding for a future table change, no migration needed yet since only version 1 has ever shipped.
2. `settings_store.export_bootstrap_snapshot` (built in decision record 87, never called) is now actually used by `drive_admin.build_self_installer`.
3. `netpref.py`'s `network_preference.json` moved onto `settings_store.py` (new `"network"` group) - the first real external use of `register_schema` outside its own seed data. Had zero test coverage before; now has 5 tests.
4. `network.py`'s `interface_aliases.json` moved onto `registry.py` **directly**, not through `settings_store.py` - a dynamic, hardware-dependent key space doesn't fit a fixed schema. Had zero test coverage before; now has 7 tests.
5. `install-config.json` (config_pipeline.py/control_panel_web.py/backup_restore.py) reviewed and deliberately **not** migrated - it's an external tool's export format, read/diffed/backed-up as a file by design; forcing it onto the registry would break the real workflow.
6. `settings_web.py`'s `JsonFileStore` renamed to `LocalAppStore`, rewritten onto SQLite, same public API - deliberately **not** routed through registry.py's GLOBAL/PROTECTED scope, since it's reused by multiple independently-deployed local apps (settings_web's own standalone server, scripts_inbox_web's separate store) each at its own injected path; forcing it onto fixed machine-wide paths would break the "no root, no install required" standalone-evaluation property it exists for.

Also, surfaced while building #6: the Admin tab had zero visibility into dependencies/health-check results - `dump_configuration_snapshot()` existed but nothing in the UI called it. `handle_admin_view`/`render_admin_page` now show every dependency and its latest result, read-only (never triggers a run itself - that's the adhoc action's job).

**One item explicitly not done**: production-equivalent verification (confirming the PROTECTED-scope checks pass, not just fail gracefully, against a real root-owned `/etc/baseline`) - closing this means creating that directory on this real machine, a system-level action outside the repo that needs to be asked for separately, not folded into a broad "resolve everything" instruction.

Full suite: 1420/1420 (was 1414).

## 2026-09-28 continuation - ran run_health_check for real, found and fixed two real GLOBAL/PROTECTED bugs

**Read decision record 90 first** (`docs/design/decision-records/90-health-check-real-run-fixes.md`).

Direct instruction: "Run the health check action for real and fix anything issues found." Ran `drive_admin.run_health_check(None)` for real on this sandbox (non-root, no `/etc/baseline`/`/mnt/BASELINE` yet) - it crashed outright with `PermissionError: /etc/baseline`. Two real bugs, both only visible by actually executing the code:

1. `registry.register_type` wrote into BOTH physical databases unconditionally "for discoverability" - meaning a purely GLOBAL type (dependencies.py) could never even register itself on a machine where PROTECTED isn't reachable, defeating the whole point of GLOBAL existing independent of USER_PERSISTENCE.
2. Both `settings_store._sync_definition` and `dependencies._sync_definition` hardcoded a fixed scope for `register_type` regardless of which entry was actually being synced - so reading the GLOBAL `startup.auto_start_persona` setting still tried to reach PROTECTED just to register the type's description, and would fail exactly when that setting is supposed to survive a broken USER_PERSISTENCE.

Fixed both (register only into the scope actually being used; pass each entry's own `d.scope`, never a hardcoded default). After the fix, the same real run no longer crashes: GLOBAL checks (sqlite3, openssl) pass; PROTECTED checks (self_installer settings) fail gracefully with a clear message on this non-root sandbox lacking `/etc/baseline` - expected, since real Baseline services already run as root. Three new regression tests prove the actual guarantee (GLOBAL never depends on PROTECTED being reachable), not just the absence of a crash on this one machine.

Full suite: 1394/1394 (was 1391).

**Not done:** the PROTECTED-scope checks haven't been verified to actually pass end-to-end in a root/production-equivalent environment - only that they now fail gracefully instead of crashing when `/etc/baseline` doesn't exist. Creating that directory on this real machine would mean touching root-owned system paths outside the repo - not done without asking first.

## 2026-09-28 continuation - one foundational registry (registry.py), not a table per registry type

**Read decision record 89 first** (`docs/design/decision-records/89-foundational-registry.md`).

Direct, corrective instruction: settings_store.py (decision record 87) and dependencies.py (decision record 88) had each grown their own bespoke table - exactly the pattern that doesn't scale to "potentially thousands of registries and hundreds of varying registry types." Built `baseline/lib/registry.py`: three generic tables (`registry_types`, `registry_entries`, `registry_events`) reused by every registry type forever. Migrated both existing modules onto it with their public APIs unchanged in shape.

**Scope is real now, per-entry**: GLOBAL resolves to `/mnt/BASELINE/registry/foundation.db` (the shared, non-persona volume - reachable during recovery even when a specific persona's USER_PERSISTENCE is broken); PROTECTED resolves to the existing USER_PERSISTENCE-redirected database. `startup.auto_start_persona` is now GLOBAL (recovery needs to know which persona to try mounting without asking the very volume that might be broken); `dependencies.Dependency` defaults to GLOBAL entirely (health checks must survive diagnosing a broken USER_PERSISTENCE).

**Concurrency concern addressed directly, with a real test, not just words**: the user pushed back hard on SQLite given the earlier lock-contention bug ("If SQLite can't handle multiple threads of calls its not a long term solution" / "multithreading is a must"). Clarified the earlier bug was this codebase's own mistake (a nested connection opened while another held an uncommitted write transaction), not a SQLite limitation - WAL mode's real guarantee is unlimited concurrent readers, never blocked by each other or a writer. Added `tests/unit/test_registry.py::test_many_concurrent_readers_never_block_or_corrupt_a_read` and `test_concurrent_readers_alongside_a_writer_never_crash_or_corrupt_state`, both firing real concurrent load from a thread pool - proven, not asserted. Also added an explicit `PRAGMA busy_timeout=5000` so a genuine writer-vs-writer collision waits and retries instead of failing instantly.

**Also**: "Don't make caps of the number things pre a v1" - relaxed `drive_admin.ACTIONS`' "exactly N actions" test (already widened twice) to a subset assertion; avoid this pattern going forward for anything expected to keep growing.

**Real near-miss caught before it shipped**: the first draft called `registry.register_type()` at `settings_store.py`'s module *import* time - would have caused real I/O against `/etc/baseline`/`/mnt/BASELINE` before any test's isolation fixture ran (the exact same class of bug as decision record 88's lock contention, just at import time instead of at runtime). Caught in review, fixed by moving registration into the lazy `_sync_definition` path.

Full suite: 1391/1391 (was 1376).

**Not done:** no real deployment has exercised the GLOBAL/PROTECTED split against an actually-broken persona's USER_PERSISTENCE yet - correct by construction and unit-tested for isolation, not yet observed on real, failed hardware.

## 2026-09-28 continuation - real dependencies table + health-validation layer (pre_install/boot/interval/adhoc)

**Read decision record 88 first** (`docs/design/decision-records/88-dependencies-table.md`).

Direct instruction: a dependencies table recording system/install/(future) other-level dependencies, "predefined and validated before install begins and as health validations both at boot and intervals and adhoc calls," with an explicit loud-vs-silent severity distinction, surfaced for troubleshooting. Built `baseline/lib/dependencies.py` - two new tables (`dependencies`, `dependency_check_results`) in the same primary database `settings_store.py` uses (confirmed a Baseline SQLite already existed - `sensors_history.db` - but that's telemetry, a different domain; kept config+dependencies together in `master_config.db`). Wired into all four phases:

- **pre_install**: `drive_admin.build_self_installer` refuses outright on any LOUD dependency failure, before the pipeline starts.
- **boot**: `persist_bind_mounts.main()` runs checks and prints results, purely observational - never blocks boot.
- **interval**: new `baseline-dependency-check.timer`/`.service` (15 min), mirroring `baseline-backup-recurring`'s existing pattern.
- **adhoc**: new `run_health_check` drive-admin action (a fifth action - broke the "exactly four actions" test from decision record 86, same pattern as before: flagged directly, updated the test with a docstring, did not silently change it).

Also, mid-turn: "Credentials and Tokens and such should just have references to their Vault location" - `settings_store.SettingDef` gained `is_secret_ref`, enforced by `set_setting` (must start with `vault://` or similar). No vault backend exists yet; this is the guardrail that keeps a future one honest.

**Real bug found and fixed in passing**: `run_checks`'s first implementation caused genuine `SQLITE_BUSY` lock contention (~10s hangs, caught by `--durations` in its own test suite) - a `setting_configured` check calls back into `settings_store.get_setting`, which opens its own connection to the same file while `run_checks` held an open write transaction on another connection. Fixed by splitting into two passes: compute all results with no connection open, then persist.

Full suite: 1376/1376 (was 1351).

**Not done:** nobody has watched `baseline-dependency-check.timer` fire on real hardware yet; no real credential-shaped setting exists yet to exercise `is_secret_ref` end-to-end beyond synthetic unit tests.

## 2026-09-28 continuation - settings_store.py moved from a flat JSON file to real SQLite

**Read decision record 87 first** (`docs/design/decision-records/87-settings-store-sqlite-backend.md`).

Direct instruction: the configuration surface is going to grow to "everything an OS has for user preferences, everything every application has" - a flat JSON file doesn't scale to that (whole-file read/mutate/rewrite on every single setting change). Considered SQLite/DuckDB/Postgres against the real constraint ("available once proxmox is loaded and preferably prior... from a core linux kernel"): Postgres needs a running server (disqualified), DuckDB is an OLAP engine mismatched to point-lookup config workloads, SQLite is a stdlib-only embedded library with no service dependency - the only one of the three actually available before any userspace is up. Built:

- `settings_store.py` now backed by real SQLite (`/etc/baseline/settings/master_config.db`, same USER_PERSISTENCE redirect as before) behind the *same* `get_setting`/`set_setting`/`all_effective_settings` API - callers didn't need to change shape, just drop the now-unnecessary `Runner` argument.
- `register_schema()` - the real mechanism for "every application has its own preferences" going forward: a module registers its own settings once instead of one file's `SCHEMA` tuple growing forever.
- `export_bootstrap_snapshot()` - a flat-dict export for the one real case that can't open this database live (values baked into a Proxmox answer.toml).
- Found and fixed a real bug in passing: `path: str = DEFAULT_DB_PATH` as a keyword default binds at function-definition time, not call time - would have made the default path unpatchable after import. Caught immediately by the new test isolation fixture raising `PermissionError` against `/etc/baseline` before the fix landed.
- Full suite: 1351/1351 (was 1349).

**Not done:** no real deployment has read/written this database from an actual pre-Proxmox/rescue environment yet - the "available prior to Proxmox" property holds by construction (no service dependency) but hasn't been observed at an actual early boot.

## 2026-09-28 - found and fixed why "build self installer" did nothing for real; made it the default, keyboard-free path

**Read decision record 86 first** (`docs/design/decision-records/86-self-installer-is-the-default-path.md`) - it has full detail; this is the short version.

**The actual bug behind "I typed my sudo password in to the install option and nothing happened":** decision record 85's `drive_admin.build_self_installer()` required `params["expected_serial"]`, `params["proxmox_source_iso"]`, `params["server_host"]`, `params["cert_path"]`, `params["key_path"]` - but `baseline_web.py`'s own JS never had a form field for any of them, only `device_path`. Every real click raised a server-side `KeyError`. This was a real design mistake caught by direct user feedback ("I will never fill in a serial number... everything must be selectable without a keyboard"), not a UI polish issue.

**What changed:**
- `self_installer.py`: `expected_serial`/`proxmox_source_iso`/`server_host`/`cert_path`/`key_path` are all now optional - auto-derived (real hardware serial via udevadm), auto-generated (fresh ephemeral TLS cert via `openssl req`), defaulted (`10.0.2.2`, the QEMU SLIRP gateway - the only address this mechanism can ever need), or auto-located (a fixed, real INSTALLER_CACHE-style search path list), each refusing clearly rather than guessing when it can't.
- `settings_store.py`: new `"self_installer"` group (`lvm_size_preset`/`fqdn`/`memory_mb`, all enum-constrained via a new `SettingDef.options` field, enforced in `set_setting`) - this is the actual "pre-populated data" mechanism the user asked for, reusing the existing Admin-tab schema store rather than a new config file. `DEFAULT_STORE_PATH` moved onto the `/etc/baseline` -> USER_PERSISTENCE redirect that already existed, per direct instruction that nothing outside USER_PERSISTENCE should be expected to survive reboot.
- `settings_web.py`: Admin tab's dropdown rendering generalized off `SettingDef.options` (was hardcoded to just the three volume-mode keys) - the new settings get real `<select>` controls for free.
- `drive_admin.build_self_installer()` now needs nothing but `device_path`. `ACTIONS` reordered so it's listed first; `install`'s description now says plainly it's a human-override-only path (persistence only, no bootloader, no OS) - not removed, just no longer presented as an equal, parallel option.
- Full suite: 1348/1348 (was 1339).

**Not done / left for next session:**
1. No real click-through of the corrected action against physical hardware yet this pass - the fix was found by code inspection (comparing what the JS sends to what the server required), not by re-running the failed attempt. `/dev/sdd` is still the real target (512GB SK Hynix, serial `FD01N6557110C271B`); `/dev/sdb` still has the empty `baseline_persist` LVM VG left over from the earlier "Install" mishap (harmless - drive was empty - but still real, current state).
2. Real hardware needs a Proxmox source ISO at one of `DEFAULT_SOURCE_ISO_SEARCH_PATHS` in `self_installer.py`, or the action will now cleanly refuse ("no Proxmox source ISO found") instead of crashing - check that path exists on the actual box before the next click.
3. QEMU SLIRP's `10.0.2.2` reaching the host-run `EphemeralAnswerServer` is still not empirically verified on this host - reasoned as correct, distinguished from the different, confirmed-broken `guestfwd` mechanism (decision records 15-16), but nobody has watched a real round-trip succeed yet.
4. Work-queue item #18 (run `homeassistant-lxc`/`haos-vm` under real QEMU) still untouched.

## 2026-09-27 late continuation - massive context gap discovered; one uncommitted test fixed; the physical disk-merge is confirmed still untouched

**Read this before touching anything.** This entry is from the same conversation thread as the original "2026-09-27 handoff" entry below (the one that starts the disk-merge investigation) - but a huge amount of work landed on this repo *from elsewhere* (git history, not this thread's own visible context) between that entry and this one: 19 commits, decision records 62-82, the entire persona/recovery-mode/admin-settings arc, and `docs/design/v0.1-work-queue.md` now shows **fully closed**. The "2026-09-27 continuation" entry immediately below this one is that other work's own handoff, written by whoever/whatever did it - it correctly notes the disk-merge thread is separate and not superseded. Confirmed directly: **the physical drives (`sdd`/`sdb`) were never touched by that other work either** - still exactly as the original handoff entry describes (real backups of VM 202/203 sitting on `/run/media/cane/8TB/Projects/Baseline_v01/`, nothing destructive run, plan agreed but not executed).

**Also superseded, no action needed**: the `persist_bind_mounts.py` module this thread was mid-way through hand-writing (the simple 3-path bind-mount version, for "credentials/config/logs should go to USER_PERSISTENCE") - decision records 62-78 already built a far more complete version of the same idea (multi-persona, `drive_installer.py`-integrated, with `switch_active_persona`/recovery mode/admin elevation on top). Don't resurrect the simple draft; read decision record 78 first to see what's actually there now.

**What this pass actually did, concretely:**
- Found real, substantial, **uncommitted** work already sitting in the tree: `baseline/lib/baseline_web.py` (473 lines) + `baseline/lib/drive_admin.py` (305 lines) + their tests (544 lines combined), plus edits to `control_panel_web.py`/`settings_web.py`/`test_settings_web.py`. `baseline_web.py`'s own docstring names it as **decision record 83** - "the merged Baseline web app... one running server exposing every page settings_web.py/control_panel_web.py already had... plus a new Drive Administration tab" per direct instruction ("merge those two together and add a Drive administration tab"). **No decision-record file for 83 exists yet, and none of this is committed.**
- Ran the full suite cold: **1 real failure** - `test_drive_admin_page_reachable_over_a_real_socket` expected the literal string `"Persistence backend"` in the rendered `/drive-admin` page; the page had a `<h2>Mounted volumes</h2>` heading instead. Checked what actually populates that table (`real_volume_state` → `drive_installer.collect_volume_usage`) - it's specifically the Baseline-managed persistence volumes, not a generic "any mounted filesystem" list, so `"Persistence backend"` is the semantically correct heading, not just a string the test wanted. Fixed with a one-line rename in `baseline_web.py`. **Full suite now 1276/1276 passing.**

**Left for the next session, in priority order:**
1. Write the actual decision-record-83 file (`docs/design/decision-records/83-....md`) documenting `baseline_web.py`/`drive_admin.py` properly - it doesn't exist yet despite the code referencing it by number.
2. Decide whether to commit the `baseline_web.py`/`drive_admin.py` work (it's real and tests pass, but nobody has reviewed it in this thread - it appeared already-written).
3. **The disk merge is still the oldest open real-world item**: pick a target drive (still "doesn't matter" per the user), get their explicit go/no-go on the QEMU-against-real-`/dev/sdd` install approach, then actually execute it. Nothing physical has changed since the original entry below.
4. Read decision records 62-83 properly before making further persona/persistence changes - this thread does not have full context on that arc and guessing at its design would be a real mistake.

## 2026-09-27 continuation - v0.1 work queue fully closed; V0.2 ready to start

A later continuation of the same day's session below (the disk-merge
investigation there is separate, unrelated work - still accurate as
its own historical record, not superseded by this note).

**What closed this pass:** `docs/design/v0.1-work-queue.md` items
25-29 - the entire multi-persona/recovery/settings arc decision record
76 started is now fully landed:

- **25** - persona-aware wiring (decision record 78): real
  mount/unmount + `switch_active_persona` in `persist_bind_mounts.py`;
  `scripts_inbox.py`'s `inbox_dir_for`; a stale-session refusal in
  `settings_web.py`; `/api/active-persona` on `control_panel_web.py`.
- **26** - Recovery Mode itself (decision record 81): real automatic
  entry wired into `persist_bind_mounts.main`, a guest-tier
  `/recovery` discovery page with no login anywhere on it, and the
  hard exit condition (refuses to leave without a real read-write
  persona volume) - explicitly not touching the withdrawn USB
  mechanism (decision record 77).
- **27** - automated recurring encrypted backup (decision record 79):
  new `backup_recurring.py` + systemd timer, honestly flagged as not
  yet targeting a genuinely separate physical device (none exists in
  this dev session).
- **28** - the Admin settings tab (decision record 80): a real
  `/admin` page on `settings_web.py`, gated on a real `admin_elevation`
  ticket for edits - the direct instruction itself had already
  answered "web vs TUI" ("essentially a version of the installer Web
  application").
- **29** - the full TDD audit itself (decision record 82) - see that
  record for the actual findings; short version: every module built
  across decision records 62-81 already had real, substantial
  FakeRunner-driven tests going in, so the audit's main output is
  confirmation plus one closed provision.sh staging gap
  (`settings_store.py`/`admin_elevation.py`/`recovery_mode.py`, caught
  by `tools/check_provision_deploys_all_imports.py` during this pass).

**Full suite at close: see decision record 82 for the exact count.**
`docs/design/v0.1-work-queue.md` has no remaining `[ ]` rows.

**V0.2 focus, per the user's own framing:** "Virtual Machines and User
Persistence capturing of data." One real, unresolved architecture
tension flagged directly to the user and **not** resolved by this
pass: `drive_installer.py`'s LVM-based multi-persona model
(`USER_PERSISTENCE_<PERSONA>` volumes inside Proxmox's own VG) does
not match the real, already-deployed `/dev/sdb` layout (plain GPT
partitions on a separate physical drive, no LVM at all) - reconciling
this is likely foundational V0.2 work, not a pre-existing decision to
build on.

## 2026-09-27 handoff - v0.1 queue items #14-16 closed; real install-ISO tooling proven; a live disk-merge is mid-flight, NOT executed

**Ending this session because it's out of tokens, not because the work is done.** The disk-merge work below is genuinely in progress - read the "Right now, unfinished" section before doing anything to either physical drive.

### What shipped this session (pushed to `origin`, tip `23a8ee0`)

Six commits, three decision records (57, 58, 59 were the prior session; this one added **60** and **61**):

1. **`vm_scripts.py`** - pinned + sha256-verified `community-scripts/ProxmoxVE` Helper-Scripts (resolves decision record 35's deferred item). Manifest: `debian-lxc`, `docker-lxc`, `homeassistant-lxc`, `pihole-lxc`, `debian-vm`, `haos-vm`.
2. **`quadlet.py`** - Podman + Quadlet host-service management (Track B4), rootless mode now fully implemented (real `getent passwd` lookup, `runuser -u <user> -- env XDG_RUNTIME_DIR=... systemctl --user`), default corrected to `rootless=False` (no sensible universal default user).
3. **Real QEMU proof, twice** - a disposable install actually reached a genuine, screendump-verified Proxmox login prompt. Found and fixed two real bugs neither module's fake-based tests caught: `repair.RealRunner.write_text_atomic` didn't create missing parent dirs; `systemctl enable` refuses a Quadlet-generated (transient) unit outright (fixed: `write_and_start`, uses `start`/`stop`, never `enable`/`disable`).
4. **Real, important disclosed finding**: `ct/debian.sh` run off-Proxmox doesn't fail closed - it silently took an "update in place" branch and ran real `apt` activity on the host in 8s. `docker-lxc` and `debian-vm` were also run for real afterward and behaved *differently again* (exit 113; exit 127 "pveversion: command not found") - behavior genuinely varies by script/kind, documented plainly in `vm_scripts.py`'s docstring rather than generalized from one data point.
5. **`baseline/bin/baseline-prepare-real-install-iso`** - new operator tool, operationalizes `docs/INSTALL.md` Step 2 for real (`--fetch-from http`, the only accepted mode for real hardware per decision record 02). Found and fixed a real bug (`prepare_iso_defensively` never created its own `--tmp`). Verified for real: hardware match -> 200, mismatch -> 403, replay -> 403.
6. **Hardware-pinning corrected mid-work, per direct instruction** ("hardware is expected to change with install"): the tool's `--target-mac`/`--target-dmi-product` are now optional, not required - `None` means "don't check this fact," relying on the session's other real properties (LAN scope, pinned TLS fingerprint, single-use, TTL) instead. Re-verified for real with a synthetic unknown machine - correctly accepted.
7. **`vm_scripts.py` unified with `pct_provision.py`/`vm_provision.py`** via a VMID-adoption bridge (`run_script_and_adopt`/`start_adopted`/`stop_adopted`/`destroy_adopted`) - creation still runs through the upstream script (unavoidable), everything after creation now goes through Baseline's existing tested primitives. Added `vm_provision.destroy_vm` (a real gap found while wiring this - only the persistence-preserving retire path existed before).
8. `packaging/baseline-drive-setup`'s executables were `777` (contradicting the package's own "read-only, root-owned" description) - fixed to `0755`/`0644`, rebuilt `.deb`, sent to the user.

Full suite: **922/922 passing.** `docs/design/v0.1-work-queue.md` items #14 and #16 closed; #15 partial (2 of 5 remaining scripts real-executed, `homeassistant-lxc`/`haos-vm` still only hash-verified - tracked as new item #18); #17 (real hardware) still blocked, unchanged.

### Right now, unfinished - a live disk-merge investigation, nothing executed yet

User decided to **merge the two physical drives** from `docs/INSTALL.md`'s table (`sdd`, the Proxmox substrate, serial `FD01N6557110C271B`; `sdb`, the persistence backend, serial `MD89N41071210AP4E`) into one - "not the end result and doesn't need to be the journey," both currently connected via USB to the dev machine (this machine, **not** the laptop), neither currently in the laptop.

**Real facts gathered, read-only, both drives left exactly as found (mounted/activated then cleanly unmounted/deactivated afterward):**

- `sdb`: all three partitions (`USER_PERSISTENCE`/`INSTALLER_CACHE`/`SESSION_TEMP`) are **completely empty** - 20K used each, just a fresh `lost+found`. Zero real data at risk on this drive.
- `sdd`'s `pve` LVM (VG size <475.94G, 16G free): `root` LV is 96G allocated but only **6.2G actually used** (7%); thin pool `data` is 352.74G allocated but only **~3.0G actually written** (0.85% data / 0.50% meta), all of it the two real VMs - `vm-202-disk-0` (4.2G alloc, 39.78% used, ~1.67G real) and `vm-203-disk-0` (5.0G alloc, 26.68% used, ~1.33G real), plus two negligible cloudinit disks. **Total real data across both drives: ~9.2GB** - smaller than the user's own "~25-30GB" estimate.

**Recommended plan, given to the user, not yet actioned:**
1. `sudo vzdump 202 203 --dumpdir <path> --mode stop` (or `--mode snapshot`) - back up the only two things worth keeping.
2. Fresh minimal Proxmox install on whichever single drive survives, via `baseline-prepare-real-install-iso` (already proven this session), with `root`/`data` deliberately sized small (~40G/40G instead of 96G/352G) to leave the rest of the drive for `USER_PERSISTENCE`/`INSTALLER_CACHE`/`SESSION_TEMP`.
3. `qmrestore` the two `vzdump` archives onto the fresh install.
4. Verify both VMs boot and match pre-migration state before wiping the now-redundant second drive.

Rejected: shrinking the existing thin pool/root LV in place - real risk combined with a physical-drive consolidation happening at the same time, for no benefit given how little real data exists to preserve.

**Still open, next session should ask the user directly rather than assume:**
- Which physical drive survives (keep `sdd`'s or `sdb`'s physical unit)?
- Proceed with the `vzdump` backup as step 1?

### A real, scoped sudoers entry now exists on this dev machine

`/etc/sudoers.d/claude-disk-inspect` (user-added, not by me): `cane ALL=(root) NOPASSWD: /usr/sbin/vgs, /usr/sbin/lvs, /usr/sbin/vgchange, /usr/sbin/pvs, /usr/bin/mount, /usr/sbin/vzdump`. Confirmed working (`sudo -n vgs` succeeds; `sudo -n true` correctly still fails since `true` isn't in the list - this is a narrow, scoped grant, not a blanket bypass). **Missing `/usr/bin/umount`** - `sudo -n umount` was needed for this session's own cleanup and wasn't in the list, yet succeeded anyway (cause not fully understood - possibly a separate cached ticket from the user's own terminal at the time); don't assume it will always work without a password. If the `vzdump`/reinstall plan above needs more commands (`lvresize`, `lvcreate`, `resize2fs`, `qmrestore`, `pct`/`qm` themselves), they are **not yet in this sudoers file** - ask the user to extend it rather than assuming broader access exists.

### Standing rule this session leaned on hard, worth repeating

Sudo credential caching is per-TTY (`tty_tickets`) - a session authenticated in the user's own terminal does not extend to a separately-launched Claude session even as the same Linux user. Don't assume a "the user just ran sudo" claim means *this* session can too; test with `sudo -n <cmd>` and take the real answer.

## 2026-09-26 status refresh - V0.1 remaining-work audit; starting V0.2

**Requested via chat:** "Note it in unfinished work but I want to
focus remaining 0.1 work and start onto 0.2 the revisions of 0.1 as
needed."

**What changed:** the "Not done" list below was six days stale
relative to this session's own work (Track A1-A5 real-hardware
Proxmox/persistence/kiosk/dashboard, Track B1-B3 GUI investigation,
harness session/write-grant decision records 31-33, and Track A6's
provisioning modules 34-36) and relative to Track A/B's still-earlier
completion in this same conversation. Re-audited item by item, in
place, rather than left to mislead the next session:

- **Done since the original note:** chat-tab multi-turn memory
  (record 31), a scoped/session-only write-access grant (records
  32-33), the real storage migration this project actually needed
  (Track A1/A2's two real NVMe drives), and the static-IP first-boot
  repair path (already solved by `repair.py`'s `reset_interface_to_dhcp`,
  proven live in Track A1 - the old note just predated knowing that).
- **Still genuinely open:** chat-tab streaming, the visible access-
  scope header, the condensed header bar, OSC 52 clipboard copy, the
  80x24 layout floor, additional harness adapters, and - new this
  session - real-hardware verification for `vm_provision.py`/
  `pct_provision.py`/`docker_provision.py` (blocked: no reachable
  Proxmox host, no Docker daemon installed in this dev environment).
- **Flagged as unclear rather than guessed at:** the old "LVM-reclaim
  manual fix" note names nothing specific enough to act on; may
  already be subsumed by Track A1/A2's real LVM work, may not be -
  ask directly before spending effort on it.
- **Confirmed still correctly scoped as V0.2, unchanged:** the phone-
  tether file/script exchange channel - the user's own current
  framing of it matches this doc's original 2026-09-20 scoping
  exactly.

**What this means going forward, per the user's own framing:** finish
what's genuinely still open under V0.1 (the list above) before
starting new V0.2-scoped work, and treat V0.2 as including *revisions
to V0.1 itself* as they're found to be needed - not only new features
layered on top. See the "Not done" section below for the current,
accurate list this applies to.

## 2026-09-24 session handoff - TestPersistence PRD + privacy-scan scope correction

**Repository state**
- Branch `main`, HEAD `71f6ab9` (`fix: widen prohibited-identifier scope; retract premature clean-content claim`), pushed to canonical `origin` (`cliffthelin/BaseLineProx`) - confirmed 0 ahead / 0 behind `origin/main`.
- Working tree: tracked files clean. Untracked and **not part of this session's work**: `backups/`, `sdc2.img`, `docs/design/.~lock.drive-setup-gui-v2-prd.md#` - leftovers from a separate, earlier task thread (a real `/dev/sdc` install plan, see the stale plan file referenced in that thread). Do not delete without investigating first; do not assume they're safe to discard.
- **Never push to `cliff` (`cliffthelin/baseline`).** `origin` (`cliffthelin/BaseLineProx`) is the sole canonical remote - unchanged, longstanding rule, see "Standing rules" below.

**What this session accomplished** (commits `1f10ae2` → `9e83d02` → `71f6ab9`, all on `origin/main`):
1. `1f10ae2` - added `docs/design/testpersistence-prd.md`, a design-only, entirely-synthetic PRD for Baseline's persistence architecture (storage classes, identity model, attachment state machine, access broker, application lifecycle, snapshot/recovery, failure behavior, 20-case acceptance matrix, milestone sequence). Recorded `physical-phase-p0-p1-plan.md`'s identity-scan gate as `pending_operator_verification` (never claimed passed).
2. `9e83d02` - **privacy finding**: the PRD's `Owner:` field carried a real personal name (outside the repo-account-metadata exception). Removed from current content. Also applied 12 architectural corrections to the PRD after independent review (logical-vs-carrier identity split, manifest/ledger authenticity requirement, honest statement that rollback cannot preserve revocation without a non-rollback ledger or monotonic anchor - made a Milestone-2 blocker, scoped clone-detection claims, automatic grant suspension on app disable/uninstall, isolated untrusted-content inspection mount spec, fixed an unknown-device state-machine contradiction, domain-separated test/production manifest authority replacing a mutable boolean, ownership split from application grants, corrected acceptance cases 4 and 20, reserved full-store recovery-ledger capacity).
3. `71f6ab9` - **scope correction**: the `9e83d02` commit's status block wrongly implied current content was clean once one field was fixed. Corrected: the repo-account exception covers GitHub URL/remote references only, not tracked-file personal-identity content. A targeted (non-protected) grep for the already-known identifier found it in two more tracked files - `docs/design/drive-setup-gui-v2-prd.md`'s `Owner:` field (removed) and `packaging/baseline-drive-setup/DEBIAN/control`'s `Maintainer:` field (replaced with a project-generic identity at a reserved `.invalid` domain). `packaging/.../copyright`'s `Copyright:` line was found but **deliberately left unchanged** - flagged as an unresolved policy conflict, not fixed unilaterally (see below).

**Verified state**
- Full pytest suite: **418/418 passing**, last run at HEAD `71f6ab9` (re-run after every edit in this session; not stale).
- Everything this session touched was pure Python schema/doc work with no disk I/O, no LUKS, no QEMU, no privileged operation - unit-tested only, nothing simulation/QEMU-tested and nothing physical-hardware-tested in this session.
- No physical drive was touched, mounted, written to, or installed to. No history rewrite, force-push, `git filter-repo`, ref/tag modification, or destructive operation was performed at any point.

**Current P0/P1 position** (see `docs/design/physical-phase-p0-p1-plan.md`, status block at the top)
- All implementation gaps, security hardening corrections, and coverage-accounting/interactive-scanner work described in that document are complete and previously verified (see that file's own "closed" sections - not re-verified again this session, no new evidence needed).
- The **next dependency-valid step for P0/P1 itself** is unchanged from before this session: the operator runs `python3 tools/interactive_denylist_scan.py` locally (hidden-prompt input, values never seen by Claude) to produce the first real `full_scan` result. Nothing else in P0/P1 is blocked on implementation work right now - it is blocked on that operator action plus the identity-scope questions below.

**Explicit unresolved decisions (operator-only, not implementable by an agent)**
1. **Copyright declaration** (`packaging/baseline-drive-setup/usr/share/doc/baseline-drive-setup/copyright`) - carries a personal-name copyright statement under the MIT license text. Left unchanged. Needs operator direction: keep as intentional individual ownership, or replace with a project-collective form. **Do not change this file** until that direction is given.
2. **Protected full current-content identity scan** - `identity_scan.current_content: pending_full_scan`. The fixes above came from a targeted grep for one already-known term, not the protected scanner, which can find identifiers this session didn't already know to look for. Only a clean `tools/interactive_denylist_scan.py` run (its `current_tracked` scope) can move this to `clean`.
3. **Git-history identity scope** - `identity_scan.git_history: known_findings_scope_unknown`. Not "one value in one commit" - given personal-identity content was found in three separate tracked files, older commits, refs, tags, and commit messages may carry it too, and none of that has been enumerated. A valid rewrite plan requires the operator's protected full scan (`git_history` scope) to run first, plus manual review of anything it can't reach (unreachable objects, other refs/tags, GitHub's own caches). **No rewrite has been proposed in executable form and none should be attempted without that scan plus explicit operator authorization.**
4. **Physical P0/P1 itself** - still entirely unstarted; blocked on the identity-scan gate (items 2-3) for final privacy closeout, not on any remaining implementation.

**Safety boundaries a continuing agent must preserve**
- Authority model stays `propose → validate → authorize → execute → verify → rollback` for anything consequential - do not skip straight to execute on drive/history/privileged operations.
- **A new agent continuing this work is not itself authorization** to run the identity scan's protected values, rewrite history, force-push, touch `/dev/sdX` or any physical drive, or change the copyright file. Those all still require the human operator, present and explicit, regardless of how much session/context has elapsed.
- Never print or reconstruct the personal-identity value that was found and removed - it has intentionally not been repeated anywhere in this document or the commits above.

**Recommended next task for a continuing coding agent**: none of the P0/P1-adjacent work is currently unblocked without one of the four operator decisions above. If further design work is wanted in the meantime, the TestPersistence PRD's own Milestone 2 (`docs/design/testpersistence-prd.md` §16) - pure schema/state-machine unit tests (dataclasses/enums for storage classes, identity model, attachment state machine, grant records; no disk I/O, no LUKS, no QEMU) - is the smallest dependency-valid unit that doesn't require any of the pending operator decisions, since it's synthetic-only and independent of the real identity-scan gate. No other physical-P0/P1-track task is safely startable right now.

---

Written from the CLI session that did tonight's bare-metal bring-up work,
for you to paste into / cross-check against the new Claude Project. I
have no access to that Project (it's a claude.ai web feature, not
reachable from this CLI session), so I can't verify what did or didn't
transfer - this is the definitive account from this side, not a diff.

## READ THIS FIRST - active drive incident, resolved; full backups now exist

Filesystem is healthy (see the "UPDATE" entry further down). After that
recovery, **three complete, checksum-verified backups were made** with
the drive in its now-healthy state (no corruption this round - `tar`
worked normally, 97,210 files each in the two full ones):

| File | Size | Locations | sha256 |
|---|---|---|---|
| `Private_Baseline_files.tar.gz` | 61KB | this CLI machine's `/run/media/cane/CACHE/baseline_repo/backups/`, laptop `/root/backups/`, sent to the user directly | `50d38279b201097ee68dd969f61daa40745c7ea6a39bb2837112d330ad8d5396` |
| `baseline-fullroot-20260920-185140.tar.gz` | 2.40GB | CLI machine's `backups/`, laptop's internal Ubuntu drive `/mnt/baseline-backups/` | `759ee9a9d814e05454d3ad5b9da0f6ba5b0d1f9ed61b94072af53d578493aceb` |
| `baseline-tight-20260920-185838.tar.xz` | 1.91GB | CLI machine's `backups/`, laptop `/root/backups/` | `7e946e28bec0f36e9171c2db5ed51458e0f1a03922692247f408bcc9bcdec5aa` |

`Private_Baseline_files.tar.gz` contains real secrets (OAuth token, SSH
host/root private keys) - same handling rule as everywhere else in this
doc: never public, never GitHub. The two full-root archives exclude
only `/proc /sys /dev /run /tmp /mnt /media /lost+found` and stay on
one filesystem (`--one-file-system`); expect harmless `tar` warnings
for postfix's unix-domain sockets and one "file changed as we read it"
for the live `/var/lib/lxcfs` fuse mount - neither affects integrity
(both archives passed `gzip -t`/`xz -t` plus a full `tar tzf`/`tar tJf`
listing).

The earlier partial/corrupted backups from during the incident
(`partial-verified-20260920-1817.tar.gz`, the failure logs) are still
in `backups/` too - superseded by these for restore purposes, but kept
since they're small and document what the degraded state actually
looked like.


The laptop's boot drive (a 28.7GB USB stick, `/dev/sdb`, holding the
`pve-root` LVM volume that everything runs from) had a real failure
event. **A verified, uncorrupted partial backup now exists** (see
below), but the drive itself is still degraded/read-only and the root
cause (wedged software state vs. genuine media failure) is still
unresolved. Whoever continues this needs to pick up here before
anything else.

**Timeline (2026-09-20):**
- `16:01:40` - kernel logs `usb 2-1.2: USB disconnect, device number 4`
  for the boot drive.
- `16:01:47` - ext4's journal aborts, several `Buffer I/O error`s, the
  root filesystem (`dm-1`, i.e. `pve-root`) remounts itself read-only
  (`errors=remount-ro` kernel safety trigger). Confirmed still
  read-only as of the end of this session (`touch` fails with
  "Read-only file system").
- User confirmed the physical USB connection is seated ("It's plugged
  in"). No new USB disconnect events logged since. Reads continue to
  mostly fail regardless (see below) with a stable connection, which
  points more toward (b) below.
- A full filesystem walk (via Python, since `/usr/bin/tar` itself fails
  to execute with a consistent I/O error) hit **15,372-15,373
  I/O-error failures out of ~18,338 files attempted (~84% failure
  rate)**, spread across essentially every directory - not localized.
  **`/usr/bin/rsync` also failed to execute** with the same I/O error
  pattern as `tar`, while `python3`, `cat`, and plain file reads kept
  working reliably throughout. Two different, unrelated system
  binaries failing to load points toward (b) **genuine, fairly
  extensive media failure** on the drive, more than (a) a simple
  software wedge - not conclusively proven, but the working theory.
- **Three backup attempts; the third succeeded and is verified valid**:
  1. Python `tarfile.add()` directly - corrupted (writes the tar header
     before copying content, so a read failing partway through a file
     desynced everything after it in the stream).
  2. Buffered each file fully into memory first (should have avoided
     the above) - **still corrupted**, breaking after 4247 entries.
     Root cause never fully identified - suspected but unconfirmed:
     `tarfile.gettarinfo()`'s PAX-header prep may use stat-time size
     before the manual `ti.size` override, desyncing PAX-format
     entries specifically. Do not reuse `tarfile` for this host without
     understanding that first.
  3. **Abandoned `tarfile`/any archive-format library entirely.**
     Custom minimal framing (tag byte + length-prefixed path + length-
     prefixed data, written by a remote Python process, parsed by a
     local Python process into individual real files on local disk -
     see `remote_backup3.py`/`local_receive.py` (neither is in the repo as of 2026-09-30, v0.2 row 31: treat as obsolete or never committed) if still present in
     that session's scratchpad, otherwise trivial to rewrite from this
     description) - **worked cleanly**: 2966 files, 417MB, local
     receiver's count matched the remote sender's count exactly, zero
     errors. Repackaged locally (purely local tar of local files, no
     remote I/O involved, so no corruption risk) into
     `partial-verified-20260920-1817.tar.gz`, 139.8MB,
     sha256 `6a03a37ad58e8c6744d6e3e3e069446583044891b0d158c2081e19e82e454d09`
     - **both `gzip -t` and `tar tzf` pass cleanly on this one.**
     Contains the real, critical files: all of `/opt/baseline`
     (including `bin/baseline` itself, which `tar` couldn't read),
     `/etc/systemd/system/baseline.service`, `/etc/baseline/*`
     (**including the live `harness.env` OAuth token and
     `interface_aliases.json`**), and `/etc/ssh/ssh_host_*_key`
     (**including the private host keys**).
  **This archive contains live secrets - never commit it to the public
  BaseLineProx repo or any public location.** It was sent directly to
  the user via chat only. The two earlier *corrupted* archives were
  deleted (not useful, superseded by the working one); the raw failure
  logs from attempt 2 were kept and also sent to the user directly.
- **Still not captured**: ~13,605-15,372 files (the ~84% that fail to
  read at all right now) - most of the base OS, kernel, `/boot`, most
  of `/usr`. This partial backup is enough to reconstruct Baseline's
  own app/config state on a fresh OS install; it is **not** a full
  system image.
- **UPDATE: user rebooted the laptop themselves** (not explicitly
  authorized in chat first - happened directly at the physical
  console). Boot log showed a new, alarming symptom: `WARNING: VG name
  pve is used by VGs 58P3UX-...-2OEmuD and wdSVr9-...-JW1rDy` (two
  volume groups both named "pve") and the `getty.target` ordering-cycle
  skip message from earlier in the session (docs/changelog/boot/001.md)
  reappearing. Also, immediately post-boot, all network interfaces
  showed `carrier_present: FAIL` (no link at all), so SSH was
  unreachable for a few minutes.
- **Once network came back, the picture resolved cleanly - genuinely
  good outcome:**
  - `/` is mounted `rw` again and a live write test succeeded - the
    read-only state is gone.
  - **`tar` and `sha256sum` both load and run normally now** - the
    "binary fails to execute with I/O error" symptom that drove the
    "genuine media failure" theory is **gone**. In hindsight this was
    very likely a software-level wedge from the ext4 journal abort
    (widespread defensive read failures cascading from one bad
    write), not permanent media death - a clean reboot + fsck fixed
    it. The `full_inventory()` "Display" fact investigation two
    reboots earlier turned up the same kind of lesson: be skeptical of
    "the drive is dying" conclusions drawn from software-observable
    symptoms alone without independent hardware evidence (SMART data,
    which was never actually obtained this session - no `nvme-cli`
    installed, no non-interactive `sudo`).
  - The duplicate-VG warning also resolved: `vgs`/`pvs` now show
    exactly one clean `pve` VG on one PV. The PV's device path moved
    from `/dev/sdb3` (throughout this whole session) to **`/dev/sda3`**
    this boot - device-letter reassignment across a reboot is an
    *already-documented* gotcha from earlier in this project (see
    `docs/BAREMETAL_BRINGUP_NOTES.md`). The "duplicate VG" message was
    almost certainly LVM's boot-time scanner catching the same
    physical volume at two different transient device paths before
    udev finished settling names, not a real second installation.
  - `baseline.service` is active and healthy post-reboot;
    `getty.target` itself is genuinely active (not skipped) once boot
    settled, so that regression didn't stick either.
  - **Do not assume device paths are stable** - `/dev/sdX` letters can
    and do change across reboots on this hardware. Anything hardcoding
    `/dev/sdb` specifically (there is nothing in the Baseline app
    itself that does - it resolves interfaces/devices by name/driver,
    not hardcoded paths - but double-check any new scripts) needs to
    tolerate this.
- **Net assessment, revised**: this looks recoverable/transient rather
  than terminal hardware failure, but it demonstrably CAN wedge the
  whole filesystem read-only and take multiple system binaries down
  with it under some trigger condition that was never root-caused
  (what actually caused the original `usb 2-1.2: USB disconnect` at
  16:01:40 is still unknown - cable, power, or a real intermittent
  fault in the drive/enclosure). Don't consider this fully closed -
  keep the backups made tonight, and treat a recurrence as reason to
  actually get real SMART/health data on this drive before trusting it
  further.

**Recommended next steps for whoever picks this up:**
1. Filesystem and service state are healthy as of the end of this
   session - no immediate action required, but this incident is real
   evidence the boot drive needs closer monitoring (real SMART data
   would help - not obtained this session) and that the NVMe-migration
   conversation from earlier (see "Not done" below) is worth prioritizing
   even though nothing is on fire right now.
2. If it recurs, reuse the working custom-framing approach (attempt 3
   in the earlier account of this incident, still above), not
   `tarfile`/`tar`/`rsync` directly - all three were unreliable while
   the filesystem was in its degraded state, for reasons not fully
   understood.
3. Get explicit authorization before rebooting the laptop in the
   future - this time it happened without an explicit go-ahead logged
   in chat.
4. Handle `partial-verified-20260920-1817.tar.gz` as containing live
   secrets (OAuth token, SSH host private keys) - never push it
   anywhere public.

## Do this first (before anything else works)

**SSH access to the laptop needs to be re-established.** The key I've
been using all session lives at a path inside *this* session's own
temporary scratchpad directory - it does not exist anywhere the new
Project can reach. Either:
- Generate a fresh keypair from the new Project's environment and add
  the public half to the laptop's `~/.ssh/authorized_keys` (you'll need
  physical/console access to do that one-time step - `baseline`'s
  Console tab or the Proxmox round-trip feature, see below, both give
  you a shell), or
- Copy an existing private key into wherever the new Project's
  persistent storage is, if one is being kept.

**The laptop's IP changes.** It's DHCP (`vmbr0`), currently
`10.0.0.133`, but it has changed at least twice already this session
(`.181` -> `.133`). Don't hardcode it as fact anywhere; check via
`ip -4 -o addr show` over the console, or your router's DHCP lease
list, before assuming SSH will connect.

## What exists and where

- **Live device**: a Dell Latitude 5290 laptop, Proxmox VE 9.2 bare
  metal, `baseline.service` owns tty1 (real console, not a VM/QEMU
  session at this point in the project).
- **Source of truth repo**: `/run/media/cane/CACHE/baseline_repo` on
  this machine (persistent storage - `/tmp` and drive-letter paths were
  both burned early in the project as unreliable across reboots, see
  `docs/BAREMETAL_BRINGUP_NOTES.md`).
- **GitHub**: <https://github.com/cliffthelin/BaseLineProx> (public),
  `main` branch, tip commit `07eda93` as of this handoff - confirmed to
  contain everything described below.
- **Deployed app path on the laptop**: `/opt/baseline/{bin,lib}`,
  `/etc/baseline/` (preferences/aliases/auth token), `/etc/systemd/
  system/baseline.service`.
- A **second, pre-existing private repo**, `cliffthelin/baseline`,
  unexpectedly received a push from this session too (a `git remote`
  mix-up - see the git-workflow note below). I don't know its history.
  Worth checking directly whether it should be archived/deleted or is
  intentional and predates this session.

## Standing rules the user has set (do not relitigate these)

- **Never use theme/variable colors** ($primary, $surface, etc.) in any
  Textual CSS - always explicit hardcoded hex. This has caused multiple
  illegible-UI bugs already; the bare `TERM=linux` framebuffer console
  renders theme colors unreliably.
- **No fake/decorative buttons or forms.** Every control must do a real
  thing. Where real functionality isn't ready yet (e.g. hardware
  Configuration tab), say so honestly in the UI rather than faking it.
- **Implement real functionality now, don't defer it** - the user has
  explicitly rejected "wait and build it properly later" multiple
  times.
- **No non-ASCII characters anywhere in rendered output** - found and
  removed the app's only Unicode use (arrow glyphs) after multiple
  `TERM=linux` rendering bugs this session; the bare console's font
  can't be assumed to have arbitrary glyphs.
- **Never open a new file descriptor to `/dev/tty1` (or any tty device
  node) from within the running Baseline process.** An earlier attempt
  to do this (for a character-grid query) correlated with real console
  font-table corruption ("garble") that persisted across service
  restarts. Use `os.get_terminal_size()` (reads the process's own
  already-open stdout) instead - see `docs/changelog/hardware/001.md`
  and `boot/001.md` for the full story.
- **Verify before declaring anything done.** The established pattern
  all session: edit locally -> deploy to the laptop -> run a headless
  Textual pilot test (`app.run_test()`) reproducing the actual
  interaction -> restart the service -> confirm stability via
  `systemctl status` (immediate + after a few seconds, to catch crash-
  loops) -> ask the user to visually confirm on the physical screen,
  since no screenshot pipeline exists for this console.
- **Every deployed change gets a change-log entry.** See
  `docs/changelog/INDEX.md` - check it first, it points to category
  files (boot/hardware/network/ui/chat), each an append-only, rotating
  block. Use `docs/changelog/TEMPLATE.md` for the entry format
  (Context/Considered/Requirement/Files changed/Verification/Pointer
  update/Docs update). This is a standing process now, not a one-off.

## What's actually done (verified live, not just written)

- Full vertical-slice PRD V0.1: boot to a Baseline prompt on tty1,
  deterministic hardware status (`inxi`-based), network bring-up
  (wired/Wi-Fi/USB-tether) with per-stage Lifeline diagnostics, a
  read-only Claude Code harness (zero tools, hardware/network JSON as
  its only context).
- A full Textual TUI (Hardware/Network/Chat/Console tabs) replacing the
  original plain Rich console output, with real keyboard navigation
  (Tab/Down/Shift+Tab, all independently verified working), explicit
  hardcoded colors throughout, and crash containment (Textual treats
  any unhandled exception as fatal to the whole app - confirmed in its
  own source - so render callbacks and event handlers are wrapped to
  log-and-continue instead).
- **Hardware tab**: shows every `inxi` fact (not a curated subset),
  grouped, each row opening a modal (Details/Description/
  Troubleshooting/Logs/Configuration - last four are honest
  placeholders).
- **Network tab**: correct Available-vs-Unreachable logic for wired vs.
  wireless links, IP + live traffic on the main row, and a
  `ConnectionModal` per interface with real bridged hardware identity
  (manufacturer/model/connection-type/driver, via `udevadm` - works for
  onboard and USB devices alike), a renameable, persisted alias, a real
  working Enable/Disable, Primary/Fallback as a genuine arrow-navigable
  toggle (not two momentary buttons), and its live position in the
  Lifeline chain when it's the active device.
- **Boot/console robustness**: fixed a `getty.target` systemd ordering
  cycle that could hang boot entirely; fixed `inxi` failing under the
  service's minimal environment; fixed console font-table corruption
  via an `ExecStartPre` `setfont` plus a standalone, re-runnable check
  (`tests/console_font_check.sh`, also wired into `provision.sh`).
- **A real Proxmox<->BaselineOS console round trip**: `(p)` inside
  Baseline switches tty1's physical console to tty2, which starts a
  genuine, unmodified login prompt (systemd-logind auto-starts the
  getty - no unit needed enabling by hand); a `baseline` shell function
  (installed system-wide via `/etc/profile.d/`) switches back to tty1
  without disturbing Baseline's already-running state. **Login stays
  required on the Proxmox side by explicit user decision** - not
  bypassed, don't add auto-login without asking again.
- This change-log system itself (`docs/changelog/`), backfilled with
  tonight's work.

## Not done - open items for the new Project

**Re-audited 2026-09-26** (this section was stale relative to the
Track A/B and harness-session work done since 2026-09-24; edited in
place against current reality rather than left to mislead the next
session - see the 2026-09-26 status-refresh entry near the top of this
file for what changed and why):

1. **Chat tab quality** - partially done. `--session-id <uuid>` +
   `-c/--continue` for real multi-turn memory: **done** (decision
   record 31, `harness.HarnessSession`/`build_ask_argv`). A named,
   auditable, scoped write-access control: **done, but narrower than
   originally proposed** - not a general `--allowedTools`/
   `--disallowedTools` toggle, but an explicit, operator-initiated,
   session-only `WriteGrant` (decision records 32/33; `grant write
   <directory>`/`revoke write` console commands). Genuinely still
   open:
   - `-p --output-format stream-json` for real incremental streaming:
     **done, scope stated precisely** (decision record 41) - the
     answer is available as soon as the assistant event lands rather
     than blocking until the process exits; NOT per-token typing
     (that needs `--include-partial-messages`, deliberately not
     tested this pass to limit real API cost). Not yet verified live
     on a real boot.
   - A visible header item showing the live-granted scope (session
     id/started state, active write grant if any): **done** (decision
     record 37, `harness.describe_session`, Chat tab's `#harness_status`
     line) - not yet verified live on a real boot, no real hardware
     access this session.
   - The condensed one-line header bar: **done, narrowed** (decision
     record 39) - `BaselineOS | <access scope + memory> | c=copy`;
     `tabs` and `datetime` deliberately not duplicated since
     `TabbedContent`'s own tab strip and `Header`'s own clock already
     show them. Not yet verified live on a real boot.
   - Real clipboard "copy" via OSC 52: **done** (decision record 38,
     `clipboard_osc52.build_osc52_copy_sequence`, Chat tab's `c`
     binding) - sends the sequence, does not and cannot confirm a
     terminal actually applied it; still not verified over this
     console/SSH path, no real hardware access this session.
   - Embedding the actual interactive `claude` CLI in a raw PTY widget
     remains explicitly **rejected**, unchanged from the original
     reasoning.
   - See `docs/changelog/chat/001.md` for the full decision record.
2. **Screen-size-appropriate layout** - partially done. The status
   bar (decision record 42) now provably never exceeds an 80-column
   budget for any write-grant scope path length - the one concrete,
   self-inflicted floor risk found in this pass. Other widgets
   (`DataTable`s already use flexible `1fr` heights and Textual's own
   scrolling) weren't individually audited for the same floor - not
   yet verified on a real 80x24 terminal either way.
3. **Storage migration** - **superseded, not open.** This 2026-09-20
   note (a candidate 512GB NVMe, pending a speed test) is the same
   role Track A1/A2 (2026-09-26) filled for real: `/dev/sdd` (Proxmox
   substrate) and `/dev/sdb` (shared LVM-thin persistence backend) are
   both real 512GB NVMe drives, installed, validated
   (`physical_device_safety.py`), and verified live. No further
   speed-test/migration action is needed.
4. **Static-IP first-boot repair** - **done, not open.** The 2026-09-20
   note ("documented but not folded into `provision.sh`") predates the
   actual architectural resolution: Milestone 1's Gates A-F (decision
   records 20-27) deliberately did **not** fix this in `provision.sh`
   at all - `docs/design/decision-records/11-repair-branch-comparison.md`
   found `repair.py`'s `reset_interface_to_dhcp()` already solved this
   fault class as a first-boot discovery+repair action, integrated into
   `firstboot_statemachine.py` and proven live on real hardware in
   Track A1 (2026-09-26). Nothing further is needed here.
5. **"LVM-reclaim manual fix" note** - **unclear, likely stale.** No
   other document in this repo names what specific reclaim step this
   2026-09-20 note referred to. Track A1/A2 (2026-09-26) did extensive
   real LVM work on both drives (deactivating a stale duplicate `pve`
   VG by exact UUID, wiping signatures, building an LVM-thin pool) -
   this note may already be subsumed by that, or may refer to
   something else entirely. Flagged rather than guessed at; ask the
   user directly if this still means something specific before
   spending effort on it.
6. Older, still-open items, carried forward unchanged:
   - Provider "configuration forms" deliberately still not built - by
     design, not an oversight (credential handling stays out of
     Baseline's own hands - see `baseline/lib/harness.py`'s docstring).
   - File-transfer/shared-folder capability for the phone-tether rescue
     channel - **still scoped as v0.2, still not started.** The user's
     own framing in this project's 2026-09-26 conversation ("the tether
     to phone... still needs the file and script exchanges") confirms
     this is still the right v0.2 scoping, not superseded by anything
     built since.
   - **OpenCode is now implemented** (decision record 44) - the second
     real `HarnessAdapter`, normalized through real ACP (Agent Client
     Protocol, an open standard OpenCode's own `opencode acp` speaks
     natively). A real, live round trip was confirmed against the
     actual binary, including a real discrepancy caught between ACP's
     own docs and its actual wire bytes. Has no write-grant support -
     honestly absent, not guessed at, since ACP's own permission
     mechanism hasn't been checked against decision record 32's
     specific shape. Hermes/Pi/DeepSeek/GrokBot remain listed-but-
     unimplemented; the dispatch layer (decision record 43) makes any
     of them a drop-in whenever the user names one and its CLI turns
     out to be checkable the way `claude`/`opencode` both were.
7. **A full audit (2026-09-26, decision record 47) found a real,
   provable contradiction in this session's own record**: commit
   `e82c6e4` claims "Real-hardware-verified... on the live Track A1
   Proxmox install" for Track A3/A5's modules; decision record 45,
   written hours later the same day, says "this session cannot verify
   anything on real Proxmox hardware at all." Neither can be fully
   right. The working plan's Track A1-A5 "STATUS: complete, verified
   on real hardware" claims have no decision record behind any of
   them and are now marked corrected/unconfirmed in place - see
   decision record 47 for the full account. A2's claimed
   `baseline-persist` LVM-thin backend specifically does not exist on
   `/dev/sdb` today (it's plain ext4, decision record 46) - do not
   build anything assuming it does.
9. **See `docs/INSTALL.md` now - the definitive install runbook this
   project didn't have, written 2026-09-26 after an audit found no
   single document (this one included) actually tells anyone how to
   build a working Baseline drive install.** Two real gaps it closed
   with new code rather than narration: `persistence_pool.py` (the
   LVM-thin pool Track A2 built once by hand, never scripted) and a
   documented, code-reuse-based procedure for the real Proxmox install
   (turns out `drive_setup_install.py`'s existing QEMU invocation
   builders already accept a real block device path directly - no new
   code was needed there, just writing down the correct combination
   for the first time). Neither has been run for real yet - see that
   document's own status table, which is meant to be corrected in
   place the first time someone actually runs it, not left to go stale
   the way this section's own prose repeatedly has.
10. **Real-hardware verification is blocked for three provisioning
   modules; the chat harness half is NOT blocked and has now been
   checked for real.** `vm_provision.py`/`pct_provision.py`/
   `docker_provision.py` (decision records 34-36) are still unit-tested
   against fakes only - no `qm`/`pct`/`pvesh`/Docker daemon reachable
   from this dev environment. But this same environment turned out to
   have a real, working `claude` CLI all along - used directly
   (decision record 40) to verify records 31-33's flagged unknowns:
   session continuity (`--session-id`/`-c`) works exactly as designed;
   the write-grant argv had a **real bug** (`Write(...)` isn't a valid
   permission rule - the CLI wants `Edit(...)`, and `--allowedTools`
   alone isn't sufficient without `--permission-mode acceptEdits` too)
   - found and fixed. The scope boundary itself was confirmed to hold
   against a real, adversarially-worded out-of-scope write attempt.

## Where to look for more detail

- `docs/changelog/INDEX.md` - check first, points to everything else.
- `docs/BAREMETAL_BRINGUP_NOTES.md` - accumulated real-hardware gotchas
  (QEMU vs. bare-metal VT-switching, DHCP client quirks, USB tethering,
  the dhclient `-timeout` bug, etc.).
- `docs/adr/0001-bare-metal-network-bootstrap.md` - the two network
  route-selection bugs found early on, written up as an ADR.
- The original PRD context lives in this chat's history, not yet
  extracted into a repo doc - if the new Project needs it and doesn't
  have it, ask for it explicitly rather than assuming it's here.


## 2026-10-01 — DR118 distro containers

Read DR118 and verification/118 before continuing. Actual native Proxmox LXC
create/boot/rebuild preserved home/root/data for 11 families; openEuler setup
failed and is disabled. Its incomplete reservation once recorded ID119, now
used by the valid openSUSE base: do not destroy119 for failed-template cleanup.
Actual web Alpine CT125 create/shutdown/rebuild passed. Physical drives unchanged.
Nine requested distro systems are listed truthfully but not installed; UEFI
ISO selection and retained-disk size controls added. Remaining work row73,
including OMV NAS disks, GrapheneOS emulator and requested Linux ISO installs.
Bind-data backup/restore is still row60; full deploy/reboot remains row72.


## 2026-10-01 — DR119 application/OS audit

App Isolation runtime claim corrected to plan checks. Read
`design/application-layer-audit-2026-10-01.md` and queue74 before applying plans.
No runtime confinement or physical app mounts proved; existing OS overlay
proofs remain valid but aren't per-app isolation. User authorized GitHub push
to current origin/upstream branch. History DR117/118 preserved.


## 2026-10-02 — DR120 functional coverage

GitHub push completed and remote branch verified at6a806d8. User clarifies AI
builds the software means; it must not act as the software during normal use.
Read `design/functional-gap-audit-2026-10-02.md` F01–F12. Existing Operations
schedules are software-owned; app lifecycle, durable workload jobs/recovery,
retained guest restore and distro acquisition/install remain gaps. New row75
for jobs/reconciliation; no new runtime or physical verification claimed.


## 2026-10-02 — DR121 durable workload increment

VM/LXC actions now use durable asynchronous jobs, authenticated status and
inspection/acknowledgement after restart, request deduplication, and one-time
login retrieval. Managed running containers support real login rotation.
2,874 unit tests passed; actual Alpine creation/rebuild with retained document
and service-restart handling passed in disposable Proxmox-in-KVM. Interruption
was during preflight, not destruction; no physical write/deployment or app
confinement proof. Queue75 remains partial; see DR121 and verification/121.


## 2026-10-02 — DR122 bounded rebuild recovery

Recover rebuild is now application-owned for a proven absent OS or an owned
stopped partial clone, preserving retained folders. Actual disposable Proxmox
service interruptions after deletion and after cloning recovered with the
document intact; reused CT119 refused, valid openSUSE base unchanged. 2,882
guarded unit tests passed. No physical writes/deployment, running partial-clone
or power-loss recovery proof, or application-confinement claim. Queue75 remains
partial; backup59/60 and application lifecycle74 are still open. See DR122.


## 2026-10-02 — DR123 Ubuntu VM login workflow

Managed Ubuntu/Proxmox Reset login is implemented as a confirmed durable job,
with native stdin password hashing, one-time result and retained profile journal.
Pending rotation blocks OS rebuild; explicit fresh reset resolves it when ready.
2,892 unit tests; actual guest password verification and retained hash/document
checks passed in disposable KVM. Post-rebuild boot needed the earlier restricted
test-network apt proxy settings restored to the same OS seed; no ordinary-network
or physical firstboot proof. Other VM types/backends and partial-state recovery
remain queue75; backups59/60 and app lifecycle/isolation74 remain open. See DR123.

## DR124 incremental handoff — 2026-10-02

Stopped managed LXC retained backup and confirmed new-name restore now work
through durable authenticated web jobs. Real Alpine native Proxmox-in-KVM proof
retained home/root/data, ACLs/user xattrs and fresh login, preserved original and
unrelated backup files, and survived service restart. Separate virtual backup
disk only: no physical off-drive proof or physical writes. Coverage excludes OS,
/etc, immutable base and original hash. Same-host unchanged-base restore only.
See decision record124 and verification/124. Rows59/60/73/75 remain partial;
full VM recovery, incomplete restore reconciliation and row74 applied application
lifecycle/isolation remain open. No direction from the user is currently needed.

## DR125 incremental handoff — 2026-10-02

AppData planner prerequisites fixed with RED/GREEN tests: collision-free encoded
state-directory keys, lexical target validation and nested/equivalent conflict
reporting. 67 focused planner tests passed. No runtime sandbox or hardware work.
Queue74 remains open; next applied path is Chromium inside Ubuntu, selected
mounted AppData, real identity/migration/launch and two-app separation evidence.
Unknown/stateless declarations and Quadlet runtime mount checks remain open.
No new direction required from the user. See decision record125.

## DR126 installer/template audit handoff — 2026-10-02

Current request: audit installer integration, durable-state rebuild and stackable
content-free OS/app configurations. Audit recommends one app with reusable recipe
engine and guest reconciler, preserving substrate installer boundaries. Distinct
operations: retained rebuild, configuration export, fresh instantiate, private
backup restore. Raw overlays cannot be automatically treated as settings-only.
Detailed wiring/acceptance: design/installer-overlay-template-audit-2026-10-02.md.
Row76 added; rows72–75 remain open. Design/source audit only, no runtime change.
Next implementation: recipe contract/coverage and first Ubuntu/Chromium adapter;
keep unsupported capabilities explicit and no AI runtime dependency.

## DR127 incremental handoff — 2026-10-02

Recipe validator/export/digest/stack compose+verify and baseline-recipes CLI now
exist and are staged by provision. Strict initial Ubuntu/Chromium allowlists;
no runtime apply, install or configuration capture. 11 focused tests use real
parser/subprocess CLI. Queue76 remains partial; next wire provenance/package locks,
web controls and Ubuntu guest reconciler. Queue74 app migration/isolation and
rows59/60/75 broader backup/recovery still open. No hardware or credentials touched.

## DR128 incremental handoff — 2026-10-02

/recipes now exposes DR127 validation/compose/verify/export to authenticated
admins, with local-file/text input and explicit undeployed/source-unverified
results. Actual local HTTP and parser/CLI tests pass; no native guest, browser
automation or hardware proof. No persistent input store or workload mutation.
Next queue76 work: verified acquisition/package locks and Ubuntu guest adapter;
queue74 runtime profile migration/isolation and earlier backup/recovery remain
open. No direction needed from user for this increment. See DR128/verification128.

## DR129 incremental handoff — 2026-10-02

User expanded requirements to existing-app extraction plus clean test-install and
recipe apply, and replacement-device restoration with original storage absent.
First implementation: durable inspect_app in managed Ubuntu/Proxmox VM via
read-only dpkg-query, with human controls on /recipes. Reports metadata/locations
only; recipe_ready/test_install_verified false. Other media/containers, content
classification/export and clean install remain queue76. Replacement recovery row77
added. Existing queue74 isolation and59/60/75 recovery still open. See DR129 and
verification129; no physical writes or deployment claimed.

## DR130 incremental handoff — 2026-10-02

User examples: VS Code first, Spotify second. Implemented five-setting JSONC
preview/export, CLI capture/new-profile stage. Actual installed Linux VS Code
consumed staged settings under Xvfb; no original profile/accounts read. No new
binary install or VM/container/isolation proof. 25 focused tests passed.
Planned/not-done table: design/application-examples-remaining-work.md. Next bind
verified installation source and recipe to managed fresh target installation;
keybindings/snippets/extensions and Spotify adapter still open. Queues74/76/77
and broader59/60/75 recovery remain open. See DR130 and verification130.

## VS Code locked fresh archive build (DR131 — 2026-10-02)

`baseline-vscode-build lock SETTINGS` resolves publisher metadata into a Linux-x64
version/commit/URL/SHA256 lock with the approved configuration. `verify BUILD`,
`fetch BUILD NEW_ARCHIVE`, and `install BUILD ARCHIVE NEW_TARGET` validate, download
and materialize exact bytes plus a new profile/extensions directory. Existing
targets refuse; failed downloads/installations can retain explicitly incomplete
files. HTTPS metadata plus hash verification is not a detached signature.

Actual fresh VS Code1.140.0 archive launched under Xvfb and read all five settings;
runtime version/commit matched the lock. No managed VM/container installation,
physical deployment, OS rebuild or app confinement proof. CLI installation itself
reports runtime_verified:false until independently tested. Evidence verification/131.
Generic recipe-stack integration, durable guest install, dependency handling,
persistence/isolation and Spotify remain open under74/76. No earlier runtime claim
is invalidated; DR130 remains the historical installed-copy test.

## Repeatable adapter direction (DR132)

Use [the OS/application adapter pattern](design/repeatable-environment-adapter-pattern.md) for each new platform:
shared discover/capture/lock/acquire/install/verify/rebuild phases, explicit native
capabilities and a test-first extension checklist. Current Ubuntu recipe and
Linux-x64 VS Code limits remain; this document adds no cross-OS runtime support.
Generic integration and managed reconciliation remain queue76; isolation remains74.

## 2026-10-03 — DR138 installer editor

Authenticated /install-plan now edits, freshly validates, previews and exports
install plans without executing stages. Actual browser tests used synthetic
discovery; native read-only discovery of the two actual SK hynix drives worked
and refused missing APPDATA_ADMIN/APPDATA_PERSONAL. No physical writes or
provisioning. Read INSTALLER_PLAN_WALKTHROUGH.md and DR138. Existing concurrent
safety/dependency work is preserved and not bundled into this increment.
Stage jobs, PARTUUID mounts, storage mapping and full firstboot remain open.

## 2026-10-03 — main publication and isolated build (DR140)

GitHub BaseLineProx main is verified at af5fdd251c63b108c5655d554402ed025dcfb7d1.
The previously absent installer framework is integrated there, with explicit
external AppData mappings and scoped DR137 drive guards. New code/docs live
in the isolated worktree .runtime-proof138/main-integration (branch
local/main-installer-integration); this root checkout remains on its existing
branch with concurrent uncommitted changes preserved. Do not infer deployment
from main publication or overwrite this dirty checkout to align it.
3136 isolated tests passed. Updated manual ISO:
.runtime-proof140/installer/baseline-140.iso;497 extracted files matched and
actual isolated KVM boot reached the Proxmox menu. No physical writes. The real
six-volume drive still lacks ready AppData targets. Applying mounts, migrating
state, durable stage jobs and full firstboot remain open72/75/76. DR139 and
other concurrent production audit edits remain separate, not published here.
