> Imported 2026-10-11 from the parallel (Codex) effort, where this record is DR245. Numbered DR249 here so it does not collide with this branch's DR245-248. Other DR numbers inside the text refer to that effort's numbering.

# DR249 (parallel effort DR245): PC401 guarded installed-drive update completed

Date: 2026-10-10. Continues DR244 and DR167. PC401 serial
`<PC401 drive serial>` is the only update target; PC601 serial
`<PC601 drive serial>` remains preserved.

## Evidence

The authenticated current-source Installer ran on loopback port 8101. Its
serial-bound existing-installation update used the native PolicyKit path and
launched the real privileged `baseline-drive-update` helper as root. The helper
revalidated the selected serial, captured source, recovery image, PV/VG and
storage identities, and closed-volume state before deployment. It accepted the
verified recovery snapshot at
`/mnt/10TB/backup/baseline-recovery-20261004T095423Z-e228c4285b1047958cccbb164ec9ec6d`.

The durable update journal records:

- `state: updated` and `serial: <PC401 drive serial>`;
- `identity_source_recovery_and_retention_verified`;
- BASELINE growth by 45,097,156,608 bytes to 53,687,091,200 bytes (50 GiB),
  leaving 65,435,336,704 bytes free in the VG and preserving the 16 GiB reserve;
- `current_baseline_provisioned`, `boot_files_refreshed`, and
  `cleanup_finished`;
- `boot_verified: false`.

The Installer displayed deployment complete and explicitly left physical boot
and runtime checks pending. No FakeRunner/FakeProc or synthetic device result
was used for the deployment. After completion, visible host mount tables had no
PC401/VG references. An unprivileged LVM query could not inspect
`/dev/mapper/control` (root-only), so current host LVM-use state is not claimed
from that query. PC601 was not selected or written.

## Result and remaining work

PC401 is prepared for physical boot testing on the other machine. The update
proves physical deployment and boot-file refresh only; it does not prove a
successful boot, Proxmox GUI, working network or internet, firewall behavior,
VM/container startup, application launch, or overlay/user-data persistence.
Perform those tests on the target machine using the distinct test network
allocation. Do not claim PC401 ready for full comparison until those checks
pass. v0.2 queue rows 72 and 78 and the independent-drive checklist remain open.

`docs/INSTALL.md` and the living queue/checklist/handoff were updated to reflect
this result. DR244 and older decision records remain append-only history.
