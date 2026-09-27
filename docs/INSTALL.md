# Installing BaselineOS on real hardware

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

| Step | Code behind it | Verified against real hardware? |
|---|---|---|
| 1. Acquire + verify the Proxmox installer | `drive_setup_acquire.py` | Yes - live, against the real `download.proxmox.com` (decision record 18) |
| 2. Prepare the unattended-install answer ISO | `drive_setup_answer.py` | Yes, under QEMU (decision record 19). Not yet re-verified with `--fetch-from iso` specifically, recommended below for a real bare-metal boot - see "Open question" |
| 3. Validate the two target drives | `physical_device_safety.py` | Yes - real, live, on the actual two drives (serials below) |
| 4. Install Proxmox onto the validated drive | `drive_setup_install.py`'s invocation builders, reused per this doc's own instructions below | **No** - every prior install this code has performed was a QEMU sparse file. The one real install (Dell Latitude 5290) used none of this code and left no reproducible record. This doc's Step 4 is the first time this exact procedure is written down; it has not been run end-to-end for real yet |
| 5. Deploy the Baseline app (`provision.sh`) | `boot/provision.sh` | Yes - real, per Track A1 |
| 6. First boot / CONFIRM gate | `firstboot_statemachine.py` | Yes, under QEMU (decision records 25-27); SESSION_HANDOFF.md claims Track A1 also proved this live, but no decision record documents that specific real-boot verification |
| 7. Build the persistence pool on the second drive | `persistence_pool.py` (**new**, written 2026-09-26) | **No** - Track A2 did this once, for real, via ad hoc commands with nothing reusable left behind. This module is a reconstruction of the intended procedure, not a recovery of what was actually typed. Review before trusting it |
| 8. Attach persistence to a VM | `vm_provision.py` | No - unit-tested against fakes only |
| 9. Verify persistence survives a reboot | N/A | Proven for network config + installed packages only (Gates D/F, under QEMU) - not for the persistence pool itself, on any hardware |

**Read this table before following the steps below.** Steps 1, 3, and 5 you can trust as written. Steps 2, 4, 6, 7, 8, and 9 are either unverified on real hardware or genuinely new - follow them, but expect to find and fix a real mistake, and **update this document when you do.**

## The two known real drives (Track A)

