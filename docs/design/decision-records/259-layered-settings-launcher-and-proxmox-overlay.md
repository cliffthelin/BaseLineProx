# 259 - Layered settings shared across OSes, Proxmox's state as overlay data, and the phone-style launcher

Date: 2026-10-14. Status: operator decisions recorded; first slice built and unit-tested against fakes. NOTHING here is verified on real
hardware or in a rehearsal VM yet (each section says what is and is not proved). Builds on DR257 (roles) and DR258 (environments).

## Operator decisions (2026-10-14, in answer to the open questions of DR258)
1. Ceph can wait. Two-factor can wait.
2. **Ubuntu is one of about ten operating systems** the application sets up, not the special case. The user's settings are shared **from one
   OS to the next** and configure each OS; each OS's applications are also set up from the configuration, the user data and the app data.
3. **Proxmox uses overlay data like everything else.** Its overlay lives on USER_ADMIN. The only places non-public settings and data go are
   USER_ADMIN, USER_DATA (`USER_<PERSONA>`), APP_DATA (`APPDATA_<PERSONA>`) and SESSION_TEMP (non-persistent). Never SUBSTRATE.
4. A **custom web application that looks like a phone OS**: every VM/OS is a tile; right-click (long-press on touch) gives its details and
   settings, the OS's settings, the settings of the applications installed in it and which are installed; and a VM runs in three modes:
   **headless (console), GUI in a window, GUI fullscreen**.

## 1. Proxmox's own state on USER_ADMIN (built; fakes only)
`persist_bind_mounts.REDIRECT_PATHS` gains `/var/lib/pve-cluster` (the pmxcfs database behind `/etc/pve`: storage, users, datacenter
settings, guest configs, certificates, two-factor), `/var/lib/pve-firewall`, `/var/lib/pve-manager`, `/var/lib/rrdcached`.
`boot/proxmox-overlay.conf` is installed as a drop-in for pve-cluster, pve-firewall, pvedaemon, pveproxy, pvestatd and rrdcached:
`Requires=` and `After=baseline-persist-bind-mounts.service`. Consequences, deliberately:
- The first migration (the redirect service moves what the installer left in the directory into USER_ADMIN) is meant to run on the boot after
  provisioning, before any of those services start. **The first rehearsal run showed it did not:** with `Requires=` in the drop-in, a
  `pveproxy` restart that `baseline-proxmox-defaults` does during the first boot started the redirect service mid-boot, which moved the
  live pmxcfs database (config.db and its WAL) under a running `pve-cluster`. Proxmox came up afterwards with its data, but copying SQLite
  files under a running process is not safe. **Fixed twice over:** the drop-in is now `After=` only (nothing can pull the redirect service
  in), and `persist_bind_mounts.ensure_redirect` refuses to move a Proxmox state directory while the service that holds it is running, or
  when that cannot be read (`QUIESCE_BEFORE_MOVE`).
- **Fail closed:** the redirects are in /etc/fstab once made, so if USER_ADMIN cannot be mounted the boot stops at local-fs.target; Proxmox never
  runs on a second, empty configuration on SUBSTRATE. (The first version used `Requires=` for this; see above for why it was dropped.)
- ~~The redirect service has no dependency on Proxmox, so the ordering cannot cycle.~~ **Wrong, found by the first QEMU rehearsal (2026-10-15).**
  `baseline-storage-verify.service` was already `After=pve-cluster.service` and `Before=` the redirect service (it reconciled Proxmox's storage
  definitions with `pvesm`), so the drop-in closed a loop: storage-verify -> pve-cluster -> redirects -> storage-verify. systemd resolved it by
  deleting the redirect service's start job: Proxmox never started and the first-boot CONFIRM screen never appeared (the VM sat at a login
  prompt). The unit test I wrote for this only compared unit text and could not see it.
  **Fix:** `baseline-storage-verify.service` keeps its identity/capacity check before the redirects and no longer waits for Proxmox; the
  `--reconcile-proxmox` step moved to the new `baseline-storage-reconcile.service` (after the redirects and pve-cluster, before Baseline's own
  services). The order is now verify -> redirects -> pve-cluster -> reconcile -> Baseline. `tests/unit/test_boot_unit_ordering.py` loads
  Baseline's units, Proxmox's real ordering directives (tests/fixtures/proxmox-units, from the 9.2 packages) and provision.sh's drop-ins
  together and asks `systemd-analyze verify` for cycles; it reproduced this one before the fix.
