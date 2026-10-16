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
- The first migration (the redirect service moves what the installer left in the directory into USER_ADMIN) runs on the boot after
  provisioning, before any of those services start, so no live database is moved.
- **Fail closed:** if USER_ADMIN cannot be mounted, Proxmox does not start; it never runs on a second, empty configuration on SUBSTRATE.
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
  They are links into Proxmox's own console pages, **not an embedded frame**: embedding across origins is reported to fail on Proxmox's
  authentication cookies and its framing policy is unconfirmed, so it is not relied on. A page cannot force browser fullscreen on another
  origin; "Fullscreen" is a full-screen-sized window, and Proxmox's console toolbar has its own fullscreen toggle. Honest limit.
- **Containers (LXC):** the model supports them (`console=lxc`, console only, no Window/Fullscreen) but the page does not list them yet; only VMs
  are tiles today. Not built.
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
