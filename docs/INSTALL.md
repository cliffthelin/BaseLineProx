# Installing BaselineOS on real hardware

## Installer-lane drive locks — 2026-10-11 (DR300)

The data-protection guard maps each pinned installer UUID to its assigned
development serial: Codex to PC401 (`MD89N41071210AP4E`) and Claude to PC601
(`FD01N6557110C271B`). An exact `lsblk` serial check enables only the current
lane's drive and refuses the other lane's drive before empty-disk or
installer-UUID allowances. Failed or ambiguous observations do not grant the
development exception. The current checkout is Claude's lane; PC401 boot,
GUI, network, firewall, internet, and workload readiness remain unverified.
See [DR300](design/decision-records/300-pc401-serial-bound-development-drive-lock.md).

## Current platform source included in rebuilt installer ISO — 2026-10-10 (DR243)

Built `iso_build/BaselineOS-platform-20261010.iso` from the publisher's
Proxmox VE 9.2-1 source ISO and the current repository. The ISO carries the
Baseline application and install code, all `docs/`, root `README.md` and
`AGENTS.md`, packaging, automation, tools, and tests under `/baseline-src`.
An independent xorriso inventory matched all 1,412 regular source files in
those paths with no missing files. A real KVM boot of the resulting image
reached the Proxmox graphical installer menu; networking and target disks
were disabled. This proves the remastered ISO boots in KVM, not installation
to a physical drive, unattended firstboot, or native cold boot. The screenshot
and build details are in [verification/177](verification/177/README.md).
The new source-staging regression test uses the production filesystem runner
and passed; no fake runner was run. See
[DR243](design/decision-records/243-current-platform-source-included-in-rebuilt-installer-iso.md).

## Proxmox detection failures cannot trigger installation — 2026-10-09 (DR242)

The Proxmox gate now distinguishes confirmed absence from failed probes. An
unknown result blocks firstboot before network discovery or package installation,
and is retried on the next invocation. Four pure gate/decision tests pass. A
read-only production probe on this development host confirmed the fresh-host
path; no installer was run. No FakeRunner/FakeProc or physical hardware was
used. See
[DR242](design/decision-records/242-proxmox-detection-failure-blocks-installer.md).

## Remote-access probe failures stay visible — 2026-10-09 (DR241)

Remote Access now distinguishes an unavailable listener probe from a successful
empty listener list, validates the `ss` table shape, and displays individual
command failures. Five pure parser/page contract cases pass. A read-only live
collection using production commands listed 46 listeners and surfaced
`sshd -T`'s missing-hostkeys error; this was not a Proxmox-drive verification.
No FakeRunner/FakeProc was used. See
[DR241](design/decision-records/241-remote-access-probe-failures-visible.md).

## inxi schema rejects missing core observations — 2026-10-09 (DR240)

The hardware normalizer now rejects malformed or empty inxi structures and
requires nonempty System and CPU observations. Missing optional sections such
as network and drives remain valid. Seven pure contract tests pass; no
FakeRunner/FakeProc or live hardware probe was used. See
[DR240](design/decision-records/240-inxi-schema-rejects-missing-core-observations.md).

## Required hardware buses reject blank probe output — 2026-10-09 (DR239)

Hardware inventory now reports blank PCI, whole-disk, or network command output
as an observation error instead of an empty bus. Successful blank USB output
remains a valid “no visible peripherals” result. Four pure contract tests pass;
no FakeRunner/FakeProc or live hardware command was used. See
[DR239](design/decision-records/239-hardware-inventory-rejects-blank-required-bus-output.md).

## Web applications reject invalid JSON consistently — 2026-10-09 (DR238)

The merged Baseline server, Settings server, Control Panel, and scripts inbox
now share a bounded JSON-object parser. Invalid lengths, oversized or
incomplete bodies, invalid UTF-8, malformed/non-object JSON, duplicate keys,
and non-standard numeric constants return HTTP 400 before route dispatch.
Form submissions retain their existing parser. Twelve focused tests pass,
including real local HTTP tests for the scripts inbox and Control Panel with
production filesystem runners. See
[DR238](design/decision-records/238-web-handlers-share-strict-json-parsing.md).

## Scripts inbox rejects malformed JSON writes — 2026-10-09 (DR237)

The scripts inbox no longer turns invalid request JSON into an empty object.
Malformed, empty, oversized, non-object, and invalid-length bodies return HTTP
400 before writing a script. A real local HTTP test reproduced the old 200
response for malformed JSON and now verifies the 400 response and absence of a file using the
production filesystem runner. No script was executed. Other web JSON parsers
remain to be audited. See
[DR237](design/decision-records/237-scripts-inbox-rejects-invalid-json-bodies.md).

## Missing tether inventory is reported as an error — 2026-10-09 (DR236)

If `/sys/class/net` is unavailable, automatic tether detection now reports a
probe error instead of claiming no tether adapter exists. A genuinely empty
readable inventory still reports no candidate. The regression exercises the
real `auto_tether` result without running network commands; all seven
tether-truthfulness tests pass. Physical tether/DHCP/internet verification was
not performed. See
[DR236](design/decision-records/236-tether-inventory-unavailable-is-an-error.md).

## Corrupt audit records are reported as unavailable — 2026-10-09 (DR235)

The Audit view no longer skips malformed JSONL entries and presents a partial
history as complete. Invalid records and incomplete writes raise an audit
read error; the authenticated page returns an unavailable response. All 18
audit/approvals page tests pass, including a real local HTTP request against a
corrupt log. A missing log remains an empty history. No physical drive or
external service was used. See
[DR235](design/decision-records/235-audit-view-rejects-corrupt-history.md).

## Retained launch scale applies across application adapters — 2026-10-09 (DR234)

Baseline display scale can now be changed for an installed Spotify, ChatGPT,
or Claude profile. The value is atomically stored in mode-0600
`home/.baseline/BASELINE.json` under the retained application data, included in
the retained-state backup, and read by both capture and launch.
The regression failed before the fix; all 39 application-bundle tests and two
persistent-catalog page tests pass. This does not prove visible GUI behavior or
native preference capture, and no package, guest, or physical drive was used.
See [DR234](design/decision-records/234-retained-launch-settings-apply-across-application-adapters.md).

## Task catalog revisions include custom package locks — 2026-10-09 (DR233)

Tasker now includes the loaded application catalog digest in each component
revision, so changing a custom package URL or SHA256 changes the advertised
revision. The regression test failed before the fix; all seven focused
custom-application contract tests pass after it. This was local code/catalog
verification only: no package download, install, guest, or physical drive was
involved. Installer Plan acquisition and runtime proof remain open under queue
item 76. See [DR233](design/decision-records/233-task-catalog-revisions-include-custom-application-locks.md).

## Custom application definitions persist in configured state — 2026-10-09 (DR232)

The writable custom application catalog now lives in the web server's
configured state directory, separate from the installer source and cache.
`baseline-apps` and `baseline-tasker` reload those entries in new processes.
Seven focused application-bundle contract tests and two shortcut-catalog tests
passed, including an authenticated real-socket catalog write/read; the real
`baseline-tasker catalog` command also passed. No FakeRunner/FakeProc was used.
No third-party package was downloaded or installed, and physical persistence
mount survival remains unverified. Installer Plan package acquisition remains
open under queue item 76. See
[DR232](design/decision-records/232-custom-application-catalog-persistence.md).

## Custom application package sources are locked — 2026-10-09 (DR231)

Custom application definitions now require an exact credential-free HTTPS
Debian package URL and SHA256. The web catalog and `baseline-apps` reload the
saved definitions through the installer source-root resolver; native
preparation verifies the download digest and Debian package identity before
binding a recipe. Four focused contract tests and the real CLI help command
passed without FakeRunner/FakeProc. No publisher package was downloaded or
installed and no guest or physical drive was used. Installer Plan input
preparation still does not acquire custom app packages; native install/runtime
proof remains open under queue item 76. See
[DR231](design/decision-records/231-custom-application-source-locks.md).

## Confirmed Proxmox VM retirement validates and removes managed data — 2026-10-09 (DR230)

The Proxmox Delete action now validates the live VMID, stopped state, storage
identity, disk attachments, and volume paths before deleting the OS and retained
home disks. It records validated volume identities for retry-safe cleanup and
stops on unexpected or unowned files. The confirmation explicitly warns that
retained home data is erased. Seven pure ownership/parser contract tests passed;
no FakeRunner/FakeProc or Proxmox command was used. `qm`, `pvesh`, and `pvesm`
are absent on this host, so native deletion and physical storage cleanup remain
unverified under queue item 75. See
[DR230](design/decision-records/230-confirmed-proxmox-vm-retirement.md).

