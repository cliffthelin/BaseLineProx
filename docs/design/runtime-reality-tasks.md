# Runtime reality audit and repair tasks

2026-10-04. Active repair backlog requested by the operator. DR142 records this
increment. Existing queue rows remain the governing feature scope. This first
pass searched production libraries, Python entry points and boot scripts for
fake/mock/demo/simulation/stub/placeholder wording, constant success, and
failure-to-empty/default fallbacks, then traced the findings below through
their callers. It is not an exhaustive semantic proof of every branch.

An unavailable operation is an error. A saved plan, started process, generated
unit, catalogue entry or passed test is not runtime completion. A confirmed
empty result remains valid; an unsuccessful observation is unknown. Intentional
no-ops must describe exactly what they did. Test doubles stay in tests and their
results must be reported as synthetic verification.

DR180 corrects one such false empty result: `backup_restore.list_backup_contents`
now raises `BackupReadError` when `tar -tzf` fails. The CLI exits nonzero and the
web route returns a refused response with the read error. Focused regression
coverage passed against `FakeRunner`; no real backup archive or disk was read.

DR182 fixes OverlayFS argv generation for per-user data paths. `mount` receives
the persona's resolved home path instead of a literal `~`; unsafe or missing
home paths are rejected. This repairs plan-command correctness, not runtime
mounting or application confinement.

DR183 removes another false empty hardware/storage result: LVM command failures
and missing stdout raise an inventory error; Drive Administration renders the
error. Volume usage first reads the actual `findmnt` JSON tree, skips targets
that are genuinely unmounted, and surfaces `df` failures on confirmed mounts.
The restricted host returned an explicit no-new-privileges LVM error and zero
mounted Baseline volumes; no LVM elevation or disk write was attempted.

DR184 rejects malformed and duplicate rows from successful LVM inventory
commands. `ensure_volume` returns failure before `lvcreate` or `mkfs` when its
existing-volume inventory cannot be parsed; the volume-size parser likewise
raises instead of silently dropping rows. Focused synthetic-runner tests passed;
no physical drive was modified or verified.

DR185 fixes Installer Cache inventory. Scan failures no longer become empty
subdirectories or partial file lists; malformed rows and non-file entries are
rejected. `reconcile()` refuses to scan the root-filesystem fallback when the
intended cache volume is not mounted. The page reports unknown contents instead
of marking files present/missing. A
read-only host observation found `/mnt/INSTALLER_CACHE` is not mounted; files
previously observed in that fallback path were left untouched.

DR186 removes further Installer Cache catalog fallbacks. Diagnostic packages,
curated VM scripts and their declared source origin must come from their owning
modules; failure to import them is propagated to the cache page as an inventory
error, never replaced with a partial static list or generic origin. Current host
catalog generation succeeded; tests cover unavailable source modules with
synthetic import failures.

DR187 removes failure-to-empty behavior from Drive Administration. `lsblk`,
partition-tree, `pvs`, and Baseline `lvs` failures or malformed rows now raise a
drive-inventory error; the page distinguishes that from a successful empty
candidate list. Repair/mount/unmount actions refuse with the probe error when
VG identity is unavailable. The initial read-only development-host attempt
could not establish the boot-drive serial because its root block node was not
present in this namespace; DR188 adds a sysfs-backed identity path.

DR188 applies the same unknown-is-not-safe rule to off-drive backups. A backup
destination is refused unless the running boot-drive serial is known, so a
failed identity probe cannot be interpreted as evidence that the destination is
separate. When `/dev` omits the mounted root node, the fallback resolves its
major:minor through sysfs and asks udev for the parent disk serial. A read-only
host probe resolved `<boot drive serial>`; 134 focused tests passed against
synthetic runners. No physical backup was made. REAL-005 retains the remaining
ancestry and complete storage-graph work.

