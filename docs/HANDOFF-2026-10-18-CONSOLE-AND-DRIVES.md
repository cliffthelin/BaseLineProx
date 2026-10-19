# Handoff, 2026-10-18: drives, rebuild, parent vault, and the new console

Branch `claude/whats-left-fixes` (pushed, not merged to main). Everything below is committed. Read this first, then `docs/design/nav-migration-map.md` (generated) and DR270 to DR272.

## Rules the operator set (still in force)

- **No hardware identifiers in the repo.** No serials, MACs or hostnames in code, tests or docs. They are operator data on git-ignored volumes (`baseline-build/drives.json`, `own-drives`). Tests use synthetic `SYNTH...` values; `tests/unit/test_no_real_hardware_identifiers_in_tracked_files.py` checks this against the machine it runs on. Git history on origin still holds earlier values (rewriting it needs the operator's approval).
- **Never type credentials or create accounts** through VM screens or pages. Owners are the signed-in Proxmox user, no password.
- **Never rewrite what did not change**, and do not wipe a drive when an in-place update will do. A full install wrote 168.8 GiB to a drive; avoid it.
- **Typed paths are not allowed.** A path is browsed to, or pasted and then validated at entry (see "Next" 1).
- **Desktop-size renders only.** Do not resize any window the operator can see (Playwright's Chrome window was left at a stuck size and confused them). Use `baseline/bin/baseline-page-shot` (headless Chrome).
- **Never `pkill -f`/`pgrep -f` with text in your own command line** (kills your shell). Use pid files or `ss -ltnp`.
- Run the **full unit suite before committing** (`python3 -m pytest tests/unit -q`, about 5 minutes; it caught real bugs three times: `provision.sh` not deploying a new module, a syntax error, and a stale test).

## What was built this session

**Drives and identity**
- Twin sync (`twin_sync.py`, `baseline-twin`, timers): two drives kept the same by child UUID; layered rules (newest wins for data, union for cache, nothing for substrate); ties kept as `.twin-conflict`; room checked before copying.
- Lane protection derived from the stamp on the drive (`drive_guard.lane_verdict`), `cardinality.py` (never pick "the first" of several), own-drives file instead of serial tables.
- Seed runner for Bazzite and Omarchy, six ready-made OS owner flows verified on real Proxmox.

**Install and rebuild**
- `baseline-allscript-install`: build check (`build_currency.py`) skips a wipe when the drive already carries the build; an installed drive is refused a rewrite without `--reinstall`; each install reports bytes written (`device_wear.py`); the rehearsal mirror on CACHE is exactly the child drive's size (sparse).
- The installer asks the system for root itself (`elevate.py`: Ubuntu's dialog, or sudo) instead of being wrapped.
- **Rebuild never wipes** (`rebuild_drive.py`, `baseline-rebuild-drive`): attaches the drive, snapshots every data volume into git (`data_vault.py`), writes bundles onto INSTALLER_CACHE, and (only with a reviewed bundle) updates the code layer through the existing guarded `installed_drive_update`. Fluid volume sizes: `volume_growth.py` has no per-role ceiling now and runs every 2 minutes.
- Unchanged files are never rewritten (`write_once.py`, a content-compare `cp` in `provision.sh`, vault bundles skipped when history has not moved).

**Managed server mode (opt-in, standalone by default)**
- `managed_mode.py`, `baseline-managed`, console page. Parent vault on CACHE (`parent_vault.py`): each child's persistence data in git, filed by combination id, one branch per drive. Remote rebuild (`rebuild_authority.py`, `rebuild_policy.py`, `baseline-rebuild*`): a root service that runs only a policy-pinned command for hash-pinned drive identities, approved with a one-time code. **Not installed anywhere**; installing needs the operator's sudo once (`sudo baseline/bin/baseline-rebuild-setup`, after `baseline-managed enable --parent-vault FOLDER --remote-rebuild`).

**The console (`baseline_web.py`, systemd `baseline-web.service`, now ordered after `pve-cluster`/`pveproxy`, address from `/etc/baseline/web.env`)**
- One theme (`console_theme.py`, the Launcher's night-glass), nested navigation in Simple and Advanced modes (`nav_tree.py`), settings as cards with plain names (`settings_ui.py`), configuration editor as one box with Efficient and Advanced tabs (`structured_controls.py`), status strip and Refresh on every page.
- TUI parity: every TUI feature has a console page (history graphs, connection name/power/role, hardware overview, copy answer, status bar). `parity_manifest.py` lists TUI features and installer functions; `tests/unit/test_parity_manifest.py` keeps `tests/unit/parity_gaps.json` equal to the real gaps. **35 of 48 carried, 13 gaps, all of them installer or build-manager functions** (backup before install, install, in-place rebuild, rehearsal, checkpoints, wear report, cache builds, Kasm base, OS bases, ISO build, drive names, parent vault browse/restore, remote rebuild setup). Nothing may be retired while a gap remains.
- Look at it: `baseline/bin/baseline-web-preview 8190 > /tmp/baseline-preview.out &` (loopback only, throwaway state, one preview session), then `baseline/bin/baseline-page-shot /settings out.png 1440 1500 advanced`.

## State of the drives (operator data, not in git)

- **PC401** (the second 512 GB drive): fully installed from the build of about 15:00 on 2026-10-18, all stages recorded, child UUID stamped. Its journal has no build record and no wear record (the run used the older script). It is on a faster USB port now.
- **PC601**: installed 2026-10-13 from an older build; has a complete recovery image. No in-place update has been run on either drive.
- The two drives are **not paired** with each other yet (`sudo baseline-twin pair --peer-serial ...`), and the first-boot vault step has not run on a real drive.
- Nothing from this session's console work is installed on any drive. The operator's PC401 still shows the old flat menu.

## Next

1. **Path picker: done for Managed server mode, container backup destination, inspection mountpoint (removed), partition unmount (a list of mounted partitions, `/drive-admin/mounted`) and the setup rebuild target (generated disposable image).** Remaining typed-path surface to look for: none known; re-grep `input name=...path|dir|folder` when adding pages. Earlier note: **Path picker: done for Managed server mode** (`path_picker.py`, routes `/fs/browse` and `/fs/validate`, server re-validates on save; the page is one section with one description). Reuse `picker_html`/`picker_script` for every other path in the console (backup file in Settings, the installer pages) and remove any remaining typed path fields.
2. Rebuild the remaining pages on the shared components, one at a time, judged with `baseline-page-shot` at 1280/1440/1920 and a narrow width: Hardware panels, Network, Sensors, Virtual machines, then the Installer pages. Empty selects should say "None found".
3. Move the 13 build-manager functions into the console under Installer, each with a typed confirmation where it erases, and close the gaps in `parity_gaps.json` as they land.
4. Wire the in-place code update (bundle preparation from the installer page, write only files that differ), then update PC401 and PC601 in place; pair the two drives; install the remote rebuild service if the operator wants it.
5. Deploy a build to a drive so the console can be seen where it runs; verify the web address setting on a real Proxmox boot.
6. Still open from before: Ollama LXC and app-VM first-boot verification, codex's installed-QEMU acceptance checks and a native cold boot of each drive, local-account paths (`/run/media/cane/...`) and `INSTALLER_UUID` in the repo (operator was asked), moving VG names from serial to child UUID (offered, unanswered).

## Continued 2026-10-18 (second session on this handoff)
Typed paths removed from the container backup page, Drive Administration (mountpoint and partition unmount) and the setup rebuild form; the server validates the backup destination again. Full unit suite: 5073 passed, 3 strict xfails. The container-backup test and the new picker tests were written after the code, not before.