## VM inventory requires its configured store — 2026-10-09 (DR229)

Local VM/base and Proxmox VM inventories now validate their configured stores
before reporting entries. A missing required mount or INSTALLER_CACHE path is
an inventory error; an empty list is reserved for a valid store with no
records. Four real-path integration checks passed, with no fakes, Proxmox
commands, VMs, or physical drives. Native mount and VM lifecycle proof remains
open under queue items 7, 72, and 75. See
[DR229](design/decision-records/229-vm-inventory-requires-mounted-store.md).

## Invalid VM storage configuration stays visible — 2026-10-09 (DR228)

Existing malformed, unreadable, or invalid VM/container storage settings no
longer silently redirect workload operations to default directories. Missing
first-run configuration still uses the defaults, and VM/container storage saves
preserve unreadable existing settings instead of replacing them. Eight
integration checks passed using procfs, `/etc`, the production host resolver,
and unsafe/allowed storage path cases; syntax and diff checks passed. No
Proxmox command, VM, or physical drive was accessed. Native VM
storage and lifecycle verification remains open under queue items 7 and 75.
See [DR228](design/decision-records/228-vm-storage-config-errors-visible.md).

## Persistence label discovery errors stay visible — 2026-10-09 (DR227)

Persistence discovery now uses validated structured `lsblk` output because
`blkid -L` status 2 is ambiguous between absence and failed identification.
Only a complete inventory with no exact match permits local-volume fallback;
inventory errors or duplicate labels stop with a diagnostic. RealRunner checks
found the live `CACHE` label and confirmed an absent audit label. No block
device was written or mounted. Native USER persistence install remains open
under queue items 7 and 26. See
[DR227](design/decision-records/227-persistence-label-inventory-errors-visible.md).

## Corrupt recovery state stays visible — 2026-10-09 (DR226)

Malformed or unreadable recovery state now produces a visible 503 diagnostic
instead of being reported as inactive. Ten RealRunner integration checks
passed against existing procfs/fstab paths and a real child process, without
test fixtures or FakeRunner/FakeProc. No physical storage was touched. Native
recovery operation remains open under queue items 7 and 26. See
[DR226](design/decision-records/226-corrupt-recovery-state-visible.md).

## QEMU process observation errors stay visible — 2026-10-09 (DR225)

The local QEMU host now rejects invalid process IDs, reports procfs/PID-record
read failures instead of treating them as stopped VMs, and represents an empty
command line as empty. ISO inventory rejects symlinked roots and errors on
invalid/unreadable paths instead of returning an empty catalogue. Five
RealRunner integration checks passed
with real process state and files. No FakeRunner/FakeProc, QEMU guest, or
physical VM was used.
VM lifecycle work remains open under queue item 75. See
[DR225](design/decision-records/225-qemu-process-observation-errors-visible.md).

## Recovery mount observation errors stay visible — 2026-10-09 (DR224)

Recovery discovery and exit return a visible 503 diagnostic when the kernel
mount table cannot be read. Recovery cannot exit unless a persona is confirmed
read-write. Four focused integration checks passed with `RealRunner`; no
FakeRunner/FakeProc or physical drive was used. Native recovery and physical
persistence-volume operation remain open. See
[DR224](design/decision-records/224-recovery-mount-observation-errors-visible.md).

## Declared harness failures stay visible — 2026-10-09 (DR223)

Claude/OpenCode remain selectable only when their modules load and satisfy the
adapter contract. A broken declared adapter now raises a diagnostic shown in
the status, console, or chat UI instead of appearing absent. Unknown and
deliberately unimplemented IDs remain unselected. The registry/adapter/
streaming/Baseline web suite passed 126 tests with injected import and contract
failures; no live harness process or provider was invoked. See
[DR223](design/decision-records/223-declared-harness-failures-visible.md).

## Retained-container backup inventory errors stay visible — 2026-10-09 (DR222)

Container backup listing now reports redirected sets, invalid paths, and
unreadable or malformed manifests as errors. It omits only a missing backup
root or a set whose manifest has not yet been published. Restore shares the
manifest checks and validates archive type, size, and digest. The focused
container, guest, distro-container, off-drive backup, and Operations suites
passed 139 tests with disposable files and scripted runners; no physical
destination or live Proxmox container was accessed. See
[DR222](design/decision-records/222-container-backup-inventory-errors-visible.md).

## Backup manifest errors stay visible — 2026-10-09 (DR221)

Off-drive backup inventory now omits only sets whose manifest has not yet been
published. Corrupt/unreadable manifests and invalid verification markers raise
visible errors instead of making backups disappear. The focused backup,
Operations, and audit/approval suites passed 105 tests with disposable files
and scripted runners; no real backup drive or archive was accessed. Live
verification remains open under queue item 56. See
[DR221](design/decision-records/221-backup-manifest-errors-stay-visible.md).

## Proxmox homepage probe errors stay visible — 2026-10-09 (DR220)

The Ubuntu VM form no longer treats a failed or malformed `vmbr0` address
probe as a valid blank homepage. A successful probe with no usable global IPv4
address remains a manual-entry case; failures appear beside the setting. The
combined Proxmox/QEMU VM host, page, and web suite passed 93 tests with injected
command and JSON failures and a local HTTP fixture; no live bridge or guest was
accessed. See
[DR220](design/decision-records/220-proxmox-homepage-probe-errors-visible.md).

## VM inventory errors stay visible — 2026-10-09 (DR219)

The local QEMU VM list no longer skips managed VMs with unreadable or malformed
records. The status API returns an unknown/503 response, and the VM page labels
the inventory unavailable instead of saying there are no VMs. The focused VM
host/web/page suite passed 68 tests with disposable records and a synthetic
runner; no real QEMU, Proxmox host, or physical drive was accessed. See
[DR219](design/decision-records/219-qemu-vm-inventory-errors-visible.md) and
REAL-013.

## USB tether probe and action errors stay visible — 2026-10-09 (DR218)

Tether discovery now distinguishes a confirmed absent interface from failed
sysfs reads. Interface bring-up and address-query command failures no longer
continue as if there were no carrier or DHCP offer, and the Tether action
reports its actual result in the console and notification. The focused tether,
configuration-apply, network, web, and TUI source-contract suite passed 162
tests with injected failures; no live USB tether or network configuration was
exercised. See
[DR218](design/decision-records/218-tether-probe-and-action-errors.md) and
REAL-007.

## Registry query failures stay visible — 2026-10-09 (DR217)

Read-only registry listing still returns an empty set when its database is
genuinely absent. If an existing database cannot be queried, it now raises
`RegistryReadError` instead of hiding stored state behind `{}`. The registry
and direct-consumer suite passed 489 tests using disposable SQLite databases
and synthetic runners; no production registry or physical drive was read or
changed. See
[DR217](design/decision-records/217-registry-read-failure-is-not-empty.md).

## Malformed Baseline config remains unknown in inventory — 2026-10-09 (DR216)

Malformed JSON and non-object Baseline configuration files no longer appear as
empty objects in host inventory. The manifest records unknown keys and a parse
diagnostic; failed reads also retain their error. Valid empty objects remain
empty. The focused config/inventory-manifest/validator suite passed 25 tests
with a synthetic inventory runner; no host configuration was read. See
[DR216](design/decision-records/216-malformed-baseline-config-is-unknown-in-inventory.md)
and REAL-006.

## Audit history read errors stay visible — 2026-10-09 (DR215)

A missing audit file remains an empty history, while other read errors now show
Audit unavailable. Operations history shows an explicit error, and its JSON
endpoint returns HTTP 503 instead of an empty run list. The focused
audit/approvals and operations suites passed 85 tests with injected read errors
and local HTTP requests; no host audit log was read or changed. See
[DR215](design/decision-records/215-audit-log-read-errors-are-not-empty-history.md).

## Drive enrollment read errors stay visible — 2026-10-09 (DR214)

An unreadable enrollment registry no longer appears as an empty set. Drive
action validation reports the registry diagnostic, drive inventory returns an
inventory failure, and off-drive backup refuses to proceed without being able
to identify all managed drives. The focused drive-enrollment, backup,
drive-admin, and web suite passed 394 tests with scripted runners and
disposable registry files; no physical drive or backup was touched. See
[DR214](design/decision-records/214-drive-enrollment-read-failure-is-not-empty.md)
and REAL-005.

