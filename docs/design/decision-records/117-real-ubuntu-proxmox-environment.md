# 117 — Ubuntu environments and the Proxmox VM library, exercised for real

Date: 2026-10-01 America/Denver (evidence also contains 2026-10-02 UTC).
Status: implemented increment, guarded unit tests and actual QEMU/KVM +
Proxmox-clone integration verified. **Not deployed or boot-verified bare metal.**
Supersedes DR98's 5 GiB minimal Proxmox root default only. Earlier decision
records remain history. Current INSTALL and layer/queue docs corrected in place.

## Scope and operator decisions

Baseline is a tool on the Proxmox substrate. Its host kernel is Proxmox's
kernel; Cage and Chromium provide the local GUI with the actual Proxmox URL.
It could later use Harvester, after a real ACL/lifecycle adapter exists. This
increment does not implement a fake Harvester adapter.

Start with Ubuntu; no guest/anonymous users. Create one fresh authenticated
baseline-admin account and display its one-time login once. Rebuilding the
OS keeps its separate home disk and the same account hash. Ordinary VM disks
also work without overlays. The operator clarified that INSTALLER_CACHE is
an unchanged starting/rebuild source, not the ceiling of supported storage,
source images or workload types. Standard VMs and Docker must eventually
work independently of overlays; Docker/LXC work is still open here.

The operator approved the disposable Proxmox clone, loopback-only access,
fresh synthetic SSH key and, explicitly, copying baseline/lib, baseline/bin
and the public pinned Ubuntu image into that clone. Earlier automatic review
rejections were reported and not circumvented. Both physical SK hynix drives
were broadly authorized, but neither was modified in this increment.

## Storage and lifecycle implemented

- Vanilla pinned Canonical Ubuntu source remains in the selected installer
  cache. Its SHA256 is checked before conversion; publisher signature
  verification and an offline package mirror remain unimplemented.
- Prepared immutable base and resettable Ubuntu OS overlay use the disposable
  OS store, default /mnt/BASELINE/vm-runtime. A retained home.qcow2 and
  hash-only recipe/account profile use protected storage, default
  /mnt/USER_ADMIN/vm-data. No formatting command is present in a rebuild seed.
- Ordinary VM full writable disks also use protected storage, with no backing
  file. A selected ISO need not come from this Baseline drive; enabled Proxmox
  ISO stores are enumerated. Independent external directory paths are supported.
- The Proxmox adapter registers baseline-os/baseline-user directory stores,
  keeps name/VMID records in protected storage and uses qm/pvesh/pvesm. It
  does not launch a competing unmanaged QEMU process. A conflicting existing
  storage definition is refused. Resizing a disk refreshes Proxmox's disk
  inventory. Ubuntu uses OVMF, a serial-identified home disk and guest agent.
- Named /mnt volumes must actually be mounted. OS/protected paths cannot be
  nested or placed under INSTALLER_CACHE. Existing home state is not replaced
  by a new allocation; retained-data Proxmox VM retirement is explicitly
  refused until a safe retirement workflow exists.
- The web page has Desktop/Server recipes, ISO/template controls, rebuild,
  lifecycle and independent storage settings. The homepage prefers the real
  vmbr0 IPv4 address, independent of the browser's localhost SSH tunnel.
  Unknown addresses require operator input. Creation returns a fresh login
  once, never a URL/query-string credential. Existing login/origin gates remain.

## Real proof — direct KVM Ubuntu desktop

Public Canonical source:
https://cloud-images.ubuntu.com/releases/noble/release-20260926/ubuntu-24.04-server-cloudimg-amd64.img

SHA256: 6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2

Actual qemu-img conversion, UEFI boot, cloud-init, package installation,
GDM login and Firefox ran using production recipe code. The test fixture
provided a restricted package proxy and a fresh test-only SSH key, not an
operator credential. Ubuntu reported kernel 6.8.0-142-generic, a distinct
ext4 /home and UID1000 baseline-admin. Firefox snap 157.0-1 was actually
running; its homepage policy was inspected in the visible desktop.

A document and an actual Firefox profile user.js preference survived a
completed production OS rebuild and clean shutdown. A final read-only
inspection of the stopped home.qcow2 confirmed both. This proves retained
home behavior, not retention of packages or system-wide settings on the
resettable OS disk. The direct fixture's configured homepage endpoint was
absent; the Firefox screenshot proves the policy, not loading Proxmox there.

## Real proof — approved Proxmox clone

The actual PC601 source serial FD01N6557110C271B was resolved and validated
through physical_device_safety before access. QEMU opened its raw backing
source read-only; every proof write went to /tmp/baseline-proxmox-live-proof/
source-overlay.qcow2. The other serial MD89N41071210AP4E was not changed.
The clone ran actual Proxmox 9.2.2, kernel 7.0.2-6-pve and nested KVM.

SSH 127.0.0.1:22230, Proxmox 127.0.0.1:18006 and Baseline
127.0.0.1:18100 were loopback-forwarded, with QEMU restrict=on and one named
package-proxy exception. Source copied to /opt/baseline, public Ubuntu image
to /var/lib/baseline-proof/cache. No operator credential was entered/copied
as part of that transfer. Only the clone's root credential was rotated using
the project's fresh one-time password/hash helpers via stdin.

- Actual qm/pvesh/pvesm created directory stores and VM100 Ubuntu Server.
  Its 12 GiB OS overlay is on baseline-os; 4 GiB home on baseline-user;
  EFI and guest agent were real. Ubuntu boot and its console were observed.
