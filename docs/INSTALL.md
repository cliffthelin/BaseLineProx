# Installing BaselineOS on real hardware

## Production operation audit — 2026-10-03 (DR139)

The notification broker now delivers through the real desktop session service;
acceptance was verified on this development desktop, **not on physical Proxmox
or in the cage kiosk**. Provisioning installs its client. The settings server
now calls existing live apply mechanisms and saves values only after successful
operations. Those settings/provisioning changes are tested against fakes and
local subprocess/HTTP boundaries only, **not applied to physical hardware**.

Unfinished operations cannot report success: logged rebuild requests, cache
checks without a verified source, firewall enforcement, tether configuration,
handoff restore and iperf3 service/test configuration explicitly fail. Network
configuration here supports hostname only; DHCP/link changes require a real
repair transaction. SSH restart failures and unavailable update categories
propagate failure. These runtime integrations remain open; changing their
reports to failure does not implement them. Missing required execution modules
fail import rather than install a fallback stub.

See [DR139](design/decision-records/139-production-real-operation-audit.md) and
the DR139 v0.2 queue entry. Installer stages, PARTUUID application and firstboot
remain open under rows72/75/76. Main remains unchanged; nothing was pushed.
Final validation: 3165 unit tests passed; deployment imports, provision shell
syntax and diff whitespace checks passed. Unit results are not physical proof.

This is the single, authoritative, step-by-step answer to "how do I
build a working Baseline drive install" - written 2026-09-26 because
no such document previously existed (an audit found the knowledge
scattered across `README.md`, `docs/SESSION_HANDOFF.md`,
`docs/BAREMETAL_BRINGUP_NOTES.md`, and ~15 decision records, none of
which are actually instructions). **Update this document, in place,
whenever a step below turns out to be wrong or incomplete - it is
meant to stay the single source of truth, not to be superseded by a
newer scattered narrative.**

## Status of each step, stated honestly

| Step | Code behind it | Current evidence and limits |
|---|---|---|
| 1. Acquire + verify the Proxmox installer | `drive_setup_acquire.py` | Live publisher download/signature chain, DR18. |
| 2. Prepare the unattended-install answer ISO | `drive_setup_answer.py` | Real disposable QEMU install and single-use HTTPS answer tests, DR60. Physical drive access exists; absence of `qm` on the development OS does not mean otherwise. |
| 3. Validate the target drives | `physical_device_safety.py` | Actual serial/device/size checks repeated 2026-10-01, DR117; physical source read-only during that proof. DR137's stricter boot-identity and serial-binding changes are verified against fakes only, not physical hardware. |
| 4. Install Proxmox | `drive_setup_install.py`, self-installer | A real installed Proxmox drive exists (v0.1 row17). Which historical installer run created it remains unconfirmed. No physical reinstall in DR117. |
| 5. Deploy the current Baseline app | `boot/provision.sh` | Imports, packaging and unit checks pass. DR117 copied current source into a disposable Proxmox clone and exercised its web/VM paths. **Full current provision.sh was not run end-to-end or deployed to the physical drive.** |
| 6. First boot / CONFIRM / kiosk | firstboot state machine, kiosk unit | Earlier QEMU firstboot tests, DR25–27. DR117 shows a visible Chromium Proxmox login on an actual Proxmox VM using a transient service with the corrected terminal properties; production firstboot ordering/autostart remains unverified. |
| 7. Mount named storage volumes | drive layout, persistence bind mounts | Existing physical drive has six plain GPT/ext4 volumes, not `baseline-persist` LVM-thin. They were unmounted during DR117; new VM integration uses separate directories inside a disposable clone, not physical volume isolation. |
| 8. Create Ubuntu or ordinary VMs | `proxmox_vm_host.py`, `ubuntu_environment.py`, `/vms` | Actual Proxmox `qm`/`pvesh`/`pvesm` registration, nested Ubuntu boot, OS/home split and OS rebuild proved in DR117. Standard VM allocation without backing proved; a standard ISO OS install has not been proved. |
| 9. Verify retained data | Ubuntu recipe + real guest agent | Document and actual Firefox profile survived a direct KVM desktop rebuild; document survived a clean Proxmox-managed Ubuntu server rebuild, DR117. Host power-cycle, physical deployment, active-VM backup/restore and other guest types remain open; DR118 adds clone-only LXC preservation evidence. |

**Current increments: [DR117](design/decision-records/117-real-ubuntu-proxmox-environment.md) and [DR118](design/decision-records/118-real-distro-linked-containers.md).**