## Network dashboard reports bridge inventory errors — 2026-10-09 (DR213)

The dashboard now uses the network module's bridge-member probe. A confirmed
non-bridge remains an empty member list; an inaccessible member list appears as
Unknown with its diagnostic instead of silently omitting interfaces. The
focused provider, harness, network, firstboot, readiness, Settings, and TUI
suite passed 210 tests with injected observations; no live bridge state or
interactive Textual render was verified. See
[DR213](design/decision-records/213-network-dashboard-surfaces-bridge-enumeration-errors.md)
and REAL-007.

## Provider discovery preserves probe uncertainty — 2026-10-09 (DR212)

Credential-file read errors now show Unknown, empty key assignments do not
count as configured, and the Claude status no longer calls a configured token
live-verified. Ollama TCP refusal is Unreachable while timeout and other socket
errors remain Unknown. Dashboard status preserves those distinctions. The
focused provider, harness, network, firstboot, readiness, Settings, and TUI
suite passed 209 tests with injected observations; no host credentials or live
provider services were queried. See
[DR212](design/decision-records/212-provider-observations-remain-unknown.md).

## Network modal preserves unknown state — 2026-10-09 (DR211)

The connection modal no longer assumes an interface is enabled when its
administrative flags cannot be read. It shows Unknown and disables the switch;
hardware identity probe errors remain visible, and `ip link` changes are
confirmed by a state readback before success is reported. The focused network,
firstboot, readiness, Settings, and TUI suite passed 197 tests with injected
observations. No live network state was queried or changed, and interactive
Textual rendering was not verified. See
[DR211](design/decision-records/211-network-modal-unknown-admin-state.md) and
REAL-007.

## Network traffic counter errors stay visible — 2026-10-09 (DR210)

Unreadable or malformed interface traffic counters no longer appear as zero
traffic. The TUI shows a traffic-counter error; confirmed zero counters still
produce the normal quiet “no traffic” display. The focused network,
firstboot, readiness, Settings, and TUI suite passed 190 tests with injected
observations; no live traffic counters were read. See
[DR210](design/decision-records/210-network-traffic-counter-errors.md) and
REAL-007.

## Network driver lookup preserves unknown state — 2026-10-09 (DR209)

Driver-link read failures no longer become “not wired” or “no driver.” The
lifeline distinguishes a confirmed unbound adapter from an unavailable driver
observation, and the TUI shows Unknown when it cannot establish the link type.
The focused network, firstboot, readiness, Settings, and TUI suite passed 187
tests with injected observations; no live network configuration was changed.
See [DR209](design/decision-records/209-network-driver-state-is-unknown.md)
and REAL-007.

## GPU capability probe errors stay unknown — 2026-10-09 (DR208)

SR-IOV read errors and malformed values no longer become zero VFs; an existing
mediated-device directory with no types no longer claims active support. GPU
path/listing errors are explicit. All 41 GPU-admin tests pass, and the combined
GPU, hardware-inventory, and Quadlet suite passed 127 tests with scripted
observations. No physical GPU capability was inspected. Live GPU readback
remains under REAL-006. See
[DR208](design/decision-records/208-gpu-capability-probe-errors.md).

## Network interface inventory preserves unknown state — 2026-10-09 (DR207)

Unreadable `/sys/class/net` or carrier observations no longer become an empty
NIC inventory or a disconnected wired link. The lifeline reports probe errors,
the TUI labels per-interface carrier state as Unknown, and Settings shows an
alert when interface choices cannot be loaded. The combined network,
firstboot, readiness, Settings, and TUI suite passed 184 tests with injected
observations; no physical network state was changed. Route preservation and
rollback remain open under REAL-007. See
[DR207](design/decision-records/207-network-interface-inventory-errors.md).

## Network lifeline distinguishes failed probes — 2026-10-09 (DR206)

Route and IPv4 address command failures now appear as unavailable observations
instead of “no route” or “no address.” A successful query that finds no route
or address remains a separate result. Gateway-less default routes retain their
interface for address checks, and bridge-member permission and I/O errors
surface as probe errors. The focused network, firstboot, and readiness suite
passed 59 tests with scripted observations; no network configuration was
changed. Route-attribute preservation and transaction rollback remain open
under REAL-007. See
[DR206](design/decision-records/206-network-probe-failures-are-unknown.md).

## GPU inventory errors remain visible — 2026-10-09 (DR205)

GPU discovery now raises an explicit inventory error when `lspci` fails rather
than presenting the failure as an empty GPU list. A successful scan with no
GPU-class devices still returns an empty list. The 37 GPU unit tests pass with
scripted command/sysfs responses; no real inventory was read. See
[DR205](design/decision-records/205-gpu-inventory-failure-is-not-empty.md) and
REAL-006.

## Installer package-cache update action — 2026-10-09 (DR204)

Drive Administration now refreshes signed APT metadata using the host's
configured trust policy, compares cached Debian `.deb` versions with current
candidates, downloads newer archives into the verified `INSTALLER_CACHE`, and
checks their package/version/architecture before reporting success. It never
installs packages on the running host; only `INSTALLER_CACHE` can be selected.
The focused 336-test suite uses scripted command responses. Real repository
access and physical cache-volume updates were not exercised. Updating and
reviewing ISO, OCI, and pinned-script sources remains open under REAL-010. See
[DR204](design/decision-records/204-verified-installer-package-cache-updates.md).

## App Isolation page checks its selected volume — 2026-10-09 (DR203)

`/app-isolation` now runs DR200's read-only volume check for the selected
persona and renders the verified mountpoint or a visible error. It no longer
claims that live mount verification is absent. It still does not apply
overlays or prove process confinement. The combined focused suite passed 185
tests with scripted command responses; no physical volume was inspected or
changed. See
[DR203](design/decision-records/203-appdata-page-live-volume-check.md).

## Hardware modal exposes only working controls — 2026-10-09 (DR202)

The legacy Textual hardware modal now shows the fields collected from the
selected device and a working Close button. Empty Description,
Troubleshooting, Logs, and Configuration panes and the no-op Save action were
removed. Its structural regression passes as part of the 98-test focused run;
the test environment lacks Textual/Rich, so no live modal render is claimed.
See [DR202](design/decision-records/202-hardware-modal-removes-inert-controls.md).

## Harness menu contains only adapters that can run — 2026-10-09 (DR201)

The TUI now offers only Claude Code and OpenCode, both backed by conforming
Baseline adapters. Hermes, Pi, DeepSeek, and GrokBot were removed from the
selectable list because they had no adapter, and Hermes ACP's default tool
surface does not meet Baseline's no-tools boundary. The registry regression
failed before this correction; focused registry tests pass. No model request
or real credential was used. See
[DR201](design/decision-records/201-selectable-harnesses-must-run.md).

## AppData refuses substrate-directory fallbacks — 2026-10-09 (DR200)

AppData now has a read-only runtime prerequisite that validates the selected
persona's filesystem label, exact mountpoint, ext4 type, and resolved block
device identity. A missing mount or any mismatch raises an explicit error;
there is no directory fallback. All 77 AppData tests pass with scripted
command results. No physical volume was mounted or changed. Overlay application,
per-app sandbox enforcement, migration, reset, recovery, and guest acceptance
remain open under queue74/REAL-008. See
[DR200](design/decision-records/200-appdata-volume-mount-verification.md).

## Selective handoff restores only chosen config sections — 2026-10-09 (DR197)

Handoff restore now reads one bounded `etc/baseline/install-config.json` member
from a validated backup under INSTALLER_CACHE. It validates selected categories
against supported settings, applies only those sections, and merges them into
the current config. Archive paths are never extracted, and diagnostics, user
files, SSH keys, and machine identity are not restored through this flow. The
Installer's handoff settings now include the archive path. Firstboot applies
handoff last so restored values take effect after its ordinary settings pass.
The focused config/pipeline/truthfulness tests passed (96) with FakeRunner
command and filesystem behavior. No real backup archive or installed system
was used; runtime and user-data isolation acceptance remains open under
REAL-004. See [DR197](design/decision-records/197-selective-handoff-config-restore.md).

## Partition-unmount action test contract — 2026-10-09 (DR198)

The browser action test now supplies the mounted partition path required by the
real modal, uses a RAM-drive action stand-in, and has a matching browser-only
agent definition. This fixes the test harness `KeyError` without bypassing the
production action's selected-drive serial check or human confirmation. The
focused action-bot and serial-safety tests passed (63 bot tests; 21 contract
tests); no real partition was unmounted. See
[DR198](design/decision-records/198-partition-unmount-agent-contract.md).