DR200 adds a read-only check for the labeled, mounted ext4 AppData volume and
DR203 shows its live result on `/app-isolation`; mismatch is an error, with no
mount or write performed.
DR212 keeps provider credential-file failures and uncertain Ollama socket
probes as Unknown, distinguishes TCP refusal from Unknown, and removes the
unverified claim that a configured Claude token was live-checked. Focused tests
used injected state only; no credentials or live provider services were read.
DR213 wires the bridge-member probe's I/O error into the dashboard as Unknown
instead of swallowing it. Focused AST and injected-observation tests passed;
interactive rendering and live bridge state remain unverified under REAL-007.
DR215 distinguishes a missing audit file from a read failure; Audit and
Operations now show unavailable history on errors instead of empty history.
Injected read-failure and local HTTP tests passed; no host audit log was read.
DR189 removes an AppData catalog fallback: a newly added package or container
without a declared data-target/bind policy can no longer appear stateless just
because its key is missing. Only an explicit empty policy means no persistent
data. The current catalog passes planner tests, and a synthetic unknown-package
regression verifies the visible failure. This does not apply overlays or prove
runtime confinement; queue74/REAL-008 remains open.

DR193 fixes the first-run handoff wizard's suppressed plaintext staging cleanup
failure. Restore cleanup is strict and setup cannot report success when
decrypted credentials may remain. The regression uses a fake packet reader and
temporary filesystem only; no packet or credential was read. Transactional
rollback for partial packet application remains open. DR194 makes hostname
application report live/persistent write failures and roll back the old value
when persistence fails; tests use synthetic socket and filesystem behavior.
DR195 makes packet application file-transactional: prior target files and
directory metadata are restored and new files removed if a later write fails.
Rollback errors identify affected paths. This is synthetic-only; no live-host
restore has been attempted.

DR196 removes false success from the Operations test-restore flow: its exit
code is nonzero unless the extracted sample is nonempty and the temporary
directory is confirmed removed. Cleanup failures include the residue path.
Synthetic archive/filesystem tests only; no real backup was read.

## First repair sequence

Finish the runtime observation tasks first (REAL-001/002/006), then service
selective restore (REAL-004). Keep optional diagnostic follow-ups (REAL-003)
separate from readiness gates. Validate the shipped installer
and its durable jobs (REAL-009), then implement the first application isolation
slice (REAL-008). Keep existing real VM/LXC, networking, backup and enrollment
mechanisms; extend them instead of replacing them with generic refusals.

## Task register

