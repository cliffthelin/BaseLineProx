# DR310 — Parent Bluetooth pairings on PC601 and BASELINE_MIRROR

Date: 2026-10-19. Direct operator request: set up Bluetooth devices on PC601 and its mirror so the parent host can send its Bluetooth configuration.

## Finding and change

Read-only physical inspection resolved PC601 by its enrolled serial and verified its SUBSTRATE storage policy against USER_ADMIN's filesystem UUID. The parent has seven BlueZ device `info` records across two controller directories. PC601 had no `var-lib-bluetooth` on USER_ADMIN, no Bluetooth bind in fstab, and no persistence ordering drop-in. The existing mirror was located through its partition UUID and its child's volume manifest, not a guessed directory.

Copied the parent's `/var/lib/bluetooth` tree without printing or parsing keys to PC601 USER_ADMIN's `var-lib-bluetooth` and the corresponding USER_ADMIN folder on BASELINE_MIRROR. Directories are 0700, files 0600. Controller identity is preserved; this is not a pairing conversion for a different Bluetooth controller. No parent service was stopped and no drive was formatted.

On both copies, added the fstab bind from `/mnt/USER_ADMIN/var-lib-bluetooth` to `/var/lib/bluetooth`, added that directory to the installed persistence mapping and its Bluetooth-service migration guard, installed a BlueZ dependency/ordering drop-in, and enabled BlueZ offline. Only those system files were edited; original system files are backed up on CACHE. The mirror received the same targeted changes, not a full mirror refresh.

Source now has the same persistence mapping/drop-in and `baseline-rebuild-drive --bluetooth-from-parent`. The explicit option copies parent pairings after the existing backup, before mirror history filing/refresh. It refuses absent devices, links/special files, missing USER_ADMIN and conflicting existing child settings; identical copies are idempotent. It transfers BlueZ pairing/device state only, not `/etc/bluetooth` global policy or USB-controller passthrough. Unrelated uncommitted guest-persistence work was preserved.

## Evidence and limits

93 focused tests passed, including real temporary-file transfer checks and injected rebuild lifecycle checks. Shell syntax and diff whitespace checks passed. These are source/unit checks, not Bluetooth connection tests.

Physical writes and independent read-only remount verification completed on both PC601 and BASELINE_MIRROR: all transferred files matched the parent, seven device records existed on each copy, permissions were private, BlueZ was enabled and fstab/drop-in wiring was present. Every inspection/deployment mount was unmounted afterward. No native boot, Bluetooth radio, reconnection, audio or input test occurred; no QEMU test was run for this change.

Evidence and rollback system-file originals:
`CACHE/baseline-build/bluetooth-repair-20261019/{report.json,verification.json,before/}`.
The one-off deployment/verification helpers were `/tmp/baseline-bluetooth-{deploy,verify}.py`. Pairing contents are intentionally absent from this record.

Native boot and actual device reconnection remain open under queue72/78 physical/runtime acceptance. The earlier DR258/259 statement that physical Bluetooth was unverified remains true; this adds physical configuration-copy evidence only. Current INSTALL and queue checkpoint updated; historical decision records retained.
