# DR248 - The drive's installer cache is the build source: OS images, drivers, applications and packages, and it learns

Date: 2026-10-11
Status: implemented; proven on the offline rehearsal (blank sparse disk, no network). Not run on PC401.
Follows DR245-247. Operator direction (2026-10-11): OS installs, driver installs, applications and packages are one
thing: resources a build is filled from, from the drive's own INSTALLER_CACHE as far as possible; when that is not
enough, what is fetched is added to the INSTALLER_CACHE so later rebuilds are more complete and less dependent on
outside resources. Nothing is constrained to be online-only.

## What the drive now carries (all verified, none fetched at install time)

- the Proxmox installer ISO and its expanded environment (DR245);
- OS install images the installer host offers (`--os-iso`), copied into `INSTALLER_CACHE/isos`, listed by the web app's
  VM page through the `baseline-isos` Proxmox storage (DR246);
- packages: provision.sh's, the first-boot diagnostic tools, the applications' runtime packages
  (`application_bundle.runtime_plan`), and the drivers the installer cache catalog declares
  (`installer_cache.firmware_packages`: CPU microcode, Wi-Fi firmware), with all dependencies, as a flat apt repository
  registered as a permanent apt source; npm's cache for Claude Code;
- the five applications (VS Code, Spotify, Chrome, ChatGPT, Claude Desktop): `baseline-apps prepare` output (archive +
  recipe with pinned sha256) and the dependencies of their packages.

## Read-through (building a cache)

`baseline-build-offline-cache --seed DIR` (repeatable): earlier caches, the volume's own `packages`/`firmware` folders and
the cache the drive carries/learned pre-fill the build VM's apt and npm caches and the prepared applications; only what is
missing is downloaded and the new cache keeps everything it was seeded with. `--refresh-apps` forces new application
downloads. The `cache` stage rebuilds an older cache that lacks the applications, keeping the old one as a seed.
Driver packages are downloaded even if the build VM already has them installed (`--reinstall`).

## Write-back (what the running drive had to fetch)

`cache_learn.py`, `baseline-cache-learn`, an apt `DPkg::Post-Invoke` hook (never fails apt): real .debs apt downloaded are
added to the carried repository, its index regenerated, and each addition recorded in `LEARNED.json` (sha256, source,
time). `baseline-cache-learn app <name> <dir>` keeps an application prepared online. `MANIFEST.json` is never rewritten;
`offline_cache.verify_carried` checks base plus learned (a regenerated index or a newer application may supersede a base
file; an unrecorded or altered file is refused). First boot and the repository check use it.

## Evidence (rehearsal VM, no network, 2026-10-11)

- cache built: 374 packages, 412 files, 1.8 GB; 231 packages and the npm cache reused from the seed; five applications
  carried (vscode 1.141.0, spotify 1.2.95, chrome 155.0.8059.39, chatgpt 26.1007.21434, claude 2.31226.1);
- first boot: `applications carried and verified`, 412 packages verified, OS image carried and registered, CONFIRM,
  offline commit, kiosk showing the Proxmox login;
- `tests/integration/verify_apps_offline.py` in the VM: `APPS-OFFLINE {"runtime": true, "vscode": true, "spotify": true,
  "chrome": true, "chatgpt": true, "claude": true, "ok": true}`: `baseline-apps install-runtime` from the drive's
  repository, then each application's `install` (recipe checksum and package identity re-checked) and sandbox `preflight`
  usable. The apt hook ran during those installs and did not disturb apt.

## Found and fixed on the way

- npm rewrote a cacache index inside the carried repository during provisioning (first boot then refused it); npm now
  works in a scratch copy and the carried repository is only read.
- the build VM's own installed packages are not downloaded (apt sees them installed): `amd64-microcode` was missing;
  drivers are now fetched with `--reinstall`. Re-verified by a rebuild (2026-10-11): 375 packages, 412 files verify, all four driver
  packages carried (`amd64-microcode`, `intel-microcode`, `firmware-realtek`, `firmware-mediatek`); the rebuild reused 374 packages from
  its seeds and downloaded only the one that was missing.

## Not proven / open

- the write-back hook has been exercised by unit tests with real .debs and by running inside apt operations that
  download nothing; no real online download on the target was tried.
- launching an application (needs a display) was not tried; preflight only.
- `installer_cache.py`'s inventory page still scans only `isos/packages/firmware/...`; it does not yet count what the
  carried repository holds.
- the real install run on PC601 (this branch's development-phase target; PC401 belongs to the parallel effort), which needs the
  operator's own `sudo` command and PC601's mounted EFI partition unmounted first.