| ID / priority | Finding and present behavior | Required repair and acceptance | Existing queue |
|---|---|---|---|
| REAL-001 / P1 | `proxmox_vm_metrics.py` returned `[]` on missing/failed pvesh or invalid JSON and filled missing metrics with zero. Now raises `MetricsError`, preserves unknown measurements as `None`, and the TUI displays errors. | Prove empty versus unavailable behavior on disposable Proxmox, including one failed VM family query, permission denial, stopped guests, and RRD outage. Malformed IDs and nonnumeric/negative/nonfinite measurements now raise errors (DR143); live verification remains open. | A5 dashboard / runtime verification |
| REAL-002 / P1 | `config_diff.py` presented failed ethtool queries as disabled settings and missing package tools as uninstalled packages. Now raises `ReadbackError`; HTTP returns 503, CLI returns nonzero, selective updates report failure without applying unknown network state. | Support per-field unsupported/unknown states without forcing an entire interface into invented defaults. Opaque/per-device/incomplete/unknown smartd directives now refuse readback and partial updates without writes (DR143); extending supported readback remains open. Cross-check on real ethtool/dpkg and verify partial updates preserve unselected fields. | 72 / configuration apply |
| REAL-003 / P2 | Optional diagnostics now save without execution; firstboot skips active tests. Explicit Run accepts a chosen port, verifies existing private-source firewall and owned listener, and returns measured details (DR154). | Actual SQLite/HTTP/nftables/systemd/iperf3 checks pass without FakeRunner, including custom-port virtual local transfer, conflict cleanup and single-use exit. DR156 physically measures Ethernet/AP/Wi-Fi at 189.4/138.2 Mbit/s with hardware counters and observed cleanup. Separate-host and successful browser active traffic plus delayed-start/cleanup-failure runtime proof remain open as optional diagnostics, not global readiness gates. | DR139 / diagnostics; DR152–154 |
| REAL-004 / P0 | Selective handoff now reads exactly one `etc/baseline/install-config.json` member from a validated local backup, validates supported category keys, applies only selected sections, and merges them into the live config. It never extracts archive paths. Archive path is an Installer setting. | Remaining: exercise actual archive parsing/apply/persistence on a disposable installed system and confirm network-only restore leaves user files and SSH unchanged. Handoff config-category restore does not restore credentials, machine identity, user files, or diagnostics; those retain their separate trust and persistence flows. | 59, 75 |
| REAL-005 / P0 | DR141 ancestry patch could ignore a cyclic branch or an ancestor with no serial. Now follows only a bounded single parent chain and refuses branching/cycles/missing identity. DR187 makes Drive Administration refuse to list eligible targets when boot-drive serial cannot be established. DR214 makes an unreadable enrollment registry an explicit inventory/action/backup error instead of an empty allowlist. | Check command failures explicitly in the physical metadata runner; use a complete supported storage graph for multi-disk/ZFS roots. Protect every ancestor, including picker/enrollment views. Prove LVM in disposable Proxmox and separately verify attached hardware metadata. Never bypass unknown identity. | 55, 72 |
| REAL-006 / P1 | Hardware command failures looked like empty buses. Individual collectors raise `InventoryError`; aggregate results preserve successful observations and show failed probes. DR166 rejects malformed/partial output; DR181 rejects missing stdout and distinguishes unreadable PCI driver metadata from a successful no-driver read. DR183 applies the same rule to LVM and mounted-volume usage; DR184 rejects malformed/duplicate LVM rows; DR187 applies it to candidate drives, partition trees, PV/VG discovery, and Baseline drive status. DR199 removes generic `Linux`/empty defaults and silent exception swallowing from the host Hardware overview; collector and `/proc` failures now appear as per-source errors. DR205 makes GPU discovery raise on failed `lspci`; DR208 makes GPU capability read/list errors and malformed values explicit rather than false empty/zero capabilities. DR216 preserves malformed Baseline configuration and failed reads as unknown keys with diagnostics. | Remaining: cover other `real_volume_state` consumers and dependency/readback gaps; verify GPU capability and other host probes against real hardware through the normal application path. Never represent unavailable inventory as empty. | hardware dashboard / 72 |
| REAL-007 / P0 | `netpref.py` invented a gateway from the first subnet host and ignored failed route demotion. Now uses only an observed default route and checks each mutation; failures do not save preference and partial changes are reported. DR206 distinguishes failed route/address probes from successful empty observations and preserves gateway-less default routes for address checks. DR207 makes NIC sysfs/carrier failures visible; DR209 preserves driver lookup failures as unknown through lifeline and TUI; DR210 keeps traffic-counter errors distinct from confirmed zero traffic; DR211 prevents the connection modal from treating unreadable admin flags or udev identity as a confirmed state, and verifies `ip link` changes by readback. DR218 keeps tether sysfs and command failures distinct from confirmed no-device/no-carrier/no-offer states, and the Tether action reports its result. | Reuse the existing network repair transaction for snapshot, apply, readback and rollback. Preserve gateway-less routes, metrics and route attributes. Verify route state before claiming success; demonstrate failure recovery without cutting off the session. Verify tether through a real USB phone/hotspot and DHCP path. | network repair |
| REAL-008 / P0 | `appdata.py` plans OverlayFS/Quadlet specs and now verifies the selected labeled ext4 mount read-only (DR200); neither proves confinement. `/app-isolation` still has no runtime apply. | Implement Ubuntu/Chromium identity, apply overlays only after `verify_appdata_mount`, sandbox permissions and explicit sharing. Prove two-app denial, reset/rebuild, migration and recovery using existing Linux sandbox tools. Keep runtime apply gated until those checks exist. | 74 / F01 |
| REAL-009 / P0 | Installer plan compile/export is real; durable stage execution, mount application and managed firstboot integration remain incomplete. Settings rebuild only records a request and returns failure, now tagged REAL-009. | Connect existing validated installer, layout, VM and tasker stages to recoverable jobs and actual readiness. Apply/reconcile PARTUUID mounts through existing gates. Prove shipped provision/reboot/kiosk end to end without manual developer repair. | 72, 75, 76 / F02, F03, F08 |
| REAL-010 / P1 | Cached Debian package/firmware `.deb` update checks and verified download-only refresh now work against the host's configured APT trust policy (DR204); only a verified `INSTALLER_CACHE` is eligible and nothing is installed on the host. Other artifact categories remain unsupported. DR185 also makes cache inventory fail closed when the volume is unmounted or a directory listing fails; no fallback directory is labeled as cache content. | Add publisher/version evidence and review flows for OS images, OCI images, pinned scripts and other artifacts. Keep download, verification, application and rollback as distinct states; manually pinned scripts remain review-controlled. | DR139 / 67, 72, 74 |
| REAL-011 / P0 | Legacy guest-backup selector covers local-lvm only. Its operation description incorrectly implied guest files in volume backups establish recovery. Description now explicitly states split/external guest storage and live recovery are not covered. | Inventory native guests and all separate OS/user/bind stores; prove quiesced backup and restore. Keep DR124's implemented LXC retained-data recovery. Never advertise active qcow2 copying as recoverability. | 60, 75, 77 / F04 |
| REAL-012 / P2 | Firstboot always said no intent was staged without inspecting staging. It now states staging inspection is unavailable and actual staged state is unknown. | Either implement inspection/reporting against an explicit staging contract or retire that status field. Existing signature/strict-parser primitives are real and remain intact; informational status must not become authorization. | installer firstboot scope |
| REAL-013 / P1 | `ProxmoxVmHost.delete_vm()` ignored local directory cleanup errors and removed its record after native destruction. DR190 now records the native destroy transition, reports local cleanup failure, retains the record, and resumes cleanup without repeating `qm destroy`. DR191 fixes retry after direct QEMU VM disk removal. DR192 makes direct QEMU base conversion report cleanup errors and resume from a store-level operation record, including partial removal of `vm.json`. DR219 prevents local QEMU inventory from silently omitting a managed VM with a corrupt/unreadable record; status becomes unknown and the page reports inventory unavailable. DR220 surfaces failed Proxmox `vmbr0` homepage detection while retaining a blank manual-entry value only for a successful probe with no usable address. | Verify Proxmox behavior on a disposable host and direct QEMU behavior with a real disposable VM. Safe retirement of VMs with retained data remains refused until the retained disk can be detached and recovered safely. | queue72 VM lifecycle |