- Production rebuild kept VMID100 and the same home disk. After fsync/sync
  and clean qm shutdown, the rebuilt guest confirmed the separate home mount
  and proxmox-retained-document. From inside that nested Ubuntu, HTTPS to
  https://10.0.2.15:8006 returned HTTP200 with the actual Proxmox page.
- VM101 standard-proof allocated a full 12 GiB qcow2 on protected storage.
  Actual qemu-img info reports no backing image. It has no installed OS;
  this is an allocation proof, not an ISO installation proof.
- The real Baseline web service refused anonymous access (login redirect)
  and a wrong synthetic root password (HTTP401), accepted its fresh correct
  password and rendered the actual Proxmox library. Authenticated same-origin
  storage configuration worked. A web create action allocated empty VM102
  web-allocation-proof on protected storage; a confirmed web delete removed
  that disposable empty VM. No existing home data was removed.
- Cage/Chromium on the clone console visibly rendered the real Proxmox login
  at https://localhost:8006. The proof used a transient service with the fixed
  seat/TTY/runtime properties; it did not assert production firstboot marker
  completion or prove the shipped service's gated autostart.

These stores are separate directories **inside the clone's root filesystem**,
not the physical Baseline volume layout. A VM backed by a real source drive
is still a QEMU proof, not bare-metal GUI/boot verification.

## Failures found and corrected

1. Direct QEMU rejected serial= on -drive. Use a separate virtio-blk-pci
   device with serial=baseline-home. The cloud image's BIOS boot failed;
   configure OVMF and a per-machine writable variable store instead.
2. Initial service-active/boot-ready markers did not show a visible desktop.
   GDM's Wayland startup crashed in the test and then fell back to working
   X11. Actual greeter/login/Firefox screenshots, not just markers, were used.
3. The old 5 GiB Proxmox root filled during Cage/Chromium installation.
   Only the clone was expanded to 24 GiB; new-install minimal preset is now
   16 GiB. It leaves free VG capacity rather than silently assuming growth.
4. Cage was blocked acquiring its VT. Explicit tty-force, builtin seat
   backend and a private systemd RuntimeDirectory produced a visible GUI.
5. Root-service web login attempted sudo on a host without it, disconnecting
   the request; sudo as root would not verify a login password anyway.
   Reuse the existing SystemPasswordVerifier for root services and existing
   SudoPasswordVerifier for a non-root desktop service. The current direct
   verifier supports the project's generated SHA512crypt hashes; other hash
   schemes are not claimed as supported.
6. qemu-img resize changed the actual OS disk but left qm config at 3.5 GiB;
   qm disk rescan now updates it to the real 12 GiB value.
7. First Proxmox persistence test force-stopped immediately after a write.
   The file's size/metadata persisted but its content was NUL bytes. The test
   was corrected to fsync/sync and a clean shutdown, then passed. This is not
   a claim of power-loss durability; Force stop now states recent writes and
   filesystems are at risk.
8. Provisioning omitted the new Ubuntu/Proxmox imports and xorriso/curl;
   installer staging omitted desktop packaging. Tests and staging now cover
   them. Full provision.sh execution is still not proved by these checks.
9. An existing path traversal test assumed a fixed /tmp directory depth.
   A deeper workspace test directory did not resolve to /etc at all. Compute
   the actual depth and assert the resolved target is /etc/out.json before
   checking refusal. No assertion was weakened or skipped.

## Verification and evidence

TDD: meaningful failing tests were run before production fixes. Unit VM
runners are fakes; they are distinct from the actual running-VM proofs above.
Full guarded unit suite: **2839 passed**,
python3 -m pytest -q tests/unit --basetemp .test-work-117.
Loopback HTTP tests required execution outside the socket sandbox; the
suite's hardware safety guard stayed active. The workspace temp directory
provided enough free space for existing 44 GiB backup sizing tests.

python3 tools/check_provision_deploys_all_imports.py: OK.
bash -n boot/provision.sh: OK. git diff --check: clean.

[Curated evidence](../../verification/117/README.md) includes actual PNGs,
version/config/guest-agent JSON, retained-home inspection and HTTP results.
No passwords, password hashes, SSH keys or seed contents are included.
Implementation SHA256 fingerprints are included to identify the code tested.

## Open work and corrected current documents

v0.2 row72 remains **[~]**. Still open: full current provisioning on a fresh
host; real named-volume mounts and control-plane bind redirects; physical
host reboot and firstboot-gated kiosk autostart; standard ISO OS installation;
Docker/LXC data/lifecycle adapters; Harvester ACL/lifecycle integration;
publisher signature verification/offline package sources; existing VM
adoption, generalized Proxmox storage adapters and safe retained retirement.

An Ubuntu OS rebuild is proved; rebuilding the whole BASELINE/substrate
volume is not. vm.json/runtime metadata and prepared backing images still
need recovery from a retained manifest/backup if that volume is lost.
Default VM storage is USER_ADMIN, not automatic active-persona migration.
Partial allocation failure recovery also needs a dedicated workflow.

v0.2 row60's local-lvm-only backup implementation does not prove a quiesced
backup/restore of baseline-os/baseline-user. Row60 is reopened for this new
coverage; full physical backup verification also remains open. Copying active
qcow2 files during a volume archive is not such a proof.

INSTALL.md corrected its unsupported no-physical-access assertion, stale
full-provision claim, current root sizing and superseded destructive thin-pool
instructions. Current layers corrected the stale VM-in-cache assumption and
backup implication; the dated 2026-09-30 handoff has a later clarification.
DR98 and other earlier decision records remain append-only history. New
proof is linked from SESSION_HANDOFF and the change-log index.
