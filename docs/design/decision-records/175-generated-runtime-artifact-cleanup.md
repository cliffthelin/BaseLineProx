# DR175 — Remove completed generated runtime artifacts

2026-10-08. Cleanup follow-up to DR133, DR140, DR146, DR165, and DR174.

The six `.runtime-proof*` directories had about 1.06 TiB apparent size but
about 100 GiB of allocated blocks. Sparse raw/QCOW2 images explain the
difference. `.runtime-proof173` holds current installer progress. The external
recovery directory on `/mnt/10TB` had a stale
`INCOMPLETE.json` older than its complete manifest. Its image SHA-256 matched
the manifest and `qemu-img compare` confirmed its contents are identical to
the local raw copy. Recovery verification uses the complete manifest plus
image hash/format and removes stale markers after future successful snapshots.

Removed completed scratch/build data with published evidence retained:

- `.runtime-proof133/tests-full-suite`, an old pytest basetemp.
- `.runtime-proof140`, the completed DR140 local run directory, after its hash,
  source signatures, extracted-file manifest, screenshots, and boot evidence
  were retained in `docs/verification/140`.
- `.runtime-proof146/a`, a failed disposable QEMU attempt. Its log records
  failure before launch, and `disk.raw` was a sparse zero target (512 GiB
  apparent, 4 KiB allocated).
- `.runtime-proof146/physical-pc401-20261004T104517Z`, the earlier failed
  installer attempt. Its large ISOs and ordinary scratch were removed. A 4.8 MB
  root-owned staged package tree remains: normal and approved elevated `rm -rf`
  both returned `EPERM`/permission denied. No chmod/attribute workaround was
  attempted. The later `104710Z` run contains the installation evidence.
- `.runtime-proof146/pc401-recovery-readonly.raw`, a redundant local copy of
  the independently mounted read-only recovery image. Its byte contents
  matched the manifest-verified external copy; the external copy and physical
  PC401 remain available.
- `.runtime-proof165`, a disposable QEMU clone and generated local run data;
  DR165's screenshots, block graph, logs, and persistence results remain in
  `docs/verification/165`.

The `.runtime-proof165/proxy.py` helper was copied into
`baseline/lib/installer_package_proxy.py`; `baseline-allscript-install` now
uses that maintained path. A regression test was added first and confirmed
failing, then passed with the implementation. Recovery tests also cover stale
incomplete markers: completion now removes the marker after the manifest is
durably written, while a valid later manifest remains authoritative. The
`test_allscript_install` and `test_drive_recovery` modules passed (14 tests
combined), and `git diff --check` passed. No real hardware was changed or newly
verified.

After cleanup, CACHE had 104 GiB free. PC601 remains selected and
untouched. Physical boot/network/firewall, native VM execution, drivers, and
physical persistence remain open as recorded in DR174 and the active work queue.

The final inventory contains `.runtime-proof146` and `.runtime-proof173`; the
other four original top-level runtime-proof directories are absent. Explicit
cleanup commands did not name `.runtime-proof133` or `.runtime-proof138`. The
large VM/application files from `.runtime-proof133` were not found elsewhere
under `/run/media/cane` or `/mnt`. Git reports the missing `.runtime-proof138`
worktrees as prunable; their branch commits remain, but their uncommitted
worktree changes may be lost. Cause is undetermined. No Git pruning/recovery or
further deletion was attempted.