## Hardware overview preserves failed observations — 2026-10-09 (DR199)

The host Hardware overview now uses a real runner when one was not injected,
does not substitute generic Linux labels for missing kernel/distro facts, and
shows per-source errors when dependency, hardware, sensor, or `/proc` probes
fail. Successful observations remain visible alongside failures. The focused
Hardware web and truthful-runtime tests passed (116), using FakeRunner for
command recording and injected failure cases; physical probe success was not
claimed. See [DR199](design/decision-records/199-hardware-overview-observation-errors.md)
and REAL-006.

## Backup test-restore cannot claim success with leftover extracted data — 2026-10-09 (DR196)

The Operations test-restore now treats cleanup as part of its result. It
reports success only after the extracted sample is verified nonempty and the
temporary directory is confirmed removed. A cleanup error returns failure and
prints the remaining path; a restore error is also preserved in the report.
The regression reproduced the old false-success result. All 15 Operations
tests passed with synthetic backup data and injected filesystem errors; no
real backup archive or drive was read. See
[DR196](design/decision-records/196-test-restore-cleanup-truth.md), queue59.

## Handoff restore fails visibly when decrypted staging cannot be removed — 2026-10-09 (DR193)

The first-run wizard no longer suppresses cleanup errors for its decrypted
handoff staging directory. A failed apply still attempts cleanup and reports
both failures if cleanup also fails; cleanup failure after an applied restore
stops setup with an explicit error instead of printing success while plaintext
secrets may remain on disk. A focused regression and the direct VM lifecycle
tests pass (37 total) using synthetic filesystem/command behavior; no handoff
packet, credential, or physical host was used. See
[DR193](design/decision-records/193-handoff-plaintext-cleanup.md).

The same wizard now treats hostname application as one state change: it reads
the prior persistent and live values, applies the live hostname, persists it,
and rolls back on write failure. A denied live change leaves the hostname file
untouched; failed rollback is included in the reported error. Three focused
setup-wizard tests, handoff tests, and direct VM tests passed (68 total) with
synthetic inputs. No real hostname or credential was changed. See
[DR194](design/decision-records/194-setup-hostname-rollback.md).

Handoff application now treats its destination file set transactionally. It
backs up only existing files that the packet will replace, stages the writes,
and rolls them back if a later copy or metadata operation fails; newly created
files are removed, and unrelated files remain untouched. Unsupported links,
special destination files, and ambiguous duplicate paths are rejected before
application. Six setup-wizard tests, 29 real-GPG handoff tests, and 36
direct-VM tests passed (71 total), using synthetic restore destinations for
the wizard. No host packet or credentials were applied. Rollback failure is
surfaced with the affected destination paths. See
[DR195](design/decision-records/195-transactional-handoff-apply.md).

## VM deletion reports incomplete local cleanup and can resume — 2026-10-09 (DR190)

Proxmox VM deletion no longer ignores local directory cleanup errors or removes
the registration record before cleanup is confirmed. After Proxmox confirms
destroy, the durable record marks the VM as no longer registered; a failed
local cleanup remains visible and can be retried without destroying the VM a
second time. Proxmox-host unit tests pass with a synthetic command runner; no
live Proxmox VM was deleted. Retained-data retirement remains explicitly
refused. See [DR190](design/decision-records/190-proxmox-vm-cleanup-truth.md).

Direct QEMU VM deletion now persists a cleanup-intent marker before unlinking
the separately stored root disk. If removal of the VM's local metadata directory
then fails, a retry recognizes the partial deletion and completes without
mistaking the already-removed disk for an unexpected missing file. All 35
`tests/unit/test_vm_host.py` tests passed with an injected QEMU command runner;
this is synthetic local-filesystem evidence, not a live QEMU or physical-host
deletion. See [DR191](design/decision-records/191-qemu-vm-deletion-retry.md).

Direct QEMU base conversion no longer ignores failure to remove the consumed
installation VM directory. It records a freeze operation in the VM store before
moving the standalone disk, then makes cleanup strict and resumable even if the
VM record was removed before cleanup stopped. The regression injects a partial
directory cleanup; all 36 `tests/unit/test_vm_host.py` tests pass with a
synthetic QEMU runner. No live VM or physical disk was changed. See
[DR192](design/decision-records/192-qemu-freeze-resumable-cleanup.md).

## AppData requires explicit per-application data policy — 2026-10-09 (DR189)

`appdata.installable_apps()` now refuses a package or container catalog entry
that has no explicit data-target/bind policy. Only a declared empty policy
means stateless; missing metadata cannot silently become “no overlay.” The
current catalog is covered by its existing plan tests, and a new synthetic
catalog regression proves unknown package policy fails visibly. 74 AppData
tests and 3 direct isolation-page renderer tests passed. The broader web
route tests could not open local sockets in this run. AppData
runtime mounting and confinement remain unimplemented under queue74/REAL-008.
See [DR189](design/decision-records/189-appdata-policy-required.md).

## Off-drive backups require known boot-drive identity — 2026-10-09 (DR188)

Off-drive backup destination validation now refuses to proceed when the
running system's boot-drive serial cannot be established. When the root block
node is absent in this execution namespace, discovery follows findmnt's
major:minor through sysfs and reads the parent disk serial with udev. A
read-only host probe now resolves `SN211808916391`; this corrects DR187's
earlier inability to identify the development host's boot disk. Safety,
backup, guest backup, recurrence, and operations tests pass (134 tests) with
synthetic runners. No backup was written or physical drive verified. See
[DR188](design/decision-records/188-offdrive-backup-requires-boot-identity.md).

## Drive and LVM inventory failures stay distinct from empty drives — 2026-10-09 (DR187)

Drive Administration now raises an inventory error when candidate-drive,
partition-tree, physical-volume, or Baseline-volume probes fail or return
malformed output. It refuses to present an unavailable probe as an empty drive
list or a non-Baseline disk. The web page distinguishes a valid empty result
from an inventory failure, and repair/mount actions return an explicit refusal
when the VG cannot be identified. 317 focused drive, enrollment, and web tests
passed with synthetic runners. The initial read-only host check could not
establish the boot serial because the root device node was absent in this
namespace; DR188 adds a sysfs-backed lookup and resolves it. No physical drive
was modified or verified. See
[DR187](design/decision-records/187-drive-inventory-errors.md).

## Installer Cache catalog follows its owning modules — 2026-10-09 (DR186)

The declared cache catalog no longer substitutes fallback package/script lists
or a generic source origin when the authoritative firstboot or VM-script
modules fail to load. Reconciliation now surfaces that dependency failure on
the cache page instead of showing a plausible but incomplete build manifest.
131 focused cache, web, source, and installer-input tests passed with synthetic
runners; current host imports/catalog generation succeeded. No drive was
modified. See
[DR186](design/decision-records/186-installer-cache-catalog-ownership.md).

## Installer Cache inventory requires the real mounted volume — 2026-10-09 (DR185)

Cache refresh now refuses to scan `/mnt/INSTALLER_CACHE` when it is only a
directory on the root filesystem. Listing permission failures, missing roots,
missing command output, and malformed `ls` rows are also reported as inventory
errors; the page does not turn them into “missing” artifacts. The read-only
host check found the cache path is not a mount point. An earlier read-only
listing saw files in that fallback directory; they were left untouched. The
repaired live reconciliation reports unknown contents (zero rows), not cache
availability. 128 focused tests passed; no disk writes or file moves occurred.
See [DR185](design/decision-records/185-installer-cache-inventory-truth.md).

## Malformed LVM inventory cannot authorize volume creation — 2026-10-09 (DR184)

Successful but malformed or duplicate LVM rows now fail explicitly. The volume
ensure path refuses to create or format anything when the existing-volume
inventory cannot be parsed; size inventory no longer drops malformed rows.
207 focused tests passed against synthetic runners. No physical drive was
modified or verified. See
[DR184](design/decision-records/184-malformed-lvm-inventory.md).

## Volume inventory failures stay visible — 2026-10-09 (DR183)

Drive Administration now distinguishes failed LVM/usage probes from a valid
empty volume list. It uses `findmnt` to identify actual mounts, then reports a
`df` error for any confirmed mount it cannot measure. The restricted host's
read-only LVM query returned the explicit `no new privileges` error; a separate
read-only mount check found zero mounted Baseline volumes. Focused verification
passed 163 tests; the host probe is sandbox-limited and establishes no target
drive status. See
[DR183](design/decision-records/183-volume-inventory-errors.md).