Not proved: that a real Proxmox boots this way, that the first migration completes, that the GUI sees its configuration afterwards. DR257
step 2 requires the rehearsal VM first; that run has not happened. Still open from DR257: `/etc/ssh` host keys, `/etc/shadow`,
`/var/log`, `/etc/machine-id`/hostname/network files, and the publishability scan.

## 2. Layered settings (built; fakes and temp directories only)
`layered_settings.py`. Four persisted layers and one temporary, resolved in this order (later wins):

| Layer | Where | Written by | Meaning |
|---|---|---|---|
| admin | `USER_ADMIN/settings/shared.json` | an administrator only | host-wide defaults every OS starts from |
| user | `USER_<PERSONA>/settings/shared.json` | the person | their settings, shared by **every** OS |
| os | `USER_<PERSONA>/settings/os/<O_V_NNNNN>.json` | the person | their differences for **one** OS |
| app | `APPDATA_<PERSONA>/<A_x_NNNNN>/os/<O_V_NNNNN>.json` | the person | one application's settings **in one OS** |
| session | `SESSION_TEMP/launcher/session.json` | the launcher | non-persistent (last used run mode, window state) |

- A guest never writes to USER_ADMIN (DR257); the admin layer is read-only to everything except an administrator.
- Keys are an allowlist with validated values, not free text: `timezone`, `locale`, `keyboard`, `theme`, `display_scale`,
  `default_run_mode` (OS/user layers); `enabled`, `autostart` (app layer). Anything else is refused. The list is v1 and meant to grow.
- Entities are named by their constant identifiers (`naming`), never by a name; a path built from anything else is refused.
- The root of every layer is checked against the four allowed volumes before any write; a path that resolves anywhere else (SUBSTRATE, a
  symlink out) is refused. Writes are atomic (temp file + rename), mode 0600.
- Effective OS settings = admin + user + os. Effective app settings = those + the app layer.
Not built: a guest that **applies** these (cloud-init / first-boot script per OS), which is what actually makes an OS configured from them;
the ten-OS list itself (DR258 question 4 is still open: which images need a helper); the association table user x OS -> app-data tree.

## 3. The launcher (`/launcher`; built; unit-tested, never opened on real hardware)
A phone-OS-style home screen: status bar, a grid of tiles (one per VM/OS, with its applications underneath), a dock. Right-click or
long-press on a tile opens a menu: **Open** (Console / Window / Fullscreen), **Start / Shut down**, **Details**, **VM settings**,
**OS settings**, **Applications**. Settings panels read and write the layers above.
- **Run modes.** Console = Proxmox's xterm.js serial console in a browser tab (needs `serial0` on the VM; without it the menu says so and
  offers Window). Window = Proxmox's noVNC console in a popup window. Fullscreen = the same console in a popup sized to the whole screen.
  They are links into Proxmox's own console pages, **not an embedded frame**. Checked 2026-10-16 against Proxmox 9.2: it sends no
  `X-Frame-Options` and no framing CSP, so it does not forbid embedding; cross-origin cookie handling is still reported to be a problem, and Baseline's
  own CSP forbids frames, so embedding is not built. A page cannot force browser fullscreen on another
  origin; "Fullscreen" is a full-screen-sized window, and Proxmox's console toolbar has its own fullscreen toggle. Honest limit.
- **Containers (LXC):** are tiles after the VMs (identifiers `O_L_NNNNN`), console only (`console=lxc`; Window/Fullscreen shown disabled with the reason),
  start/shutdown through the existing `/containers/action` jobs, OS settings shared like any OS, no application panel. A problem listing them is a
  notice on the page; it never hides the VMs. Unit/HTTP-tested against a fake container host only.