Authenticated `/containers` now provides real native Proxmox linked LXC clones with
separate retained `/home`, `/root`, `/data`. Eleven distro families booted and
passed clean OS-rebuild/data checks in the disposable KVM Proxmox clone (DR118);
this is not physical deployment. openEuler 25.03 failed setup and is disabled.
These containers share the host kernel and have no preinstalled desktop/browser.
Bind data is **not covered by vzdump**. DR124 adds stopped retained-data backup and new-container restore, proved on Alpine in disposable Proxmox with separate virtual disks; physical off-drive proof and full VM recovery remain open.

The nine requested desktop/NAS/mobile systems are visible on `/vms` with official
sources and explicit uninstalled/unverified status. ISO UEFI selection and overlay
retained-disk size controls are implemented and unit-tested; the named systems
were not installed in DR118. Their retained disk needs actual guest filesystem/mount
setup before an OS reset is dependable. OMV NAS disk controls, GrapheneOS development
emulator integration and ChromeOS-specific deployment remain open (v0.2 row73).
Baseline manages the Proxmox substrate; it is not a replacement kernel.
Proxmox's kernel runs the host, Cage/Chromium provides its local GUI and
opens `https://localhost:8006`. Ubuntu Desktop has its own kernel, GDM and
Firefox; its homepage must be the host address reachable from that guest.
The bootstrap marker alone is not evidence that a GUI is visible.

The minimal Proxmox root preset is now **16 GiB**, superseding DR98's 5 GiB
root default. The actual clone filled its 5 GiB root during GUI installation;
the proof expanded only the clone's root to 24 GiB. The physical source was
not resized. Root expansion still requires genuine free VG capacity.

## The two known real drives (Track A)

**2026-09-30 event:** the Baseline drive (serial `MD89N41071210AP4E`) was repartitioned at the operator's instruction with `boot/prepare_scratch_drive.sh --apply`. It then held an `iso9660` image labelled `OMARCHY_202609` and no LVM or recognizable persistence layout; that was erased and replaced by a 200G/100G/176.9G GPT (`proxmox-rehearsal`, `luks-scratch`, `scratch-data`), which was in turn re-laid out the same day into Baseline's own volumes (`baseline_drive_layout.py`: BASELINE, INSTALLER_CACHE, SESSION_TEMP, SUBSTRATE, USER_ADMIN, USER_PERSONAL). The Proxmox drive (`FD01N6557110C271B`) was not touched.