## Per-user overlay commands resolve the target home — 2026-10-09 (DR182)

AppData OverlayFS command generation now requires and validates the target
persona's absolute home for `~/...` targets, producing a real path for `mount`
instead of a literal tilde. Absolute system targets remain directly usable.
The combined 248 focused tests passed with synthetic runners; no overlay was
mounted and app isolation remains unimplemented at runtime (REAL-008). See
[DR182](design/decision-records/182-appdata-overlay-home-resolution.md).

## Hardware inventory preserves unknown driver state — 2026-10-09 (DR181)

Hardware inventory now reports missing command output and unreadable PCI
`uevent` metadata as errors/unknown, not an empty bus or “no driver bound.”
The 61 focused tests passed with `FakeRunner`. A read-only development-host
probe parsed 45 PCI devices (zero driver metadata read errors), 16 with no
bound driver, and 13 block devices; `lsusb` and `ip` were blocked by the
restricted sandbox and remain unverified here. This is not Proxmox or physical
target verification. See
[DR181](design/decision-records/181-hardware-inventory-unknown-state.md).

## Backup archive listing reports read failures — 2026-10-09 (DR180)

`baseline-backup list` and the authenticated backup-list web action now report
the `tar` error and fail when an archive cannot be read. A failed read no longer
appears as a valid empty archive. The 114 focused tests use `FakeRunner`; no real
archive or drive was read, and this change does not complete selective handoff
restore (REAL-004). See [DR180](design/decision-records/180-backup-list-read-errors.md).

## PC601 app-mediated EFI unmount action — 2026-10-09 (DR179)

Drive Administration now has a serial-checked `Unmount partition` action in
the source. It verifies the mounted source, its parent disk, and the selected
drive serial before asking PolicyKit to unmount it. Unit tests cover ownership,
path restrictions, the app action, and its HITL gate. The currently running
development server was not reloaded, and the physical unmount was not
performed. PC601 remains mounted at `/mnt/sdb2`; do not move it until the app
reports success and `findmnt` confirms it is no longer mounted. The EFI
preflight still supports a controlled second-machine UEFI boot attempt; no
native boot, GUI, network, firewall, workload, or persistence verification
is claimed. See [DR179](design/decision-records/179-pc601-app-mediated-efi-unmount.md)
and [DR176](design/decision-records/176-pc601-uefi-portability-preflight.md).

## PC601 selected — existing Proxmox installation preserved (2026-10-08, DR174)

The selected target is PC601 serial `FD01N6557110C271B`, which already contains
Debian 13/Proxmox on the `pve` LVM layout. A read-only inspection found
`pve-root`, `pve-swap`, and `pve-data`, with about 438.94 GiB free in the volume
group; the root filesystem was about 87% used. Proxmox packages and an enabled
`pveproxy` unit were present in the inspected root filesystem. These are
installation-file observations, not proof that PC601 is currently booted,
networked, firewalled, or serving its GUI. The host-visible serial mapping at
that inspection was `/dev/sdb`; resolve by serial again before any operation.

The temporary root mount used `ro,noload` and has been unmounted. No PC601 data
was written. Do not run the Baseline drive installer over PC601: its current
Proxmox installation is the requested host and must be preserved. Existing
KVM screenshots/overlay results in DR48/DR117/DR165 are historical virtual or
prior-session evidence, not this session's native boot or live GUI acceptance.
Current cold boot, LAN/internet, firewall, actual browser GUI, workloads,
drivers, and physical overlay/user-data persistence remain unverified under
queue72/73/74/75/76/78. See [DR174](design/decision-records/174-pc601-selected-existing-proxmox.md).

## PC601 UEFI portability preflight (2026-10-09, DR176)

The current read-only EFI mount for serial `FD01N6557110C271B` contains the
x86-64 UEFI fallback loader at `EFI/BOOT/BOOTx64.efi` and Proxmox's
`EFI/proxmox/grubx64.efi`. The Proxmox EFI config searches for root UUID
`fa48739d-a429-4ac2-a2d5-7a6ab0883046`, matching the physical `pve-root`
filesystem UUID recorded in verification/143. Both EFI binaries were
recognized as x86-64 EFI applications. The EFI filesystem is mounted
read-only; this preflight made no disk writes. This supports a standard UEFI
boot attempt on another x86-64 machine without relying on this machine's UEFI
boot entry. It does not prove that another machine's firmware, storage
controller, NIC, or physical GUI/network path works. Follow the controlled
second-machine test in [DR176](design/decision-records/176-pc601-uefi-portability-preflight.md)
before treating native boot or Proxmox GUI/network acceptance as complete.
The current host still has `/mnt/sdb2` mounted read-only. Unmount requires
superuser rights; the privileged request was aborted, so do not disconnect the
drive until it has been cleanly unmounted and safely removed.

## Installer choices reach the saved build plan — 2026-10-08 (DR173)

Desktop drive selection now sets the serial-identified target used by the
reviewed installed-drive update, while protected drives are disabled. OS
selection updates the environment in the canonical Installer Plan, including
the active VM/container name. Adding or configuring an app updates the saved
build choices and app configuration. These are saved choices only: they do not
claim that the OS or app has been installed. The existing reviewed native
authorization and deployment workflow remains the only path that writes the
target. Browser integration proves the wiring with synthetic drives and
executor; no physical deployment is claimed. Full new-build execution,
multiple-workload composition, native boot, LAN/firewall, driver package and
retained overlay/data proof remain open under queue72/74/75/76/78.
See [DR173](design/decision-records/173-installer-desktop-build-plan-wiring.md).

## Tab-free Installer environment desktop — 2026-10-08 (DR172)

The additional desktop mode fills the browser with the active environment
picker and seven relevant setup groups in the vertical icon rail: applications,
OS, drive assignment, Proxmox, hardware, drivers and Advanced settings. Unrelated admin
and recovery links are kept out of this rail. The horizontal icon strip shows
the selected group's objects and includes a Setup group for all six setup
blocks. The main surface presents those six blocks for the active VM/container, and each environment has one settings modal that collects its related configuration. The default is named `testvm1` and is clearly marked as a setup draft, not a running VM.
Object Manager opens with all object types grouped together. Detailed
configuration is under Advanced settings. Applications available in the
catalog are marked available to add, not installed or runtime-tested. Drivers
remain visible but grayed out because no verified universal package exists.
The lower-left Edit control still switches between this desktop and Current
workspace. Drive configuration is labeled “Drive assignment,” not “Storage.”

Real Chromium/HTTP checks cover the tab-free rail, saved layout, setup icons,
group gestures, object settings/copy/move, and phone-width layout without
horizontal overflow. Drives and the privileged executor are synthetic, so this
proves browser behavior only. It does not prove PC401 installation, Proxmox
boot/network/firewall, driver installation, workload execution, or persistence.
Physical requirements remain queue72/74/75/76/78. See
[DR172](design/decision-records/172-tab-free-installer-environment.md).
Browser captures and the exact verification scope are in
[verification/172](verification/172/AUDIT.md).
DR171's screenshot-matched tab layout remains historical and is superseded for
the current desktop design.

## Desktop visibility correction — 2026-10-07 (DR170)

Fresh Installer layouts now show the requested Phone desktop & taskbar mode
with the bar expanded. Current workspace stays selectable. The new Installer
desktop menu opens /install-plan?display=desktop directly, including when the
old mode was saved. Browser mouse/touch checks and 100 focused regressions
passed with synthetic privileged execution. The actual read-only discovery
pipeline returned two drives and five apps. The live server was reloaded and
the desktop URL opened; the operator screen itself has not been captured or
accepted by the operator. No new physical deployment/boot proof is claimed.
See DR170; native/workload/driver acceptance remains in queue72/74/75/76/78.

## Additional Installer desktop display — 2026-10-07 (DR169)

Current workspace remains available. The additional Phone desktop & taskbar mode
has owner-scoped saved preferences, collapsible icon groups, swipe/hold controls,
VM/container configuration tabs, and full-page/split Object Manager. Right-click
Copy to / Move to carries validated shortcut settings between configured pages.
Actual Chromium/HTTP and mouse/touch verification passed with synthetic devices
and privileged executor; full unit suite 3454 passed, followed by 21 focused
checks of the final UI change. This does not establish native VM migration or
PC401 deployment/boot. Physical acceptance and generalized workload/driver
execution remain open. See DR169 and verification/169.