- VM start/stop/configure reuse the existing `/vms/action` jobs; nothing in the launcher runs a command of its own.
Not verified: the console URLs against a real Proxmox, popup behaviour in the host's browser window, touch long-press, anything on a
laptop. Not built: guest-side application install and status ("which applications are installed" shows what the settings layers and the
environments catalogue say, labelled as such, until a guest reports it).

## Fixed alongside (same day, from the operator's issue list)
`/power` (systemd shutdown/restart; the old nav button asked GNOME, which the host does not have), a read-only "Drives found" table on Drive
Administration (the list had hidden every drive off the allowlist and still said "every real, non-boot drive"), and bluez/pipewire carried
in the offline cache. Unit-tested against fakes only. Ceph and two-factor wait (operator).

## What an operator must still do or decide
- Rehearse Section 1 in the QEMU VM (rebuild the offline cache and ISO first: new packages and a new drop-in): does Proxmox boot with
  `/etc/pve` on USER_ADMIN, does the first migration complete, does the GUI show its storage, users and guests afterwards.
- Name the ten operating systems and which need a helper (DR258 question 4).
- Say what the guest-side applier should set up per OS first (cloud-init for Ubuntu/Debian is the obvious start).
- Containers as tiles; a console URL check against a real Proxmox; the touch long-press on a real touch screen.

## QEMU rehearsal evidence (2026-10-15; runs 20-22 of `baseline-allscript-install --stage rehearse`; a sparse 64 GiB disk, no network, no real drive)
Built from commits through the live-migration fix; offline cache rebuilt first (403 packages, 491 files verified, all five new audio/Bluetooth
packages and the five applications present). Read over SSH with the development monitoring key (a host-to-guest port forward added through the
QEMU monitor) and from a RAM dump of the guest when it was unreachable.
- **Found by run 20, fixed:** the ordering cycle (storage-verify <-> pve-cluster <-> redirects). Symptom: VM idle at a login prompt, no CONFIRM
  screen. Evidence: the guest journal's "Found ordering cycle ... Job baseline-persist-bind-mounts.service/start deleted".
- **Found by run 21, fixed:** the redirect service started mid-boot through `Requires=` and moved the live Proxmox database.
- **Run 22 (final code), verified in the guest:** first boot never starts the redirect service (0 starts, 0 refusals); second boot order is
  storage-verify 4.2 s -> redirects 4.4-4.6 s -> pve-cluster 4.9 s -> storage-reconcile -> first-boot; all four Proxmox state directories are
  mounted from USER_ADMIN (device `baseline_user_admin`); `config.db` is on USER_ADMIN and the same paths on the substrate hold 0 entries (also
  `/root`, `/home`, `/etc/baseline`); Proxmox sees storage.cfg, user.cfg, datacenter.cfg and all eight storages; a marker pool created with
  `pveum pool add` was found inside `user.cfg` in the database on USER_ADMIN and **survived a normal reboot**; 0 ordering-cycle messages, 0 failed units.
- **Also verified in the guest:** bluez, pipewire, pipewire-pulse, wireplumber and libspa-0.2-bluetooth installed offline from the carried repository
  (the `bluetooth` service is inactive because the VM has no Bluetooth hardware); the new modules deployed and import; layered settings written
  to the real mounted volumes (user and os layers on USER_PERSONAL, app layer on APPDATA_PERSONAL, session layer on SESSION_TEMP, 0 files on the
  substrate, admin layer refused); `/launcher`, `/launcher/state` and `/power` exist and redirect to login; the launcher state builds from the real
  Proxmox VM host (0 VMs, no error); the kiosk browser window shows the Proxmox login with Baseline's tab and bookmarks.
## Still not verified
- Real hardware (laptop or the PC601 drive itself) and real Bluetooth devices; the launcher in a logged-in browser with real VM tiles, its
  console URLs against a real Proxmox, and the popup/fullscreen behaviour; right-click and long-press on real input devices.