| Serial (the identity) | Model | Kernel path on 2026-09-30 (re-verify, don't assume) | Role |
|---|---|---|---|
| `FD01N6557110C271B` | PC601 NVMe SK hynix 512GB | `/dev/sdc` (was `/dev/sdd` earlier the same month) | Proxmox substrate (steps 1-6); holds the `pve` volume group |
| `MD89N41071210AP4E` | PC401 NVMe SK hynix 512GB | `/dev/sdd` (was `/dev/sdb`) | The Baseline drive: plain GPT volumes laid out by `baseline_drive_layout.py` (see `docs/layers/00-baseline-drive.md`). Steps 7-9's LVM-thin pool design is superseded for it (decision records 46-47) |

Resolve a serial to its current device with
`readlink -f /dev/disk/by-id/ata-PC601_NVMe_SK_hynix_512GB_FD01N6557110C271B` (substrate) and
`readlink -f /dev/disk/by-id/ata-PC401_NVMe_SK_hynix_512GB_MD89N41071210AP4E` (Baseline drive).

`/dev/sdX` letters are **not** identity - re-resolve by serial every time (Step 3), never assume the same letter next boot.

**Hardware is expected to change with an install - the two rows above are an example from one point in time, not a permanent fact.** A drive gets replaced, a persistence disk gets upgraded, the substrate disk itself might not even be the same physical unit next time - adding or swapping a drive is a normal, supported operation, not an exception to work around. Re-derive the real serial at the time of each install (`lsblk -o NAME,SERIAL,SIZE,MODEL` or `udevadm info`); never carry a serial forward from this table without re-checking it against the drive actually in front of you. `baseline-prepare-real-install-iso`'s `--target-mac`/`--target-dmi-product` are optional for the same reason - see Step 2.

## Step 1 - Acquire and verify the Proxmox installer

```python
import drive_setup_acquire as dsa

runner = dsa.RealAcquireRunner()
result = dsa.acquire_and_verify(runner, workspace=Path("/root/baseline-install-workspace"), ...)
```

See `drive_setup_acquire.py`'s own module docstring and
`acquire_and_verify()`'s signature for the exact keyword arguments
(package name, workspace paths) - this step's GPG/hash verification
chain is real and already proven; this doc doesn't restate every
parameter to avoid drifting out of sync with the code's own docstring.

## Step 2 - Prepare the unattended-install answer ISO

**Two different modes, for two different purposes - do not mix them up:**

- **For a disposable QEMU test only** (proving the install mechanism
  works, never for real hardware): `--fetch-from iso` is fine here -
  the credential is synthetic, one-time, and the whole VM is deleted
  afterward. This is the accepted exception decision records 21/22/27
  already used successfully, and it sidesteps decision records 15-16's
  unresolved `guestfwd`-based-answer-fetch QEMU networking blocker
  entirely (that blocker is specific to `--fetch-from http` under
  QEMU's SLIRP; it does not apply to `iso` mode, and has still never
  been resolved - don't attempt `--fetch-from http` under QEMU, use
  `iso` mode for QEMU proofs instead).
- **For anything meant for real hardware**: always `--fetch-from
  http`, never `iso`. Decision record 02 demonstrated `--fetch-from
  iso` embeds the root password *hash* recoverably inside the prepared
  ISO file itself - `inspect-iso` reads it straight back out, and so
  does a bare `grep -a` with no tooling at all. `--fetch-from http`,
  via a Baseline-owned, single-use, TTL-bounded, hardware-fact-bound
  `EphemeralAnswerServer`, is the only accepted mode for a real
  install.

**Use the real tool, not hand-rolled snippets**:
`baseline/bin/baseline-prepare-real-install-iso` operationalizes this
whole step (decision record 60) - it builds the answer file (disk
targeted by serial via `filter.ID_SERIAL_SHORT`, never a device
letter), generates a fresh one-time credential, calls
`prepare_iso_defensively`, and can also start the matching
`EphemeralAnswerServer` in one invocation (`--serve`). It refuses to
guess your real target's MAC address or DMI product name - pass
`--target-mac`/`--target-dmi-product` yourself, obtained from the real
machine (`proxmox-auto-install-assistant system-info` from any live
media, or `dmidecode -s system-product-name` / `ip link`).

```bash
baseline/bin/baseline-prepare-real-install-iso \
  --source-iso <iso from step 1> \
  --assistant-binary /usr/bin/proxmox-auto-install-assistant \
  --output /root/baseline-real-install.iso \
  --workspace /root/baseline-install-workspace \
  --disk-serial FD01N6557110C271B \
  --server-host <a real LAN IP reachable from the target at boot - never 127.0.0.1, never QEMU's gateway> \
  --cert /root/answer-server.crt --key /root/answer-server.key \
  --target-mac <the real target's real NIC MAC> \
  --target-dmi-product <the real target's real DMI system product name> \
  --serve
```

Run `--serve` on a machine reachable from the real target's own local
network at boot, never exposed beyond that network - matching every
other network-facing surface in this project (`settings_web.py`'s
LAN-scoped, never-internet-exposed convention). It blocks until the
session is consumed or its TTL expires (default 30 min) - start it,
*then* boot the target from the USB stick.

## Step 3 - Validate the target drives

```python
import os

import physical_device_safety as pds

# `validate_target_device` refuses symlinks, so resolve the by-id link first; the serial check is the guard.
substrate_path = os.path.realpath("/dev/disk/by-id/ata-PC601_NVMe_SK_hynix_512GB_FD01N6557110C271B")
baseline_path = os.path.realpath("/dev/disk/by-id/ata-PC401_NVMe_SK_hynix_512GB_MD89N41071210AP4E")
substrate = pds.validate_target_device(
    substrate_path, expected_serial="FD01N6557110C271B",
    min_size_bytes=500_000_000_000, max_size_bytes=520_000_000_000,
)
baseline_drive = pds.validate_target_device(
    baseline_path, expected_serial="MD89N41071210AP4E",
    min_size_bytes=500_000_000_000, max_size_bytes=520_000_000_000,
)
```

Refuses (raises `PhysicalDeviceSafetyError`) on a symlink, a non-block
device, a serial mismatch, a size outside range, or - critically - if
the path resolves to **this machine's own current boot device**,
regardless of which path string was passed. Re-run this every time;
never cache or assume a prior result still holds.

## Step 4 - Write the ISO to real media and install (not yet run for real)

1. Prepare installation media only through a validated device operation:
   resolve the selected media by serial and pass the current target through
   `physical_device_safety.validate_target_device` before a write. The earlier
   unguarded `dd ... of=/dev/sdX` example is removed. Current Baseline drive
   installation belongs in the authenticated Drive Administration action,
   including its data-protection and human-confirmation gates.
2. Boot the target machine from that USB stick (UEFI boot menu).
3. The unattended installer runs, targeting whichever disk the answer
   file specified - **the answer file's own target-disk selection is
   the real safety boundary here, not anything in this repo's own
   code** (this repo's `physical_device_safety.py` validates a device
   *before* Baseline touches it for persistence/provisioning purposes;
   it does not run during Proxmox's own installer). Confirm the answer
   file specifies the exact serial `FD01N6557110C271B` (`/dev/sdc` on
   2026-09-30, but re-check by serial)
   before writing the USB stick, not just its expected disk letter.
4. Reboot into the freshly-installed Proxmox host.

**This step has never been run end-to-end for real using this
project's own tooling.** If it works as written, update the status
table above from "No" to "Yes" with the date and evidence. If it
doesn't, fix this section - don't let the fix live only in a decision
record.

## Step 5 - Deploy the Baseline app

On the freshly-booted Proxmox host, as root:

```bash
bash boot/provision.sh
```

Provisioning deploys the modules, desktop assets and gated services. It now
installs Cage, Chromium, xorriso and curl; the latter two are required for
Ubuntu acquisition and cloud-init seed generation. Full execution of the
current script on a fresh host is still open. Do not infer it from unit
checks or the narrower clone proof. Provider OAuth is an optional interactive
operator action; agents never handle an operator's real service credentials.

## Step 6 - Reboot; the first-boot CONFIRM gate

```bash
reboot
```

`baseline-firstboot.service` takes tty1 automatically. You'll see one
combined proposal screen (Proxmox detection, network diagnosis, the
five proposed diagnostic packages, a rollback description) that
**waits indefinitely with no default and no timeout**. Type the exact
string `CONFIRM` (case-sensitive) and press Enter - nothing else
authorizes anything. After that, network repair applies and is
independently re-verified, the five packages install and are
functionally verified, and only then does a durable completion marker
get written and control pass to Baseline's normal console. A second
reboot goes straight to that console, no re-prompt.

## Step 7 - Mount the existing named volumes

The current Baseline drive uses plain GPT/ext4 partitions: BASELINE,
INSTALLER_CACHE, SESSION_TEMP, SUBSTRATE, USER_ADMIN and USER_PERSONAL.
The former wipe-and-create `baseline-persist` thin-pool recipe is superseded;
following it would erase the current layout. Resolve the physical disk by
serial and inspect its current partitions before any storage action. Drive
changes belong in the authenticated Drive Administration workflow, including
its identity, data-protection and human-confirmation gates.

Mount the actual volumes at their named `/mnt/<LABEL>` paths before enabling
persistence-dependent services. A plain directory is not a mounted volume.
The VM engine refuses missing named mounts rather than quietly writing to the
host root. The bind-mount boot path on this physical layout still needs a
real deployment check; DR117 does not claim it works after a host reboot.

| Data | Default location | Rebuild behavior |
|---|---|---|
| Unchanged public Ubuntu download | `/mnt/INSTALLER_CACHE/images/` | Source bytes stay vanilla, SHA256 checked. |
| Prepared immutable templates, disposable OS overlay and VM runtime metadata | `/mnt/BASELINE/vm-runtime/` | Ubuntu OS overlay can be replaced while stopped. Templates must remain available to backing chains. |
| Ubuntu home disk, account hash/profile and Proxmox VMID/name records | `/mnt/USER_ADMIN/vm-data/` | Kept across an OS rebuild; never formatted by a rebuild seed. |
| Ordinary VM full writable disk | `/mnt/USER_ADMIN/vm-data/` | Protected state; no backing image or automatic OS reset. |

Independent absolute directories on other storage are also supported. On
Proxmox this increment registers directory stores `baseline-os` and
`baseline-user`; a conflicting existing definition is refused. Changing the
folders does not migrate existing VMs. Arbitrary LVM/ZFS destination adapters
and adoption of existing Proxmox VMs are not implemented in this library.

## Step 8 - Build Ubuntu from the authenticated web application

Open Baseline's `/vms` page (default app port 8100), log in as an admin and
set the disposable OS and protected disk folders. On Proxmox, Baseline uses
`qm`, `pvesh` and `pvesm`; direct QEMU is the development backend.

1. Prepare Ubuntu. This downloads the pinned Canonical 24.04 image, checks
   its pinned SHA256 and converts it into an immutable template. Publisher
   signature verification and an offline package mirror are later increments.
2. Choose Ubuntu Desktop or Server, name it, size the OS/home disks and set
   the Proxmox homepage to an address reachable **inside the VM**. A browser
   connected through localhost or an SSH tunnel does not establish a guest
   address. The form prefers the host vmbr0 IPv4 address and leaves an unknown
   loopback-only address empty; review it before creation.
3. Save the fresh, one-time `baseline-admin` login displayed after creation.
   Only its hash/profile is retained. There is no anonymous login, default
   cloud `ubuntu` account or desktop autologin. Start the VM and use the
   Proxmox console. Package installation needs network access and can take
   several minutes; “started” means the VM is running, not that setup finished.
4. Shut down cleanly before using Rebuild OS. It recreates the disposable OS,
   remounts the same `/home` and installs the recipe again. Only `/home` is
   retained: guest system-wide settings and packages on the OS disk are reset.
   A missing/damaged home disk is a recovery error, never permission to format.

The ordinary ISO path offers ISOs from existing enabled Proxmox ISO stores,
not just INSTALLER_CACHE. Other OS installations use a full protected disk;
the generic template/overlay controls are separate from Ubuntu's home recipe.
Docker/LXC runtime/data adapters and Harvester's ACL integration remain open.

## Step 9 - Verify the actual deployment

- Check `pvesm status`, actual `qm config <VMID>` disk references and sizes,
  guest `/home` mount, authenticated GUI and browser homepage.
- Save a document and real browser preference, shut down cleanly, rebuild the
  OS and verify both through the guest. Force stop can lose recently written
  data or damage a filesystem; DR117 observed this and repeated the test with
  fsync and a clean shutdown.
- Reboot the host and verify real named-volume mounts, bind redirects, VM
  records, firstboot ordering and GUI autostart. This physical check is open.
- Prove a quiesced backup and restore of the new split stores before relying
  on them. Existing backup claims based on `local-lvm` or cache placement do
  not establish recovery of `baseline-os`/`baseline-user` (v0.2 row60).

## Credentials

Agents never receive an operator's real account or service credentials.
Project-generated disposable credentials are fresh one-time values from
`drive_setup_answer.generate_one_time_password()`, hashed via stdin; never
put cleartext in logs, argv, environment or installer ISOs. For unattended
Proxmox deployment use the bounded HTTP answer server, never `--fetch-from iso`.
DR117 used a fresh test-only SSH key and rotated only the clone's root password
using the same factory. Current root-service web login validates the generated
SHA512crypt machine hash directly; the non-root desktop path uses the existing
sudo verifier. Other machine password hash schemes need a later adapter.

## If any step above turns out wrong

Fix this file directly, in place - do not just narrate the fix in a
decision record and leave this document stale. This file existing at
all only helps if it stays the thing people actually follow.


## Application isolation versus OS overlays (DR119)

Per-app AppData is planning only: no applied app overlay, app launch boundary,
update/reset or restore transaction has been verified. `/app-isolation` reports
plan checks, explicitly not runtime isolation. DR117/118 prove guest OS/data
rebuild mechanisms in disposable KVM; those do not isolate apps within guests,
and the proof host's qcow2 layer is not a production bare-metal root overlay.
Read `docs/design/application-layer-audit-2026-10-01.md`; implementation remains
v0.2 row74 with deployment/backup gaps in rows60/72/73.


## Software-owned workflows (DR120, 2026-10-02)

Baseline must perform normal operations without AI acting as its runtime.
`docs/design/functional-gap-audit-2026-10-02.md` identifies application coverage
and missing deterministic workflows. VM/LXC long operations and partial-state
recovery now have a first durable job increment (DR121; row75 remains partial);
app lifecycle74, guest/bind restore59/60
and distro installs73 remain open. Existing Operations scheduling works within
the web service without AI. This audit adds no runtime/hardware proof.


## Durable workload jobs (DR121, 2026-10-02)

VM/LXC actions return a saved job ID immediately. Use **Workload jobs** for actual
native stages, final outcomes and interrupted-job inspection. Repeated identical
request IDs reuse the job. Only one workload mutation runs at a time. Service
restart records interrupted work and never replays it. Inspect native state, then
type the exact name to acknowledge; acknowledgement releases the reservation and
**does not repair the workload or declare success**. After checking the native
state, explicitly submit any next operation. Failed jobs are reviewable but do
not hold the global reservation.

One-time logins are retrieved by authenticated POST and disappear after retrieval
or service restart. Running, ready managed containers support **Reset login**
without resetting OS or retained data. Managed Ubuntu/Proxmox login recovery is added in DR123 below; other guests/backends remain unsupported.
Existing drive/Operations jobs have not been migrated to this durable store.

2,874 guarded unit tests passed. Actual Alpine create/login rotation/rebuild and
service restart handling passed in disposable Proxmox-in-KVM, with a retained
/home document. The interrupted rebuild stopped during preflight, before
replacement: that DR121 run did not verify destructive-boundary recovery (DR122 below adds it);
power-loss recovery remains unverified. No
physical-drive write or production named-volume deployment was performed.
The development host's BASELINE, INSTALLER_CACHE, SESSION_TEMP, SUBSTRATE,
USER_ADMIN and USER_PERSONAL volumes were observed mounted; this observation
is not proof of runtime placement or isolation. See verification/121 and queue75.


## Recover a partially rebuilt container (DR122, 2026-10-02)

If a rebuild job is interrupted, open **Workload jobs**, inspect it, and acknowledge
with the exact container name. Acknowledgement releases the job reservation and
does not repair anything. Return to **Distro containers** and select **Recover
rebuild** if the inspected state supports it. Confirm explicitly. Baseline checks
the saved base, retained folders and current native ownership again before
recreating a missing OS or configuring its owned stopped partial clone in place.
The retained folders are kept. Use Reset login after readiness if needed.

Recovery refuses reused IDs, changed bases/mounts, running partial clones,
unknown native state and orphan volumes. Unsupported states remain explicit;
there is no blanket cleanup or automatic replay. Initial create/template failures
and interrupted detach before deletion still require further workflow software.

2,882 guarded unit tests and actual disposable Proxmox-in-KVM checks passed.
Service interruption after deletion and after linked cloning recovered through
the app with the retained document intact. The legitimate openSUSE base119 was
unchanged after a stale-reservation refusal. No physical writes or deployment;
host power-loss and in-flight native task interruption remain unverified.
See DR122 and verification/122; queue75 remains partial.


## Recover a managed Ubuntu VM login (DR123, 2026-10-02)

Start the Ubuntu environment, wait for its guest agent/recipe readiness, and use
**Reset login** on its VM card. Confirm replacement of the existing baseline-admin
password. Save the returned login once. OS and home stay intact; the retained
profile makes future clean OS rebuilds use the new hash. This supports managed
Ubuntu Desktop/Server on Proxmox, not arbitrary ISOs or local-QEMU guests.

A pending login rotation blocks OS rebuild. Once the guest is ready, confirm
Reset login again to replace the ambiguous credential with a fresh value. Lost
cleartext is never recovered from disk or shown by GET/status. Native identity,
readiness and synchronous guest command completion are checked before success.

2,892 guarded unit tests passed. Actual Ubuntu web login rotation and retained
hash/document continuity passed in disposable Proxmox-in-KVM. The post-rebuild
boot required restoring the earlier fixture's restricted-network apt proxy seed
settings and rerunning bootstrap on the same OS. Ordinary-network firstboot,
pending-rotation power loss and physical deployment remain unverified; see
DR123 and verification/123. This qualification leaves queue72 open.

## Stopped LXC retained-data backup and restore (DR124, 2026-10-02)

Cleanly shut down a ready managed container, select **Back up retained data**,
and supply a mounted separate local-disk folder. Open **Retained backup sets and
restore**, select the same folder and restore a set into a new unused name.
The original stays stopped and intact. Save the new container's one-time login.

Coverage is /home, /root and /data, including numeric owners, modes, safe links,
POSIX ACLs and user attributes. OS packages, /etc, native base and original login
hash are excluded. Same-host unchanged-base restore only. Backup writes are
add-only; unsupported metadata/nested mounts/special files are refused. Failed
restores retain an incomplete reservation for inspection, with repair still open.
Actual Alpine backup/boot/read/metadata checks passed in disposable KVM Proxmox
with a separate virtual backup disk. Physical off-drive recovery, full VM backup,
encryption/scheduling and app-level isolation remain unverified/open. See DR124
and verification/124; rows59/60/73/75 remain partial.

## Application-plan prerequisites (DR125, 2026-10-02)

Planner state paths now avoid separator/dash collisions, equivalent/nested
targets are reported as conflicts, and unsafe or oversized targets are refused.
Verified with pure unit tests only; no app sandbox, mounts, profile migration or
physical deployment was applied. Queue74 remains open for the real Chromium
lifecycle inside Ubuntu and its selected mounted AppData storage.

## Installer and portable recipe direction (DR126)

The substrate self-installer and VM lifecycle are already separate. The proposed
environment builder reuses them through durable jobs and a guest reconciler.
No portable OS/app recipe import/export or stack builder exists yet (row76).
Current retained-home rebuild does not preserve arbitrary /etc, package installs
or service databases. The target contract retains all declared flushed durable
state; only volatile state is expected lost after verified coverage and quiescence.
See design/installer-overlay-template-audit-2026-10-02.md. Source audit only;
no new runtime or hardware verification. Recipe-only export excludes user data
and secrets; fresh instantiate and private data restore remain separate actions.

## Initial portable recipe tool (DR127)

baseline-recipes validate RECIPE.json checks the narrow configuration-only
contract; compose OS.json APP.json emits a locked stack to stdout; verify STACK.json
checks recipes and their digests. It never installs, launches or applies overlays.
Initial support: Ubuntu24.04 amd64 and Chromium with allowlisted locale/symbolic
homepage configuration. State declarations are limited, not complete coverage.
No runtime profile/overlay capture or deployment exists. Source hashes are declared
locks, not fetched/trust-verified images. See verification/127 and queue76.

## Human recipe controls (DR128)

Open Environment recipes in the authenticated admin navigation. Load/paste JSON,
validate an individual recipe, compose OS plus optional application, or verify
a locked stack. Export is enabled after successful validation and invalidated
when inputs change. This performs configuration checks only; sources are not
verified, no VM is deployed and retention coverage is not complete. No input is
saved server-side. See verification/128; queue76 runtime builder remains open.

## Inspect an existing application (DR129)

In Environment recipes, enter a running managed Ubuntu/Proxmox VM and Debian
package name. Inspect installed application submits a durable job and reports
version, declared dependencies and configuration-file locations. Reconnect through
Workload jobs. No configuration contents/profiles/secrets are extracted; report
is not a deployable or test-installed recipe. Source/dependency locking, reviewed
settings export, container/media adapters and clean-target install/apply remain
queue76. Replacement-device restore is now explicitly row77, not implemented.

DR129 native verification: actual authenticated Bash metadata inspection in
managed Ubuntu inside disposable KVM Proxmox passed and report survived service
restart; guest confirmed stopped afterward. No config contents, recipe install/
apply, isolation or physical deployment proof. See verification/129 for helper
errors and evidence boundaries.

## VS Code settings preview and staging (DR130)

On Environment recipes, load/paste a selected VS Code settings.json and choose
Preview VS Code settings. Five approved portable editor settings are captured;
unknown values are excluded and counted. Export is a settings artifact, not an
installation recipe. baseline-vscode-settings capture INPUT previews; stage
ARTIFACT NEW_USER_DATA_DIR writes native settings only to a new directory.
Actual installed Linux VS Code read all five staged settings in a fresh profile.
No fresh binary install, VM rebuild, cross-OS/isolation or Spotify proof. See
verification/130 and design/application-examples-remaining-work.md.

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

## Native application workflow (DR133)

The `baseline-apps` / `application_bundle.py` workflow now downloads
and verifies exact publisher packages for VS Code, Spotify, Google Chrome,
native ChatGPT Linux preview and native Claude Desktop Linux beta. All five
have rendered actual windows in Ubuntu24.04.5 inside the disposable Proxmox
clone and in a separate Debian13.7 KVM VM. Spotify required a private D-Bus
session; earlier black-window captures are failed evidence, not readiness.
The profile-switch and crash-recovery homepage fixes were checked on both guests;
Chrome reaches the actual Proxmox endpoint but stops at its untrusted-certificate
screen. Human certificate acceptance/login remains open.
No operator account was authenticated and no physical drive was written.

Stopped, unauthenticated Ubuntu private profiles were backed up, restored into
new private targets and matched by file contents before fresh payload installs.
Debian13.7 now completed a real disposable-KVM OS-root replacement and
reinstalled all five locked native packages through the suite CLI. Before
launching applications, all five private identities and30,827 retained regular
files matched their stopped pre-rebuild inventory exactly. This is not proof
of account login/playback/chat, encrypted recovery or physical deployment.
All five rendered native windows after the rebuild. GDM is active and generated
application menu entries exist; interactive human login/Wayland remain unverified. Native extraction/apply covers five VS Code settings and Chrome's
homepage; Spotify/ChatGPT/Claude exports currently contain Baseline launch
options only. Full native preferences are retained privately, never exported as
a sharing recipe. The optional login-browser grant shares only Chrome code;
its browser profile belongs to the requesting app. Actual Debian dispatch opened
the public ChatGPT website and Claude native action; cross-app/file URIs refused.
This is not authenticated OAuth proof.

The disposable clone's root was expanded from24 to48GiB and Ubuntu VM100's
root from12 to24GiB for old/new-generation testing. The physical Proxmox drive
was not resized. A `/tmp` user-quota I/O failure required stopping the clone,
moving its COW overlay to disk-backed workspace storage and restarting it.
These are test capacity events, not physical-drive fixes. Debian's publisher
cloud image required UEFI; retained home is addressed by its virtio serial,
not `/dev/vdX`. Rows74/76 and installer/physical row72 remain open. No new
physical deployment occurred. See [DR133](design/decision-records/133-native-five-apps-and-retained-debian-rebuild.md)
and [verification/133](verification/133/README.md). Installer/ISO application
staging, storage-class routing and the complete user walkthrough remain open.

## Reusable application tasks and installer guidance (DR134)

baseline-tasker now emits typed, registered Ansible playbooks with editable
cache/generation/private-data paths. Real roles install prerequisites and build
or inspect native suites; successful target-source-verified observations are
separate from expected compatibility. Actual disposable Debian13 runs cover all
five apps; Ubuntu24.04 tasker runs cover Chrome. Both repeated with changed=0.
All-five GUI evidence remains DR133, not a tasker readiness claim. 2993 unit
tests pass; no physical deployment is verified. provision.sh/ISO staging now
includes app/tasker code, automation and docs, but full current provisioning
remains open. See [walkthrough](BASELINE_BUILD_WALKTHROUGH.md),
[contract](design/tasker-recipe-contract.md) and
[DR134](design/decision-records/134-reusable-ansible-tasker-and-installer-guidance.md).
The autofill is an application recipe, not complete hardware volume setup.

A DR134 manual Proxmox9.2 installer ISO now carries the updated source, roles
and walkthrough. Real isolated KVM boot reaches the Proxmox menu; extracted
critical file hashes match staged source. It contains no unattended answer or
password hash and does not automatically provision Baseline. This verifies
packaging/boot only, not installation or physical readiness.

## Drive enrollment and the install plan (DR135)

Baseline's initial action gate admits the SK hynix drives, plus any drive a person
deliberately enrolls with the `enroll_drive` Drive Administration action. That
action takes the drive's serial typed exactly, must match what the drive
reports, and needs a human confirmation every time. It writes nothing to the
drive. `baseline/bin/baseline-install-plan discover | autofill | validate PLAN |
compile PLAN` reads one `lsblk` listing. It autofills an editable JSON plan
(drives by serial, Baseline volumes by PARTUUID, Ubuntu 24.04 desktop, five
apps), checks every edit against fresh discovery, and prints the parameters
the existing stages take. It runs none of them. Retained volumes compile to
`PARTUUID=` mounts, because `LABEL=` is ambiguous once two drives carry
Baseline's labels.
Unit-tested against fakes only: real-drive discovery was not run (the
development sandbox returns no `lsblk` output), and nothing has been enrolled
or provisioned with it. Running the stages as one job, applying the mounts and
a web editor remain open under rows 72/75/76.

**2026-10-03 remediation: all five DR136 findings are fixed against fakes
only, not verified on physical hardware** ([DR137](design/decision-records/137-main-readiness-review-fixes.md)).
Layout retains the confirmed serial through dispatch and revalidates identity,
path and size before each destructive command, then serial before stamping.
The device gate refuses unknown boot identity; install-plan discovery also
refuses it. This includes unsupported live/overlay or ambiguous root topology:
it must be resolved before enrollment or planning, rather than bypassed.
Autofill leaves ambiguous choices unset; even two empty disks require explicit
role choices. Retention requires valid GPT PARTUUIDs and distinct volume names.
PARTUUID uniqueness is checked across all partitions in the existing read-only
listing, including boot, unenrolled and unidentified disks. Repeated sightings
of the same named partition count once; GUID comparison ignores letter case.
No extra per-device probes or writes are added to discovery.
The inherited backup tests now use fake destination capacity; the production
free-space gate is unchanged. DR136 remains the historical review. Rows
55/65/67's reviewed guarantees are restored in guarded tests; physical proof
and the existing rows 72/75/76 integration work remain open. No merge or push
was performed.

## Installer plan web editor and physical discovery (DR138)

Authenticated /install-plan now discovers/autofills, edits JSON choices,
validates against fresh hardware and previews/exports stage parameters. No
stages execute. Actual headless-Chromium/loopback HTTP tests use synthetic
listings; separate native read-only physical discovery found both SK hynix
drives and selected keep/retain. The existing six-volume drive lacks required
APPDATA_ADMIN/APPDATA_PERSONAL, so compilation refuses. No drives were changed.
This supersedes the earlier current-status note that physical discovery could
not run; DR135's failed sandbox attempt remains historical. The current ISO
still predates this editor. Full stage execution, PARTUUID mount application
and provisioning/firstboot remain open under72/75/76. See
[editor walkthrough](INSTALLER_PLAN_WALKTHROUGH.md) and
[DR138](design/decision-records/138-authenticated-installer-plan-editor.md).
