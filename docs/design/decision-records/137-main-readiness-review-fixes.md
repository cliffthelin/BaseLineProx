# DR137: Fix all five main-readiness review findings

Date: 2026-10-03. Implements the operator's request to fix each DR136 finding.
Verification is against fakes and loopback HTTP only, not physical hardware or
QEMU. No physical drives were discovered, enrolled, formatted, mounted or
booted. No real operator credentials were handled. No merge or push occurred.

## Decisions and implementation

### F1: preserve the exact confirmed serial during layout

`perform_action` passes the validated serial internally to the layout action
only after verifying web origin and HITL authorization. It is not a new
caller-controlled action parameter and does not alter the signed request.
Layout requires this managed serial and passes it to `baseline_drive_layout.apply`.
The helper binds its initial validated identity and revalidates serial, path
and size before every wipe/GPT/mkfs command. Layout checks the serial again
before the installer-identity stamp. A replacement is refused even when it is
another allowed disk. No kernel-assigned path is treated as durable identity.

The regression originally formatted a fake unenrolled replacement. Both that
case and replacement by an allowed disk now refuse before any write. A
replacement immediately after the first fake wipe stops before GPT erasure.
These checks detect changes at command boundaries; they are not an atomic
kernel device reservation. Hotplug between a check and command execution and
real-hardware behavior remain unverified; do not claim those races are eliminated.

### F2: refuse indeterminate boot identity

`validate_target_device` now refuses when `get_boot_device_serial` cannot
establish a nonempty identity. Empty/ambiguous root sources, non-device roots,
multiple immediate parents, and missing/blank boot serials do not disable
boot exclusion. Install-plan discovery also refuses unknown boot identity.
The existing resolver is deliberately conservative: unsupported live/overlay
and complex root topology require a supported identity resolver before use,
not an override that skips this guard.

Existing self-installer success fixtures omitted the boot serial and thus
relied on the old fail-open behavior. They now provide an explicit synthetic
boot serial. Their assertions remain intact. A separate test confirms that
unknown boot identity refuses before acquisition or install commands.

### F3: leave ambiguous drive roles unset

Autofill distinguishes no existing candidate from multiple existing candidates.
An empty disk never replaces an ambiguous set of installed Proxmox disks.
Listing order no longer assigns multiple empty disks to destructive roles.
Only one empty disk with exactly one missing role can be autofilled; two empty
disks or one disk eligible for both missing roles require explicit choices.
The plan's notes explain the unresolved choices.

The former test expecting automatic assignment of two blank disks now verifies
that compilation refuses until the operator explicitly chooses their roles,
then asserts the same valid install/layout behavior. This is the reviewed design
change, not an assertion weakened to hide a failure. The layout compilation
test uses an existing Proxmox disk plus one empty Baseline disk to exercise
the unambiguous positive case.

### F4: validate retained partition identities

Retention requires nonempty, syntactically valid GPT partition GUIDs. Names
must be distinct in both the plan and the selected disk. Missing/malformed
identities, nonexistent names and duplicate names cannot produce mounts.
GUID matching is case-insensitive; trailing control characters do not pass
the full-match check. No `PARTUUID=None` fstab output can compile.

### F5: reject cloned identities across the whole listing

Discovery counts valid PARTUUIDs across all partition nodes in the already-read
`lsblk` tree before filtering candidate drives. This covers boot, unenrolled,
unidentified and non-disk roots without issuing extra probes or exposing their
volume contents in the picker. Names deduplicate repeated nodes in multi-parent
trees. Discovery returns a normalized GUID-to-partition-count map.

Validation requires each retained identity to occur exactly once. A saved
plan cannot compile if another disk or partition carries the same GUID, even
with a different disk serial or UUID letter case. A discovery result without
the count evidence cannot establish uniqueness and cannot authorize retained
mount output. This remains planning only; no fstab lines are applied.

### Deterministic backup tests and review cleanup

`test_guest_backup.py` now gives its fake backup destination controlled capacity,
as the other off-drive tests already do. A dedicated low-capacity test confirms
that real production space checks reject the backup before vzdump or set
creation. No production backup code, assertion or required test was removed,
weakened or skipped.

The new BotEnrollDrive description's whitespace/garbled sentence is corrected.
Its instructions now explicitly stop when the still-unimplemented browser
enrollment controls are absent; no fictional usable form is claimed.

## Verification and evidence

The original six failing review probes are preserved in DR136's evidence.
Added adversarial cases were confirmed RED before their implementation changes.
The complete current regression file was also run on an isolated `df4a84a`
source snapshot: **24 failed, 1 passed**. That positive test ensures repeated
sightings of one partition do not create a false collision. The inherited
backup tests were separately reconfirmed RED before adding fake capacity:
**6 failed, 7 passed**. Source under test was never rolled back in the working tree.

Focused guarded verification after the five fixes and backup fixture change:
**254 passed**. Self-installer and review regressions after correcting the
boot fixtures: **50 passed**. The first full run caught the 14 success tests
whose fake boot identities were absent (3,099 passes); this failure and its
fixture-only correction are recorded rather than omitted.

Final full guarded suite: **3,114 passed in 110.12 seconds**, no failures or
skips. The full suite and deployment-check output are retained in
`docs/verification/137/full-suite-green.txt` and `deployment-check.txt`.
`bash -n boot/provision.sh` and working-tree `git diff --check` pass.
Full HTTP integration needs loopback sockets, so the existing approved
outside-sandbox unit command was used with the autouse hardware guard active.
Hardware/VM/mount/privilege commands remain fake; these results do not prove
a physical install or device isolation under hotplug.

## Current status and remaining work

F1–F5 and the inherited test-capacity issue are addressed in the local working
tree. This record supersedes DR136's unresolved status for these findings and
DR135's unqualified uniqueness/guard claims; both older records remain history.
INSTALL.md and the v0.2 queue are updated in place for the next session.

Rows 55/65/67's reviewed behavior is restored in fake-only tests; physical
validation remains open. Rows 72/75/76 still need runtime stage orchestration,
PARTUUID mount application, the web editor/enrollment UI and ISO firstboot
integration. No real-drive discovery has been newly verified. The inherited
Guardian tree and remaining 230-commit payload have not received an exhaustive
review or Rust/package/runtime validation in this remediation. These fixes
alone do not certify the entire merge as production-ready.

Changes remain local and uncommitted. Main and remote branches are unchanged;
the two scratch folders remain excluded from any publication payload.