- Several Proxmox services were checked only for "active"; a VM or container was not created and run under the overlay layout in this run.
- The sensors-history, scripts-inbox and other older units were not part of this check.
## Open: a stale offline cache is accepted silently
`baseline-allscript-install`'s `cache_status` calls any cache with a manifest and an `apps` folder "complete", so a cache built before
provision.sh gained new packages is used as-is and the install fails offline at `apt-get install`. This run avoided it by moving the old cache
aside by hand. A fix needs the cache to record what it was built for (a hash of `offline_cache.required_packages`) and the stage to compare it;
comparing against the apt index does not work (the Proxmox base already has curl, smartmontools, ethtool and others, so they never appear there).

## Follow-ups built 2026-10-16
- **Stale offline cache is now refused** (the open item above): the cache carries `BUILT_FOR.json` (the package list it was built for, hashed in its
  manifest); `baseline-allscript-install` compares it with `offline_cache.required_packages` and calls a mismatch "stale", naming what it lacks, and the
  cache stage keeps the old cache under a timestamped name and rebuilds from it. Checked on the real stale cache (reported stale; the rebuild
  renamed it and produced 403 packages, 493 files).
- **TUI VMs tab** (operator item 9): `s` starts and `h` cleanly shuts down the VM or container under the cursor; Enter shows its details
  (`vm_power.py`: fixed `qm`/`pct` commands, validated). Forced stop stays in the browser launcher, which asks first. The key handling needs
  Textual, which this dev machine lacks, so it is checked in the guest, not here.

## Rehearsal run 23 (2026-10-16): the launcher end to end, and two defects it found in the VM library
Final code through `2527c06` plus the changes below; hot-copied into the running guest for the last part. Driven over the forwarded web port with a
throwaway account created inside the disposable guest (its password generated for the test and never printed) and a real Proxmox-backed VM.
- **Launcher, verified in the guest:** real login (303 to `/home`); a VM made through the real VM library appears as a tile with a constant
  identifier (`O_V_00001`), its menu and details; user and per-OS settings saved and read back with their sources; the admin layer refused from
  the page; `/power` present and a power request without the confirmation refused; **starting the VM through `/vms/action` really started it**
  ("Started rehearsal-vm", the tile became running and offered Console, Window and Fullscreen); both console address shapes are served by Proxmox
  (an xterm.js page and a noVNC page, HTTP 200). The page rendered in a browser from the guest with its running tile.
- **TUI VMs tab, verified in the guest** with Textual's Pilot against the real app (recording runner, no real `qm`): keys do nothing outside the VMs
  tab; start of a stopped VM issues `qm start 101`, shutdown of a running one `qm shutdown 102`, start of a container `pct start 200`; a disallowed
  action (shutting down a stopped VM) is refused with a notice; Enter opens the details.
- **Defect 1, fixed:** the VM library compared a new disk with the *current* free space of a role volume, but those start at 1 GiB and grow on
  demand, so a fresh drive could not create its first VM. It now asks `volume_growth.ensure_room` first (`VmHost._ensure_room`, hook wired in
  `_vm_host_for`), and says why when growth cannot help. Verified in the guest: the persistence volume grew.
- **Defect 2, fixed:** the default VM persistence store was `/mnt/USER_ADMIN/vm-data` (DR117), against DR257's "VMs never write to USER_ADMIN". New
  default `/mnt/USER_PERSONAL/vm-data`; a drive that already holds VM records under the old folder keeps using it (`default_persistence_store`), so
  nothing is orphaned and Proxmox's `baseline-user` storage keeps matching. `docs/INSTALL.md` and `docs/layers/06` updated.
- **Open decision (not changed):** the library demands `FREE_HEADROOM` = 10 GiB (plus 10% of the disk) free in each of two volumes before it
  creates any VM. With growth now wired in, that makes a first small VM grow two volumes by about 10 GiB each, which sits oddly with "volumes grow
  only if actually used and needed"; the rehearsal's 21 GiB volume group was a hair too small for it (the test lowered the constant in its own
  process only). Whether a growable volume should need less headroom at creation, and let the growth timer follow actual use, is the operator's call.