## Automatic Installer continuation and shortcut workspace — 2026-10-07 (DR168)

The Installer now prepares and reviews an authenticated exact-serial update
automatically, then dispatches through native PolicyKit. It presents grouped
application/OS shortcuts over a desktop background, uses the browser width,
and retains drag-and-drop and right-click settings. Configuration saves are
reported separately from installation. Browser integration passed with actual
Chromium/HTTP and synthetic drives/executor; no physical update or boot has been
verified. Unit regression results are recorded in verification/168.

The helper supports guarded growth of disposable BASELINE to 50 GiB while
preserving 16 GiB VG reserve. This is unit-tested, not executed on PC401.
Read-only observations still show its older 8 GiB allocation; PC601 is preserved.
Native privilege authorization may require the operator's OS prompt. General
Build/Rebuild, multiple workloads, broader distros/applications, driver profiles
and native boot/network/firewall/persistence proof remain open in
queue72/74/75/76/78. DR168 supersedes DR167's manual-flow/no-resize descriptions;
DR167's earlier 3441-pass suite remains historical.

## Resumption and hardware observation repair — 2026-10-07 (DR166)

DR165's completed virtual GUI acceptance remains valid; native physical cold
boot and web Build/Rebuild execution remain open. Stale pending-GUI entries
below and in the installer checklist now refer to that completed KVM proof.
REAL-006 rejects malformed/partial bus output instead of presenting it as empty
or complete. 66 focused tests passed against fakes; actual development-host
PCI/USB/network command output parsed successfully (45/25/5 devices), read-only
without fakes. Block parsing has no new physical verification. No drive write,
credential handling or boot occurred. See DR166 and verification/166 for full
regression results and remaining observation gaps.

## Restart authentication fix — 2026-10-04 (DR160)

Web reloads previously discarded login records, leaving stale browser cookies
that Restart host reported as "not authenticated". New merged-app logins use
private HMAC-authenticated SQLite records with hashed bearer tokens and survive
reload until their original expiry; logout revokes them. Expired restart requests
now offer Sign in on the same origin, without replaying the restart. Old lost
sessions require one fresh sign-in. Native Ubuntu confirmation remains required.
Temporary SQLite/HTTP tests passed; no actual host restart or drive action.
Full final unit suite: **3368 passed**, no skips/deselections/failures;
focused checks: **204 passed**. Chromium verified the expired-session sign-in
link against fixtures. Production reload PID1624321 serves login HTTP200
with same-origin policy. See verification/160. Actual native restart remains
unperformed, so PC401 boot acceptance (queue78) remains open.


## Ubuntu cache source and base verification — 2026-10-04 (DR159)

Installer Cache now offers a typed Ubuntu source acquisition/verification action
and authenticated link to its actual file. Native jobs require the mounted
INSTALLER_CACHE UUID/label, verify the publisher SHA256 and refuse damaged or
redirected files. Installer input preparation consumes that verified source;
VM preparation uses the same handler and checks imported-base SHA256 receipts.
Canonical's actual checksum metadata matches the existing source pin; detached
signatures remain unverified. Real qemu-img conversion/receipt/tamper refusal
and native Linux plain-directory cache refusal passed on disposable files.
HTTP/browser acquisition tests use fixtures, not a physical publisher download.
No target drive changed or guest booted. Other sources, package closure,
Build/Rebuild execution and final physical acceptance remain open in the
[checklist](design/installer-acceptance-checklist.md). Final full unit suite: **3364 passed**, none skipped or deselected; focused
affected checks: **140 passed**. Chromium source-control checks passed against
fixtures. Production web reloaded (PID1598679); login HTTP200 with same-origin
policy. Evidence: verification/159.


## Application restart — 2026-10-04 (DR158, awaiting login)

At the operator's request, the existing desktop browser opened Baseline Drive
Administration. It shows Log in on the checked loopback hostnames. Sign-in must
happen interactively; no operator credential or cookie was handled. The agent
has not submitted the Restart host action or issued a restart/native dialog.
After login, the authenticated application action requests Ubuntu confirmation.
PC401 boot tests remain pending until the host lifecycle step completes.

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

## Installer acceptance review — 2026-10-04 (DR158)

The seven installation outcomes remain incomplete. See
[installer acceptance checklist](design/installer-acceptance-checklist.md) for
completed components and every remaining step. The web Installer Plan now
prepares a saved code/configuration input bundle as a durable job and reports
missing publisher sources and target package closure. This is preparation,
not Build/Rebuild execution. The ISO now includes its required console check,
and the installed source resolver uses /opt/baseline-src. Actual repository
snapshot/integrity checks passed for 762 files; fixture Chromium and HTTP tests
are not physical installation evidence. Final full unit suite: **3352 passed**, no deselections, skips or failures;
focused installer/HTTP checks: **128 passed**. Chromium preparation interaction
passed against test fixtures. Production web reloaded (PID1576009); login
returned HTTP200 with same-origin policy. See verification/158.
No physical drives changed; native PC401 cold boot and queue78 remain open.


## Physical LAN throughput — 2026-10-04 (DR156)

Resolved the unmeasured-physical-LAN finding: actual TCP 5201 transfers through
Ethernet, the LAN/access point and Wi-Fi measured 189.4 Mbit/s Ethernet→Wi-Fi
and 138.2 Mbit/s Wi-Fi→Ethernet (five seconds each). Separate endpoint isolation
prevented local routing; hardware TX/RX counters corroborated the payload, and
an actual loopback control was rejected. No FakeRunner or remote credential.
This measures the same machine's two physical adapters through the network,
not separate-host workflow or wired-only capacity. All temporary resources were
independently observed removed; both links remain up. The earlier DR155 endpoint
is stopped. See DR156 and verification/156. Separate-device/browser tests and
PC401 installed Proxmox/native boot (DR146/queue78) remain open.

## Standard throughput port — 2026-10-04 (DR155)

Actual default-port server/client workflow passed on TCP 5201 without FakeRunner
in an isolated Linux namespace; measured traffic was virtual local, not physical
LAN. A temporary real host listener was observed at 10.0.0.231:5201, restricted
to 10.0.0.0/24, for one client or up to ten minutes. It is not a persistent
endpoint. Fresh discovery found no working peer among 253 private addresses.
DR156 subsequently measured the physical Ethernet/AP/Wi-Fi path; separate-host
workflow and PC401 boot (queue78) remain open.
See DR155 and verification/155. No production web reload or Proxmox change.

## Optional network diagnostics — 2026-10-04 (DR154)

Normal use does not require an iperf3 endpoint on port 5201 or a Proxmox
web endpoint on port 8006. Those ports were discovery defaults. Diagnostics
saves now persist options without running a test; firstboot skips active iperf3.
The separate authenticated Run network test action accepts a chosen peer/port.
Server runs verify the existing private-source firewall and an owned listener.

TDD and actual SQLite/HTTP/nftables/systemd/iperf3 checks passed without
FakeRunner, including a custom-port client measurement in an isolated Linux
network namespace. This increment proves the local workflow; DR156 adds physical
Ethernet/AP/Wi-Fi throughput. Successful browser active traffic and installed
Proxmox/native boot remain unverified.
PC401 mount recovery and boot proof remain important under DR146/queue78.
See DR154 and verification/154. The production web process was not reloaded.

## Verification continuation — 2026-10-04 (DR153)

Actual discovery checked 253 directly connected/private addresses for iperf3
and the public Proxmox version endpoint. No working standard-port endpoint
was found. DR156 subsequently measures the Ethernet/AP/Wi-Fi path using local
physical adapters; separate-host testing remains unverified. Read-only serial/PV/VG
inspection confirms PC401 root is still held by 23 mount namespaces; its
installed workflow cannot safely be boot-verified yet (DR146/queue78).
No physical writes, unmounts or reboot occurred in this continuation.

The next independent REAL-006 check found and fixed omission of MAC-less
network interfaces, including tailscale0. Real development-host checks now
match all five non-loopback interfaces, 45 PCI devices and driver bindings,
and 13 whole disks. No FakeRunner was used. Malformed output and unavailable
driver metadata handling remain open. See DR153 and verification/153.

## iperf3 diagnostic readiness — 2026-10-04 (DR152)

Server success now requires active service state and a listening TCP socket
owned by that service's MainPID. Each request owns a separate bounded,
single-use service; failed readiness attempts stop it and verify cleanup.
Actual systemd/ss/iperf3 checks on the development host passed for loopback
transfer, port conflict, listener exit, missing executable and invalid input.
No FakeRunner was used for this evidence. No host package was installed.
DR154 adds actual HTTP/settings-backend proof; DR156 measures the physical
Ethernet/AP/Wi-Fi path. Successful browser active traffic, separate-host testing
and Proxmox deployment remain unverified. See DR152 and
`tests/integration/verify_iperf3_runtime.py`. Other readiness tasks remain open.