## Findings that are not fake implementations

DR222 fixes retained-container backup inventory's false-empty cases: a
redirected set, invalid path, or unreadable manifest now raises an error, while
only a missing root or unpublished manifest is omitted. Disposable tests pass;
real destination and live Proxmox backup/restore remain open under queue items
56 and 59/60.

DR221 fixes a false-empty backup inventory: a missing manifest still means an
unfinished set, while a corrupt/unreadable manifest or invalid verification
marker is now an explicit error. Synthetic backup tests passed; live destination
verification remains open under queue item 56.

DR153 continuation: REAL-003 discovery checked 253 actual private addresses and
found no successful standard-port LAN peer or Proxmox version response. PC401
root remains held in 23 namespaces, blocking installed physical workflow proof
under DR146/queue78. DR154 corrects the endpoint framing: standard-port
responses are not normal-use prerequisites. Existing-policy readback and explicit
Run now resolve the partial Diagnostics apply issue, with actual Linux workflow
proof. DR156 subsequently verifies physical Ethernet/AP/Wi-Fi throughput; installed
Proxmox/native boot remains unverified.

REAL-006 now preserves MAC-less interfaces such as tailscale0. A real failing
host inventory comparison preceded the fix; afterward five interfaces, 45 PCI
devices/driver bindings and 13 whole disks match actual commands/sysfs, without
FakeRunner. Malformed/partial output and unavailable driver readback stay open.

- Runner/host/transport injection and fake runners in tests are intentional
  boundaries. Abstract methods already raise `NotImplementedError`; deleting
  these interfaces does not produce a working runtime.
- `testpersistence` and `experiments` are explicitly synthetic research, not a
  production vault/storage implementation. No production import of
  `testpersistence` was found in this pass; textual references are not imports.
