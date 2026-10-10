# DR145: Independent installations use the same single-drive profile

Date: 2026-10-04. Partially implemented; physical conversion and boot verification remain open.

The operator clarified that each 512 GB drive must contain a complete,
independently bootable installation. This supersedes any interpretation of
DR144 in which the two drives must cooperate to provide one installation.
Identical roles and sizing do not mean cloned disk, filesystem or LVM identities.

The selectable `single-drive` installer preset reserves 32 GiB host root,
64 GiB disposable OS pool, 4 GiB swap and a 2 GiB boot/metadata budget.
The capacity policy budgets all eight existing data roles, 20 percent growth
headroom and the existing 1 GiB safety allowance. Measured role requirements
can raise role minimums; oversized requirements are refused, never shrunk to
claim a fit. Without supplied measurements, the result explicitly describes
role minimums, not a proven workload fit. Migration staging is an additional
budget. Sources remain vanilla and structurally separate; user and application
data remain persistent; SESSION_TEMP remains quarantine.

The web editor and `baseline-install-plan single-drive SERIAL` produce an explicit proposal
using one enrolled serial for boot and data. Compilation selects the preset
and passes planned sizes and the reserve to the existing LVM provisioning
helper instead of the data-only GPT layout. The real installer checks measured
target capacity before workspace creation or credential generation when these
preset sizes are selected. The helper checks actual physical VG free space,
counts only missing LVs and refuses existing LVs smaller than the profile.
It does not resize existing volumes or wipe boot partitions.

Verification: 201 focused tests passed against fakes and a local HTTP test server after confirmed
failing tests. Real hardware was inspected read-only: both enrolled SK hynix
drives report 512110190592 bytes. PC601 has an existing Proxmox installation
with 5 GiB root, 28 GiB thin pool and 471309746176 bytes of VG free space;
PC401 has six mounted data-only GPT partitions, each reporting roughly
2 MiB used apart from SUBSTRATE (roughly 0.3 MiB). These are observations,
not migration, recovery or independent-boot proof. Neither drive was changed.

REAL-013 and installer queue rows 72/75/76 remain open: persisted measured
placement policy, selected-root/VG backing-serial enforcement in the stage
executor, recoverable migration of populated targets, handling both installations'
LVM identities when attached together, actual first-boot provisioning and boot
tests with the other drive absent. Slower-storage suitability must be measured
before moving cold sources/templates; no such move or performance proof occurred.

DR144 remains historical. INSTALL and REAL-013 are updated with this partial
implementation and the physical verification boundary; no earlier hardware
installation claim is upgraded by these tests.