## Configuration web UI — 2026-10-04 (DR149–151)

Master Config now aggregates current owner-backed settings, Admin groups, storage,
schedules and declared policies with search/filter. Settings and Admin reuse
their real save handlers. Installer and recipe drafts now persist per authenticated
user and appear in Master Config (DR150), explicitly not applied; editor changes
autosave and reopening restores them, with revision checks against stale edits. UI
contracts/local HTTP and isolated real Chromium checks passed; no physical
drive, guest driver load or real host setting change was verified in this increment.
Hardware now uses category sub-tabs, serial-based Drive Administration navigation,
observed installed package versions/module ownership and associated Installer Cache
entries (DR151). Real host package observation was read-only; browser hardware
inventory was an isolated fixture, not physical target verification.
Open web work is listed in `docs/design/configuration-web-checklist.md`.

## Selected PC401 installation — 2026-10-04 (DR146, in progress)

The current instruction is to write **one** SK hynix drive: PC401 serial
`MD89N41071210AP4E`. PC601 `FD01N6557110C271B` remains unchanged.
PC401's six filesystems were normally unmounted after root process-use checks.
A whole-drive compressed recovery image passed `qemu-img check`, complete raw
source comparison and independent SHA-256/image-size verification:
`/mnt/10TB/backup/baseline-recovery-20261004T095423Z-e228c4285b1047958cccbb164ec9ec6d`.
Read-only mounts with journal replay disabled found role indexes, a small seed
archive and Baseline design/source files, all preserved in that image. The
existing Baseline-only layout was adopted through the established identity
mechanism. Proxmox was then installed onto PC401 and observed booting into its
login screen under QEMU with only this physical drive attached to the guest.
The first launch failed at GTK initialization before installation; the tested
headless-monitor fix allowed the subsequent install and disk boot. This is
physical-drive boot under QEMU, not a native machine cold boot.
A single-drive profile reserves host,
all eight storage roles and growth on this measured 512110190592-byte drive.
All eight physical role LVs were created and mounted with unique filesystem
UUIDs; the UUID-based fstab, measured-capacity policy and root/PV/VG marker
were written to PC401. Its VG is now `baseline_1b75c1a556ee`, independently
verified by PV/VG UUID. Root is 32 GiB and swap 4 GiB. Proxmox's 64-GiB
maxvz budget creates 62 GiB minus 4 MiB of physical thin data after its two
metadata allocations; the host preflight now follows the upstream formula.
Boot files were regenerated after rename. Actual package installation succeeded
(diagnostics, Chromium/Cage, Podman, Node22 and Claude Code); deployment then
stopped because the offline source staging lacked automation assets. The
single resumable script now stages those assets and preserves the development
console during offline provisioning. Baseline was staged and enabled, and 22
files from the original roles were restored to persistent destinations with
per-file SHA-256 checks. The run stopped when LVM refused to close the target
root LV. `/proc/1224/mountinfo` identifies a mount under the host
`systemd-oomd` mount namespace; namespace-targeted normal unmount attempts still
fail. Both SK hynix drives share the same Realtek USB bridge `SiblingId`, and
UDisks refused PC401 safe power-off because PC601 `/dev/sdc2` is mounted. No
power-off occurred; neither drive was force-removed. Post-rename boot
verification remains pending.

The boot-only continuation was retried after changing namespace unmounts to
enter the recorded namespace with `nsenter` before calling ordinary `umount`.
The script still reports that PC401's root LV is mounted in PID 1224's
`systemd-oomd` namespace and stops before deactivating LVM or booting it. The
new command path passes its focused unit test, but physical unmount and
post-rename boot verification remain unverified.

After the GNOME Disks power-off dialog showed both drives and failed opening
PC401 `/dev/sdd` for `fsync` as busy, the user clarified neither drive was in
active use. The PC601 EFI mount was no longer present in the current namespace;
its Proxmox root and PC401 root LV remained mounted elsewhere. A retry that
checks each unique mount namespace and enters its root still could not normally
unmount PC401. It stopped before LVM deactivation or any power-off. These are
host-held namespace references, not evidence of user activity.

Read-only namespace diagnosis found nine stacked ext4 root mounts and 23
distinct mount namespaces referencing PC401. Their mountinfo entries identify
the target path, but path lookup from the helper and representative process
roots returns `ENOENT`; ordinary `umount2` therefore cannot address those
mounts from this execution context. Recovery-image and serial/LVM checks still
pass. No force/lazy unmount, LV deactivation, server restart, or power-off has
occurred. Clearing these stale mount trees safely requires a host-level
lifecycle action before PC401 can be boot-verified.

See [the remaining checklist](design/independent-drive-checklist.md).

The web application's shared navigation now has **Restart host** (DR148).
It requests Ubuntu/GNOME's standard confirmation dialog in the active local
desktop session and preserves inhibitor handling. Software/HTTP checks pass;
actual dialog display and host restart remain unverified. The ordinary restart
request was blocked by session inhibitors; the later inhibitor-override tool
request was cancelled, with no successful restart observed. PC401's subsequent
boot-only retry still found the root LV open across 45 process namespaces and
stopped before deactivation/boot. Drive completion remains open.

## Read-only storage inspection and audit continuation — 2026-10-04 (DR143)

Read-only physical metadata confirms PC601 serial `FD01N6557110C271B` is
currently `/dev/sdc`, whose 475.9 GiB third partition is the Proxmox LVM PV:
5 GiB `pve-root`, 2 GiB swap and a 28 GiB thin data pool are visible.
Follow-up read-only LVM inspection (DR145) reports 471309746176 bytes of
physical VG free space and 0.00 percent thin-pool data usage.
The Proxmox root was already mounted rw by the desktop and is 87% used.
The running development root is `/dev/nvme0n1p2`, not this Proxmox installation.
The other SK hynix (`MD89N41071210AP4E`, currently `/dev/sdd`) still has six
named ext4 Baseline partitions, including the two USER volumes, and no Proxmox
EFI/root layout. Whole-drive copying it onto PC601 would replace Proxmox's
layout. No copying, formatting, mounting or physical deployment occurred.

DR143 also rejects malformed VM identities/measurements and unrecognized
smartd config instead of fabricating defaults. Partial updates preserve
unrecognized config and return REAL-002 errors. Focused guarded tests:211 passed;
these code changes are synthetic-tested, not live Proxmox/hardware-verified.
See [DR143](design/decision-records/143-runtime-audit-and-drive-role-inspection.md).

## Current runtime audit — 2026-10-04 (DR142)

Production paths no longer present failed Proxmox/ethtool/package/hardware
observations as empty inventories or disabled settings. These now report
explicit errors through the affected TUI, HTTP, CLI and selective-update paths.
Selected handoff categories now map to a single config archive member (DR197);
physical archive/apply and isolation proof remain open. Iperf3 server submission originally reported readiness unverified; DR152 now
implements owned-listener readiness and verified cleanup with real host evidence.
Network preference no longer guesses a gateway and checks route mutation
failures. Firstboot reports unimplemented intent inspection as unknown.

See [the active runtime repair tasks](design/runtime-reality-tasks.md) for the
concrete REAL-001 through REAL-012 backlog and acceptance criteria, and
[DR142](design/decision-records/142-runtime-reality-audit.md) for this increment.
This is source/synthetic-test verification, not physical Proxmox or hardware
verification. Earlier runtime proof remains scoped to its original DR117/118
work; the shipped full installer/firstboot, application confinement, selective
handoff and recovery coverage are still open under rows72/74/75/76/77.

DR142 corrects DR141's DHCP finding: `dhcp` already existed in the settings
schema, so no extra schema extension was needed. Its unnecessary patch was
removed. DHCP retain/disable tests remain. The single-chain boot resolver now
refuses every branch/cycle instead of discarding unidentified ancestors; actual
Proxmox-root verification and multi-disk/ZFS support remain open.

DR139's claims about unavailable firewall/tether/iperf integrations predate
f5fede6, which connects those real mechanisms. Runtime readiness and physical
verification must still be demonstrated. Main/origin/main were f5fede6 at the
start of this audit; this increment has not been merged, pushed or deployed.

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

## Main integration and external AppData mapping (DR140)

