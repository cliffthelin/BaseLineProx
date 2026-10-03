# DR134: Reusable Ansible tasks, compatibility evidence and installer guidance

Date: 2026-10-03. Accepted incremental implementation. Extends DR133; no
physical deployment or complete replacement-device recovery claim.

## Decision and actual implementation

Use established Ansible Core roles/argument_specs and Ansible Runner as the
executor. Two real registered roles classify native prerequisites (root) and
locked DEB/tar application suites (named administrator). baseline-tasker supplies
catalog, autofilled canonical playbook, strict validation, execution and SQLite
expected/observed compatibility history. The dedicated store holds execution
proof, not a competing settings system; general-registry/web-job integration is
still open. AI can author reviewed recipes from components; it is not runtime.

Protected backend fingerprints verify actual target code, root ownership and
non-writable parents before invoking the CLI. Evidence is pinned to component
revision, OS, application version/source SHA, instance and capability; current
proof excludes old revisions. Unknown tasks/roles, executable Jinja variables,
overlapping/traversing paths and stale code refuse. Fake runners stay unit-test;
check mode does not prove installation. Failed runs never promote partial results.
Application package output now goes to stderr so CLI results remain JSON.
Completed suites inspect private identities and main executable fingerprints.
Legacy receipts without those hashes explicitly need rebuilding; they do not
silently gain new verification. Whole payload integrity/dependencies are not locked.

## Verification

TDD RED was confirmed before implementing the tasker, source trust, target-OS
check, CLI output fix, path/Jinja boundaries and deployment staging. Final full
suite: 2993 unit tests passed in149.88s; bash syntax and git diff whitespace pass.
These are unit tests, not physical proof.

Actual Ansible Core2.21.4 / Runner2.4.3 executed both registered roles in Debian13.7
and Ubuntu24.04.5 disposable KVM guests. Debian records prerequisites plus five
apps; Ubuntu records prerequisites plus Chrome. Both final repeats changed=0.
The target code matched all five fingerprints. Native app observations cover
materialization, not GUI/authentication/recovery. Some dependency names are APT
aliases fulfilled by t64 packages and have an empty dpkg-query version; this
record does not claim each alias is an independently installed package.
DR133 separately proves all five native GUI windows on both OSes and the retained
Debian home across clean OS-root replacement. No operator accounts were used.
See verification/134/native-tasker-summary.json for reviewed scoped evidence.

Private Runner artifacts preserve command-not-found, test-key permission and
APT-output parse failures from development. They are failed rows, not success.
The actual source drive remained read-only; all root/data changes were inside
virtual images. Physical PC601/PC401 drives were not written.

## Installer and walkthrough

boot/provision.sh stages tasker/app CLI/modules, automation and docs; ISO builder
carries automation/docs alongside source. The walkthrough documents source
ownership, private inventory, capture/config-only compose, editable task autofill,
execution, launch/grants and limitations. It does not impersonate a full hardware
installer. A real remastered ISO reached the Proxmox9.2 boot menu in isolated KVM with
no disks or network. Independent xorriso extraction matched seven critical
source/role/walkthrough files. The source ISO SHA256 matched the publisher and
gpgv verified both official release-key signatures (Trixie24B30F06ECC1836A4E5EFECBA7BCD1420BFE778E,
BookwormF4E136C67CDCE41AE6DE6FC81140AF8F639E0C39). The first local proof wrapper
failed serializing a Path after remastering; independent content/boot checks
confirmed that output. Final packaging uses an explicit serialization handler.
The artifact is a manual Proxmox installer plus Baseline source, roles and docs;
it contains no unattended answer/password hash and does not automatically run
Baseline provisioning. Existing HTTP ephemeral-answer installation remains a
separate flow. No install was attempted in this boot-only test. The public
verification manifest identifies the final ISO checksum; the ISO stays local.

## Open work and historical correction

Rows72/74/75/76 remain partial; rows59/60 and77 recovery remain open. Hardware
volume autofill/apply, full current provisioning/firstboot, ordinary networking,
all-five Ubuntu tasker observations, new OS/media adapters, richer native prefs,
full source/dependency locks/quarantine, phone-style identities/display/network,
durable app jobs/restart reconciliation and independent encrypted restore remain.
Multiple-host capability completeness is not guaranteed by the current journal.
No earlier decision record is rewritten. INSTALL, remaining-work queue and
handoff are updated in place: previously missing ISO/app staging now exists in
source, while physical/end-to-end provisioning remains unverified.

Final ISO boot verification used KVM CPU host, one vCPU, 2048MiB, no network or
target disks and displayed the Proxmox menu. An earlier final-artifact attempt
with QEMU default CPU/two vCPUs remained black in firmware; cause undiagnosed,
not a passing boot. Final extraction matched all467 staged files. The build
snapshot predates these final verification notes/manifest; those are published
beside the artifact to avoid circular self-checksums.
