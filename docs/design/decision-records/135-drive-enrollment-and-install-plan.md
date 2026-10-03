# DR135: Deliberate drive enrollment and the installer's install plan

Date: 2026-10-03. Accepted incremental implementation of queue row 72/76's
"installer integration" step 1 (discover, autofill, connect). Extends row 55.
Unit-tested against fakes only. Nothing was run against real hardware, and no
provisioning stage is executed by anything added here.

## Context

DR134 left the ISO as a manual Proxmox installer that carries Baseline's
source. The pieces existed (the serial-checked safety gate, drive_guard's
installer UUIDs, the HTTP answer flow, `baseline_drive_layout`, Ubuntu
environment creation, tasker autofill), but nothing discovered the drives
present and turned them into one editable set of choices.

Discovery had a direct conflict. Row 55 (2026-10-01, "this can't have any
effect outside of the SK hynix") enforces `drive_admin.ALLOWED_TARGET_SERIALS`,
which hardcodes this machine's two serials. INSTALL.md says hardware changes
between installs. Asked directly on 2026-10-03, the operator chose
**deliberate enrollment**: the installer may list other drives read-only, but
a drive becomes a target only after explicit enrollment with a typed serial
confirmation. Row 55's own earlier note proposed "select-from-detected plus
the root password, never typed". The drive is still selected from the detected
list (never a typed path); the typed serial is an added confirmation, per the
2026-10-03 answer.

## Decision and implementation

**Enrollment** (`drive_enrollment.py`, `drive_admin.enroll_drive`):
- `drive_admin.allowed_target_serials()` = the SK hynix set plus enrolled
  serials. It is now the one source of the set for the picker and for
  `resolve_target`. Registry GLOBAL scope, read-only reads; an unreadable store
  admits nothing.
- `enroll_drive` is a normal Drive Administration action: web-origin proof,
  human confirmation every time, and listed in `hitl.NEVER_PRE_APPROVED`. Its
  drive is validated by `validate_target_device` with
  `expected_serial=<typed serial>` instead of the allowlist: non-boot, block
  device, at least 50 GB, and serial exactly as typed. A drive reporting no
  serial cannot be enrolled.
- Enrollment writes nothing to the drive. Formatting is still governed by
  drive_guard (data without an installer UUID is never formatted) and the
  24 h backup gate.
- `list_enrollable_drives` reads only the existing whole-system `lsblk -d`
  listing. It never probes partitions or volume groups of unenrolled drives.
- `offdrive_backup.resolve_destination` also refuses enrolled drives as backup
  destinations, so a managed drive is never its own "separate" backup.
- Corrected drift: drive_admin's module docstring still described the pre-row-55
  "selectable, never restricted" design.

**Install plan** (`install_plan.py`, `baseline-install-plan`):
- `discover` parses one read-only `lsblk -J -b` listing. It identifies drives
  by serial (the kernel name only as `path_now`), classifies each as
  empty / baseline / proxmox / data, and identifies Baseline volumes by GPT
  partition name (legacy names mapped) plus PARTUUID. The boot drive is
  omitted, unenrolled drives are listed by serial/model/size only, and drives
  without a serial are only counted.
- `autofill` keeps an existing Proxmox drive or installs onto an empty one,
  and retains a Baseline drive PARTUUID by PARTUUID or lays out an empty one.
  It defaults OS (Ubuntu 24.04 desktop) and all five apps with tasker's paths.
  It never selects a data drive and never guesses between two candidates;
  `notes` says why.
- `validate` checks edits against fresh discovery and reports every problem.
  It refuses paths in place of serials, and refuses unenrolled or absent
  drives, one drive in both roles, installing over data or mounted drives,
  and retaining PARTUUIDs that are no longer on the drive (a swapped or
  re-laid-out drive is caught). Laying out over Baseline volumes needs an
  explicit `erase_existing: true` and an installer UUID. Missing volumes point
  to `repair`. Personas must fit the 16-character ext4 label limit. App paths
  and account use tasker's own checks (extracted as
  `tasker.validate_task_storage`).
- `compile_plan` emits the parameters existing stages already take:
  `build_self_installer {expected_serial}`, `lay_out_baseline_drive` by serial,
  `ubuntu_environment.create` name/desktop/base, and tasker
  cache/generation-root/data. Retained volumes compile to `PARTUUID=` fstab
  lines with each volume's own mount options. `executed: false` and a
  `not_yet_connected` list are always present.

Why PARTUUID rather than LABEL: filesystem labels are not unique. A second
drive laid out by Baseline (a clone or a replacement) carries identical labels,
so `LABEL=` mounts (`persist_bind_mounts` today) are ambiguous. A PARTUUID
names one partition on one drive.

## Verification

TDD RED was confirmed before each part: enrollment, hitl listing,
backup-destination refusal, install plan, CLI. New tests: 25 enrollment,
63 install plan, 1 backup. Final full suite: 3081 passed, 6 failed. The 6 are
`test_guest_backup.py`, which fail identically on the unmodified tree because
they read this machine's real free space ("31 GiB free, about 44 GiB needed").
They are pre-existing and environment-dependent, not caused by this change.
`provision.sh` stages the two modules and the CLI, and its dependency check
passes. `bash -n` and `git diff --check` pass.

Not verified on real hardware. `lsblk` returns nothing inside this session's
sandbox, so read-only discovery against the actual drives was not run. That
is a sandbox restriction, not evidence about the hardware. No drive was
enrolled, written or mounted. No physical drive was touched.

## Open work

- Running the compiled stages as one confirmed, resumable job (row 75's
  workload jobs). Today each stage is still started separately.
- Writing the compiled PARTUUID mounts in place of `persist_bind_mounts`'
  LABEL mounts.
- A web page for enrollment (the picker still lists only allowed drives) and
  for editing the plan.
- Un-enrollment.
- Custom personas for `lay_out_baseline_drive`.
- OSes other than Ubuntu 24.04.
- The ISO's own first-boot path invoking the plan.
- Real-hardware discovery on this machine:
  `baseline/bin/baseline-install-plan autofill`.

No earlier decision record is rewritten. Row 55's restriction stands, extended
by enrollment.