Main was missing the installer framework; DR140 integrates the tested branch
and the scoped DR137 safety fixes. The authenticated editor now lists existing
unique ext4 AppData targets on enrolled drives and records explicit per-persona
serial/PARTUUID mappings. A six-volume Baseline drive can be retained when real
AppData volumes exist elsewhere. No user/cache-directory fallback, partitioning,
mount application or data migration is performed. Actual physical discovery
still refuses missing targets on this machine. Browser mapping/export tests use
synthetic disks; physical writes and full provisioning/firstboot remain unverified.
Other concurrent production audit work remains separate. See DR140,
verification/140 and INSTALLER_PLAN_WALKTHROUGH.md. Rows72/75/76 stay open.
## Independent single-drive installations (2026-10-04, DR145)

Each enrolled 512 GB drive is intended to hold a complete independent
installation with the same storage roles. The `single-drive` installer preset
and `baseline-install-plan single-drive SERIAL` now implement capacity budgeting
and compilation to boot-preserving LVM provisioning, also exposed in the web
editor. 201 focused tests passed against fakes and a local HTTP test server;
real drives were inspected read-only and remain unchanged.
Physical migration, first-boot stage execution, simultaneous LVM identity handling
and independent boot verification remain open under REAL-013 and rows 72/75/76.
The profile is not evidence that either current drive is a complete installation.

## Physical PC401 continuation (2026-10-04, DR146)

The earlier read-only status above is superseded by DR146 for PC401 only. The
selected drive `MD89N41071210AP4E` now has the Proxmox install, unique VG
`baseline_1b75c1a556ee`, all eight physical storage roles, deployed Baseline
services/packages, vanilla installer source in INSTALLER_CACHE, and 22
checksum-verified files restored from its verified recovery image. These are
real writes to PC401. PC601 `FD01N6557110C271B` was not modified.

PC401 has not yet passed post-rename boot verification. LVM reports its root LV
open because the mount appears in the host `systemd-oomd` mount namespace; the
script's normal unmount attempts do not release it. The prior QEMU login-screen
observation predates the VG rename and does not verify the current image. No
native cold boot or successful post-rename QEMU boot is claimed. The resumable
real-command entry point is `baseline/bin/baseline-independent-drive-install`;
it has a boot-only continuation to avoid repeating installation and restore.
The physical checklist records remaining work. DR147 adds the requirement that
one action choose Install/Build or Rebuild/Update from fresh drive analysis;
that UI/execution path is not implemented yet.

## Installation review repairs — DR161

Source downloads now use concurrent HTTP request handlers and a 30-second write
stall timeout. Driver application verifies the bound driver's sysfs owning module
matches the selected module; another existing binding cannot report success.
Focused installation tests: 126 passed, synthetic handlers/fake runners only.
No physical driver change, native cold boot or installed Proxmox proof. Remaining
sources, package closure, Build/Rebuild execution/journaling and physical acceptance
remain open in installer-acceptance-checklist.md under queue72/74/76/78.

## Installed-system readiness — DR162

Authenticated Installation readiness now reports mounted storage identity,
restriction and capacity checks, network address/gateway observations and required
Baseline/Proxmox unit states. Missing observations fail visibly. Firstboot no
longer treats omitted network facts as success. Provisioning stages the report.
66 focused unit tests passed using fake runners/direct handlers; no installed
Proxmox, real HTTP or physical cold-boot proof. Queue74/75/78 physical readiness,
portal/VT and final installation acceptance remain open.

## GUI/browser and Ubuntu configuration continuation — DR163

The Ubuntu GUI builder now carries locale, desktop and homepage configuration
through its cloud-init overlay and retained rebuild profile. Native Proxmox guest
verification checks effective settings/services without claiming a logged-in GUI
or browser rendering. Chromium's host kiosk profile is on APPDATA_ADMIN; startup
requires verified mounted storage and its Proxmox homepage service. Old installs
need the role/policy ready before the new kiosk gate passes.

164 focused tests passed (fake runners/direct handlers); actual qemu-img/qemu-io
and xorriso seed/rebuild checks passed on synthetic images. DR165 subsequently
completed current-source provisioning, both GUI/browser paths, configuration
verification and two retained-user-data rebuilds in a KVM clone with explicitly
read-only physical backing. Native physical cold boot remains open under
queue72/74/75/76/78. See DR163 for the earlier artifact checks and DR165 below
for the completed virtual acceptance.

## GUI startup continuation — DR164

The kiosk explicitly activates tty3 after its readiness gate; provision includes
kbd. Ubuntu Desktop's overlay autostarts Firefox after authenticated GUI login;
Server seeds omit it. 42 focused tests and native synthetic seed/rebuild checks
passed in DR164. DR165 subsequently verified actual host kiosk startup after
virtual restart and Ubuntu graphical login/Firefox rendering in an isolated
KVM clone. Native physical cold boot and broader integration remain open under
queue72/74/75/76/78.

## Current live GUI acceptance — DR165

Current-source provisioning and firstboot completed in a serial-validated KVM
clone of PC401 with explicitly read-only physical backing. The shipped
cage/Chromium kiosk rendered Proxmox and authenticated. After an orderly virtual
host powerdown/relaunch, storage, firstboot, web and kiosk services started
automatically and Chromium rendered Proxmox again.

Authenticated real web jobs acquired the pinned Canonical image and created a
Proxmox-managed Ubuntu Desktop with locale en_GB.UTF-8, configured homepage and
a separate retained home disk. Actual graphical login and Firefox rendering
passed. Two OS-overlay rebuilds retained the generated login, user document and
Firefox-created bookmark while removing the disposable OS marker. Final native
configuration verification passed; screenshots supply the separate GUI proof.
Firefox recovery and the disposable self-signed certificate were handled through
the normal browser UI.

Live defects fixed include stale firstboot network evidence, invisible persistence
bind mounts, threaded SQLite access, insufficient new-install BASELINE sizing,
stale Proxmox VG references and Firefox first-run/homepage policy verification.
New profiles reserve 50 GiB for BASELINE; legacy policies remain readable. VG
reconciliation validates the target serial and refuses unrelated or existing old
VGs. The clone's existing BASELINE expansion was confined to its disposable disk.

The full current unit suite passed **3412 tests**. See
[verification evidence](verification/165/README.md) and
[DR165](design/decision-records/165-live-gui-installation-continuation.md).
This establishes actual virtual GUI/browser/configuration/rebuild acceptance.
Physical native cold boot and the broader isolation/integration queue remain open;
no physical drive was written during this continuation.

## Self-contained all-script installer — DR245-248

`baseline/bin/baseline-allscript-install` builds an installer that carries everything its build needs and finishes the
installation on the target by itself, with no internet and nothing attached but the ISO. Stages: `preflight`, `recovery`,
`cache`, `install`, `firstboot`, `kiosk`; `--stage rehearse` runs the same installer end to end against a blank sparse disk
under KVM (no root, no physical drive).

- `cache` builds the drive's installer cache once (`baseline-build-offline-cache`): packages with all dependencies
  (provision.sh's, first-boot diagnostics, the applications' runtime, drivers: CPU microcode and Wi-Fi firmware), npm's cache for
  Claude Code, and the five applications prepared with `baseline-apps prepare` (VS Code, Spotify, Chrome, ChatGPT, Claude
  Desktop). It reads through earlier caches (`--seed`) and downloads only what is missing.
- `install` / `--stage rehearse` offer the cache and OS images (`--os-iso NAME`, repeatable) to the installer VM. The installed
  system's first boot (`baseline-first-boot-install`) lays out storage, copies the exact installer ISO and its expanded
  environment onto INSTALLER_CACHE, copies and verifies the offered OS images (registered as the Proxmox ISO storage
  `installer-cache`), and provisions from the carried repository.
- After CONFIRM, first boot installs its diagnostic tools from that repository when the network does not verify, commits, and the
  kiosk shows Proxmox. `baseline-network-retry.timer` then re-applies only the change that was confirmed, until it verifies.
- The drive's cache learns: packages apt downloads are kept in it (`LEARNED.json`), so a rebuild finds them there.
- Proofs on the offline rehearsal VM: `tests/integration/verify_os_open.py` (opens a carried OS through the web app's VM code)
  and `tests/integration/verify_apps_offline.py` (runtime and all five applications install offline and pass preflight).

The real PC401 run needs the operator's own `sudo` command and a drive cleared by the operator. Merge status with the
parallel effort: [parallel-effort-merge.md](design/parallel-effort-merge.md).
