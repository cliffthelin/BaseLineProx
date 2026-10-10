# DR144: Configurable locations, predefined storage roles

Date: 2026-10-04. Operator requires settings to determine where data is read
and written. Install sources, overlays and retained data keep predefined
roles. If the 512 GB drives cannot fit, evaluate slower drives and reassess
what each holds. This supersedes assumptions that all roles must stay there.

The common role mapping must cover vanilla sources, built templates,
disposable overlays or standalone OS disks, retained user data, retained app
data and staging. Changing locations does not change retention or isolation.
Cache sources remain structurally separate from protected user data. Both
reads and writes use the mapping; source searches may have explicit multiple
locations, while mutable state has an explicit writable target.

Resolve enrolled targets by serial/PARTUUID or validated Proxmox storage and
backing identity. Missing or unsuitable targets must produce an error, never
silently fall back to the root filesystem. Check measured available space,
requested allocation, configured growth headroom and migration staging;
distinguish thin logical allocation from actual pool capacity. Unknown space
or performance remains unknown rather than inferred from device size.

Explain existing occupants and capacity costs when recommending relocation.
Consider cold install sources and infrequently used templates first, then
assess active overlays and retained data by workload. Validate slower targets'
capacity, filesystem and runtime compatibility. Preserve all role semantics.

Populated-location changes need a recoverable migration: quiesce writers,
copy, verify, switch mappings, verify actual workload reads/writes and retain
the old copy until validation succeeds. Do not automatically format or delete
existing data to satisfy capacity. A saved setting is not migration proof.

Existing distro_containers.py cache/OS choices and install_plan.py external
AppData overrides are partial mechanisms. A common capacity-aware settings
policy and migration transaction are not implemented by this documentation
increment. REAL-013 tracks implementation under queue rows 72/75/76.
Acceptance requires undersized fast storage, suitable slower storage, missing
targets, unknown capacity, thin-pool constraints and interrupted migration
without retained-data loss. Failing tests precede implementation; synthetic
checks and real workload verification remain separate claims.

No production code, physical devices or credentials were changed here.
