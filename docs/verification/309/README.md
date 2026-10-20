# PC401 → PC601 port assessment

Use PC601's newer architecture as the base. My PC401 build contributes useful
failure handling and acceptance methods, rather than a replacement architecture.

| Concept | PC401 candidate | Current PC601 source | Recommendation |
| --- | --- | --- | --- |
| Rebuildable substrate and vanilla installer cache | Same role model | Same, with newer OS bases | Keep PC601 |
| Persistent user/app data beneath disposable sessions | Local VM/overlay paths | Extended to Kasm's dedicated VM and workspace profiles | Keep PC601's expansion |
| Phone-style launcher/shared settings | Earlier implementation | Newer schema, including host and guest swap | Port only unmounted-read errors |
| Host database migration | Pending-move/collision handling; no live-service guard in the older PC401 tree | Newer live-service quiescence guard; unchecked move results | Combine both safeguards |
| VG/boot repair | Pending transaction and restartable boot regeneration | Basic rename/rewrite | Port transaction/retry protection |
| Networking | Failed-command diagnostics and exclusive backup creation | Newer NIC negotiation/retry already shared | Port only diagnostics/backups |
| Formatting/update safety | Stronger serial/whole-disk and lane exclusions | Earlier guard | Port with PC601's own lane identity |

Priority order: migration correctness, boot repair, drive safety, settings
truthfulness, then network diagnostics/backup preservation. These are absent
from the current PC601 source inspected at `b4e41ec`, even though it contains
the newer functional features.

## Concrete compatibility work

The isolated candidate preserves the exact PC601 installer UUID
`4af8c95a-1c9b-437a-a306-c53855d4077f` and therefore protects physical PC401.
The port never copies `baseline/INSTALLER_UUID` from Codex's branch. The
self-installer passes its already-validated serial to the stronger guard.
New guard/update tests are adjusted for the destination lane rather than
assuming PC401 is the target.

The persistence helper is inserted alongside `QUIESCE_BEFORE_MOVE`, not
copied as an entire old file. The running-service check executes even when a
destination directory already exists if a pending migration record remains.
Both existing quiescence tests and the added retry test pass. Do not cherry-pick
the complete original `ea3a658` source file over PC601's newer implementation.

Similarly, the settings port changes only `read_layer`; it retains
`swap_mb`, `host_swap_gib`, `host_swap_kind`, and the exclusion of host-only
settings from guest settings. Existing swap tests pass. Byte comparisons for
the preserved identity/architecture are in `preserved-pc601-components.json`.

## What was actually tested

- 11 selected cases fail on unmodified PC601 (missing journal/helper, missing
  update-lane exclusion, and unmounted settings accepted).
- The pending-migration retry regression also fails on unmodified PC601,
  demonstrating the guard integration needed for this port.
- Combined candidate: **308 focused tests passed**. Scope includes real
  temporary-file moves, pure parsing/policy, and injected unit commands. No
  destructive hardware commands ran.
- No new QEMU boot or physical PC601 verification was performed for this
  comparison. Previous PC401 QEMU helper/HTTP results are not relabelled as
  destination-PC601 acceptance.

The latest shared physical-target PC601 install log/progress is Oct 13 and
records kiosk acceptance/QEMU exit 0. Current source is later; DR260 records
Kasm on a nested virtual Proxmox host and explicitly distinguishes it from
native hardware. Installed disk contents were not read in this review.

## Review and next validation

Fetch `codex/pc601-backport-review` from the isolated checkout and inspect its
single candidate diff over `b4e41ec`. It changes eight production modules and
their regressions, with no Kasm, OS-base, role policy, Proxmox service drop-in
or installer identity changes. The report/evidence is part of the review commit.

Before deployment: check additional formatting/update callers against the
stronger serial guard; run the relevant full suite where sockets are available;
then use a disposable installed Proxmox guest to test interrupted VG repair and
reboot, partial directory migration, collision refusal, and a retry while the
database service is active. No full-branch merge or replacement disk image is
recommended. Queue72/74/75/76/78 remain open; physical drives are unchanged.

Caller checks also caught the two Drive Administration paths needing the freshly validated serial. Those calls are included, with destination-lane data-protection fixtures. The complete self-installer/data-protection subset now passes 50 tests alongside the 258 core tests. The missing-serial regression now verifies the earlier refusal and absence of workspace/QEMU creation.