| Path (at last check - re-verify, don't assume) | Model | Serial | Role |
|---|---|---|---|
| `/dev/sdd` | PC601 NVMe SK hynix 512GB | `FD01N6557110C271B` | Proxmox substrate (steps 1-6) |
| `/dev/sdb` | PC401 NVMe SK hynix 512GB | `MD89N41071210AP4E` | Persistence backend (steps 7-9) |

`/dev/sdX` letters are **not** identity - re-resolve by serial every time (Step 3), never assume the same letter next boot.

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

**Corrected 2026-09-26 - the first version of this step recommended
`--fetch-from iso` for simplicity. That was wrong and has been
removed.** Decision record 02 already investigated this directly and
found, by demonstration (not theory), that `--fetch-from iso` embeds
the root password *hash* recoverably inside the prepared ISO file
itself - `inspect-iso` reads it straight back out, and so does a bare
`grep -a` against the raw ISO with no tooling at all. Anyone who ever
obtains that ISO has the hash. This is exactly why this project's own
accepted design is `--fetch-from http`, via a Baseline-owned,
single-use, TTL-bounded, hardware-fact-bound `EphemeralAnswerServer` -
never the embedded-ISO mode, for a real install any more than a QEMU
one.

```python
import drive_setup_answer as dsan

outcome = dsan.prepare_iso_defensively(
    runner, binary=Path("/usr/bin/proxmox-auto-install-assistant"),
    source_iso=<iso from step 1>, answer_file=<your answer.toml>,
    fetch_from="http",
    output_path=Path("/root/baseline-real-install.iso"),
    tmp_dir=Path("/root/baseline-install-tmp"),
    workspace_root=Path("/root/baseline-install-workspace"),
    expected_fetch_mode="http", min_size=..., max_size=...,
    forbidden_iso_strings=[...],
)
```

Then run `dsan.EphemeralAnswerServer` on a machine reachable from the
real target's own local network at boot (not QEMU's SLIRP gateway -
a real LAN IP) and never exposed beyond that network: single-use,
TTL-bounded, and bound to the installing machine's own hardware facts,
matching every other network-facing surface in this project
(`settings_web.py`'s LAN-scoped, never-internet-exposed convention).
**Known open risk, not yet resolved**: decision records 15-16 found
this exact `guestfwd`-based answer-fetch path failing under QEMU with
a root cause never identified ("blocks building any new disposable
Proxmox install... via the established guestfwd/ephemeral-answer-server
methodology"). A real bare-metal boot reaches the answer server over a
real NIC, not `guestfwd`, so this specific failure mode may not apply -
but it hasn't been re-tested on real hardware either. Watch for it.

## Step 3 - Validate the target drives

```python
import physical_device_safety as pds

sdd = pds.validate_target_device(
    "/dev/sdd", expected_serial="FD01N6557110C271B",
    min_size_bytes=500_000_000_000, max_size_bytes=520_000_000_000,
)
sdb = pds.validate_target_device(
    "/dev/sdb", expected_serial="MD89N41071210AP4E",
    min_size_bytes=500_000_000_000, max_size_bytes=520_000_000_000,
)
```

Refuses (raises `PhysicalDeviceSafetyError`) on a symlink, a non-block
device, a serial mismatch, a size outside range, or - critically - if
the path resolves to **this machine's own current boot device**,
regardless of which path string was passed. Re-run this every time;
never cache or assume a prior result still holds.

## Step 4 - Write the ISO to real media and install (not yet run for real)

1. Write the prepared ISO from Step 2 to a real USB stick:
   `dd if=/root/baseline-real-install.iso of=/dev/sdX bs=4M status=progress oflag=sync`
   (`/dev/sdX` here is the **USB stick**, not either target drive from
   the table above - triple-check this before running `dd`, which is
   silently destructive to whatever device you point it at).
2. Boot the target machine from that USB stick (UEFI boot menu).
3. The unattended installer runs, targeting whichever disk the answer
   file specified - **the answer file's own target-disk selection is
   the real safety boundary here, not anything in this repo's own
   code** (this repo's `physical_device_safety.py` validates a device
   *before* Baseline touches it for persistence/provisioning purposes;
   it does not run during Proxmox's own installer). Confirm the answer
   file specifies the exact serial `FD01N6557110C271B` (`/dev/sdd`)
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

Real, tested, reviewed - see `boot/provision.sh`'s own inline comments
for exactly what it does (disables enterprise repos, installs
packages, deploys `/opt/baseline`, stages and enables six systemd
units, never touches this session's own tty). Then, separately and
interactively:

```bash
baseline-auth-setup.sh
```

(needs a real login to complete Claude OAuth - cannot be scripted
further than this).

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

## Step 7 - Build the persistence pool on the second drive (new, unverified)

```python
import persistence_pool as pp
import physical_device_safety as pds
from repair import RealRunner

runner = RealRunner()
validated = pds.validate_target_device(
    "/dev/sdb", expected_serial="MD89N41071210AP4E",
    min_size_bytes=500_000_000_000, max_size_bytes=520_000_000_000,
)

# If a stale VG from a prior install shares a name with anything
# currently active elsewhere (Track A2 hit exactly this with a
# duplicate "pve" VG) - deactivate it by exact UUID first, never by
# name alone. Skip this call if `vgs` shows nothing stale.
pp.deactivate_stale_vgs(runner, name="pve", keep_uuid="<the OTHER drive's real pve VG UUID - check `vgs` yourself first>")

pds.wipe_signatures(validated)
result = pp.create_thin_pool(runner, validated)
assert result.ok, result.detail
result = pp.register_with_proxmox(runner)
assert result.ok, result.detail
```

**This is a reconstruction, not a recovery of what Track A2 actually
typed - review every command against your own `vgs`/`pvs` output
before running it.** `pp.deactivate_stale_vgs`/`create_thin_pool` are
destructive; there is no dry-run mode. Confirm with `pvesm status`
that `baseline-persist` shows up afterward.

## Step 8 - Attach persistence to a VM

```python
import vm_provision as vp
from repair import RealRunner

runner = RealRunner()
vp.attach_persistence_disk(runner, <vmid>, size_gb=<N>)
```

## Step 9 - Verify

- `pvesm status` shows `baseline-persist` active.
- Create a test volume, write to it, reboot the host, confirm the
  data is still there and `pvesm status` still shows the pool active
  without manual re-intervention.
- Update the status table at the top of this document with what you
  actually found - pass or fail, with the date.

## If any step above turns out wrong

Fix this file directly, in place - do not just narrate the fix in a
decision record and leave this document stale. This file existing at
all only helps if it stays the thing people actually follow.
