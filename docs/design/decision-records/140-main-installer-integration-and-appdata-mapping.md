# DR140: Main integration and explicit AppData mapping

Date: 2026-10-03. User requested confirmation on main and implementation if absent.

## Main status and scope

Verified GitHub main0391f347ba84a2e57403e4249200d326bce7383c lacked
baseline_web.py, install_plan.py, install_plan_page.py and INSTALL.md. It was
an ancestor of the tested installer branch,232 commits behind3dd98f9. This
integration therefore carries that existing framework, not just a standalone
page copied into an incompatible old tree. It also includes the specific DR137
drive-safety fixes required for main readiness. Other concurrent production
audit/dependency changes (including DR139) are excluded and remain separate
uncommitted work; this is not a claim all historical operations are real.

## AppData implementation

Optional storage.appdata maps personas to enrolled drive serial and GPT PARTUUID.
The read-only editor lists only existing ext4 APPDATA_<PERSONA> volumes with
unique identities. Applying a mapping uses fresh discovery and copies the plan.
External AppData can satisfy the per-persona requirement while retaining the
six-volume Baseline disk. Core/user/cache requirements remain. A disk containing
only AppData is excluded from Baseline-role autofill, preventing false ambiguity.
Compiled mount descriptors include expected serial, PARTUUID and persona-specific
mountpoint/options; explicit local overrides do not duplicate destinations.

Wrong persona/labels, user/cache partitions, malformed GUIDs, unknown enrollment,
cloned or replaced partitions, wrong filesystems and layout-stage mappings refuse.
There is no fallback to a USER directory or disposable/cache data. Mapping does
not create a volume, change fstab, migrate data or execute installation. Existing
no-mapping plans remain supported with dedicated volumes on Baseline.

## Prerequisite review fixes

Before applying DR137 fixes, its probes were rerun on3dd98f9:24 failed,1 passed.
The scoped fixes preserve the confirmed serial through layout and revalidate
before destructive command boundaries/stamping; refuse unknown boot identity;
leave ambiguous drive roles unset; require valid/distinct retained GUIDs; and
reject cloned PARTUUIDs across the complete listing. No physical write verified
these gates; command-boundary checks are not atomic hotplug reservations.
The prior DR136/137 decision records and evidence remain historical. Publication
and main integration here supersede their earlier no-merge/no-push status.

## Verification

TDD confirmed RED before external mapping, AppData-only autofill filtering,
web mapping and discoverable-target selection. Actual headless Chromium against
loopback HTTP exercised two external mappings, stage preview, export roundtrip
and refusal of an unenrolled target. Drives in that browser test were synthetic.
Separate real physical metadata discovery with this source found the two known
SK hynix drives, kept/retained them and refused missing AppData volumes. No
physical partition, mount, migration, credential rotation or installation occurred.
Final isolated full suite:3136 passed in125.92s, implementation20c193f. The
updated manual ISO matched497 staged files on extraction and booted to the
actual Proxmox menu in isolated KVM (CPU host/one vCPU, no network/target disks).
Its publisher source hash and both release signatures were freshly verified.
Final verification notes/manifest live outside the artifact snapshot.
Installer-artifact results are in verification/140.

## Open work and current-document correction

Rows72/75/76 remain partial: create/provision AppData volumes/containers, migrate
private state with retained identity, apply validated mounts and attach them to
guests, durable stage jobs/restart reconciliation and full provisioning/firstboot.
Independent encrypted replacement-device restore remains77/59/60. The actual
six-volume layout still needs real AppData targets; mapping software does not
make them exist. INSTALL, walkthrough and queue now describe optional external
AppData rather than treating repartitioning Baseline as the only solution.
The artifact is manual Proxmox installer/source packaging, not an unattended
answer or proof of completed installation. Main publication is verified by
remote ref after tests; root checkout's unrelated uncommitted work is preserved.

Scope clarification: DR137's backup test-capacity and BotEnrollDrive prose
cleanup are not included here; only the tested drive/plan guards and their
regressions were carried into main. Other production audit fixes remain separate.