- Distro catalogues and app plans are previews. Native distro LXC and Ubuntu
  paths have earlier disposable-Proxmox proof (DR117/118); requested desktop/NAS
  catalogues have not all been installed. Harvester needs an actual adapter.
- Disabled tether and empty handoff selections are explicitly described no-ops.
  The audit does not pretend that such a request changed a running service.
- Core VM/LXC/docker helpers execute real commands. Their synthetic tests verify
  orchestration; hardware/runtime certification requires separate evidence.

## Closure rule

Track each task's implementation, synthetic tests, disposable runtime proof and
physical proof separately. Close only the layer actually demonstrated. Passing
the unit suite never closes a runtime-proof requirement. Full-project production
readiness remains open while this register has unresolved workflow tasks.

## REAL-013: Common storage placement and capacity reassessment

DR144: implement persisted role mappings for reads/writes, stable backing
identity, measured capacity/headroom, explicit unsuitable-target errors and
slower-drive recommendations with existing occupants explained. Preserve
predefined retention/isolation roles. Implement recoverable migration before
switching populated targets. Acceptance: undersized fast target, suitable
slower target, missing storage, unknown capacity, thin-pool constraints and
interrupted migration without data loss. Existing VM/LXC arguments and
AppData overrides are partial only. DR145 adds the selectable independent
single-drive preset, role/headroom capacity checks, explicit serial CLI proposal,
compiled LVM stage and physical free-space checks (201 focused tests against
fakes and a local HTTP test server; hardware inspected read-only). Persisted measured placement, safe physical
migration, backing-serial stage execution and independent boot proof remain open.
Queue rows 72/75/76; not runtime verified.

DR155 adds real default-port 5201 workflow proof and a temporary LAN listener.
DR156 subsequently measures the physical Ethernet/AP/Wi-Fi path and verifies
cleanup. The historical endpoint was bounded to one
client or ten minutes. See verification/155; no Proxmox deployment proof.

DR156 resolves the broad unmeasured-physical-LAN finding. Separate-host and
browser active traffic remain distinct open REAL-003 checks.

DR224 closes a recovery-web failure path: unreadable kernel mount state now
returns an explicit HTTP 503 diagnostic for discovery and exit, and cannot
satisfy the read-write recovery exit condition. Four RealRunner integration
checks passed; this did not access physical storage or use FakeRunner/FakeProc.

DR225 closes local VM observer false states: invalid PIDs and procfs read
errors/corrupt PID records no longer become false-dead or absent observations,
empty command lines are represented as empty, and invalid/symlinked ISO roots
no longer become empty catalogues. Five integration checks used real process state/files;
no QEMU guest was started and FakeRunner/FakeProc were not used.

DR226 closes the recovery-state false-inactive path: malformed or unreadable
state is now an explicit observation error in the web view and cannot be
reported as recovery inactive. Ten RealRunner checks used existing procfs,
fstab, and live process state; no fixture files, FakeRunner, or FakeProc.

DR227 closes the persistence false-absence path: discovery uses a validated,
nonempty `lsblk` inventory and rejects duplicate labels or inventory errors
before local-volume fallback. Live RealRunner checks found `CACHE` and a
confirmed absent audit label. The host's real `blkid -L USER` returned status 2
without diagnostics; no block device was written or mounted, and no
FakeRunner/FakeProc was used. Native USER-volume self-install remains open.

## PC401 boot continuation — 2026-10-04 (DR157)

Recovery/physical identity checks passed, but the guarded boot-only attempt
stopped before VG deactivation/QEMU: root is held by 23 distinct mount namespaces
across 45 processes. Ordinary namespace unmounts did not release it. Current
GNOME shutdown inhibition requires the supported native-confirmed host lifecycle
step before another boot attempt; no host restart or enclosure power-off occurred.
Actual read-only ext4/LVM checks passed eight fstab role UUIDs, separate storage
policy and marker identities, renamed GRUB root, nonempty kernel/initramfs files,
enabled firstboot unit files and a 22-entry restoration manifest. This is physical
configuration proof, not runtime services, post-rename QEMU boot or native cold
boot. No FakeRunner. See DR157 and verification/157. Boot remains open under
DR146/queue78; payload restoration hashes were not rechecked in this increment.
