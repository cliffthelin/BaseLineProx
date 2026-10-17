# 260 - Kasm Workspaces on top of Proxmox, aligned with the overlay and persistence design

Date: 2026-10-16. Status: built and verified end to end on a Proxmox host that is itself a QEMU VM (nested KVM, no network), including from a freshly built installer; NOT yet on real
hardware. Each claim says which. Builds on DR257 (volume roles), DR258 (environments, application containers) and DR259 (layered settings, launcher, Proxmox overlay).

## Operator instruction (2026-10-16)
"Build in Kasm on top of Proxmox and align Kasm to build the overlays and persistence data like I have been designing to. Include configuring Kasm to do these
things in the installer setup so that it can be ready immediately on a new setup."

## Why a VM, and which one
Kasm is a Docker-based platform (Postgres, API, manager, agent, proxy, guacamole, RDP gateways, then one container per workspace session). Docker on the
Proxmox host would rewrite iptables/forwarding that Proxmox's firewall and guest networking depend on, and Kasm officially supports a dedicated machine, so it
runs in **its own VM**. Kasm 1.19.0's installer lists Debian 13 as supported, which is also the host's release, so the VM is **Debian 13** (genericcloud image).

## How Kasm's data maps onto the volumes (the point of this record)
| Kasm data | Where it lives | Volume / layer | Why |
|---|---|---|---|
| Debian 13 + Docker + Kasm installer + the service and workspace images | the base image `kasm-base-<ver>-debian13.qcow2` on INSTALLER_CACHE | **base**, vanilla, read-only, reproducible | no secrets, no install state; rebuilt only by the build |
| The VM's root and Docker's container layers and running workspace sessions | a copy-on-write overlay of the base | **SESSION_TEMP**, disposable | a reset or rebuilt OS starts fresh; nothing personal is on it |
| Kasm's platform state: `/opt/kasm` (configuration, certificates and private keys, logs) **and** Postgres's data (users, sessions, workspace settings) | a persistent disk with serial `baseline-kasm-admin` | **APPDATA_ADMIN** (the admin persona's application data) | secrets and the user database; DR257 says VMs never write to USER_ADMIN, so the platform's state is the administrator's *application data*, not host configuration |
| Workspace persistent profiles `/mnt/kasm_profiles/{user_id}/{image_id}` (a person's profiles together; one folder per workspace) (browser profile, editor settings, files) | a persistent disk with serial `baseline-kasm-prof` (a virtio serial is 20 characters at most) | **APPDATA_PERSONAL** | a person's application data is theirs and goes only to their AppData volume |
| Kasm's generated administrator credentials | Baseline's credential vault | **USER_ADMIN** (the host's own, encrypted at rest, DR258) | the host generated them and keeps its copy; Kasm's own copies stay on APPDATA_ADMIN |
Nothing personal is on SUBSTRATE, INSTALLER_CACHE or the base. Postgres's data is a named Docker volume, which would sit in Docker's data directory on the
disposable root; it is created as a bind volume onto `/opt/kasm/data/db` on the admin disk **before** Kasm installs, and re-created at every boot (Docker's
record of it is on the root; the data is not).

## How it is made ready on a new setup
1. **Build time (online, once)** - `baseline-build-kasm-base` (`kasm_build.py`): verifies the Debian image (SHA-512) and the Kasm bundle (SHA-256), boots
   Debian 13 under QEMU, installs Docker 26 and Compose, makes the fixed `kasm` (6500) and `kasm_db` users, **pulls** the eight service images and the carried
   workspace images at the static `1.19.0` tag (Kasm's own offline archives are not used: they carry only four workspaces), packs the two Docker plugins the
   installer would otherwise fetch from the registry (log driver, sidecar network), records every image digest in `KASM.json`, and makes the image generic (no
   machine id, host keys or cloud-init state). It does **not** run Kasm's installer, so the image holds no secrets and no install state (`KASM.json` says so
   and the setup refuses a base whose manifest does not).
2. **Carried with the installer** - `baseline-build-offline-cache --kasm-base DIR` copies the base into the offline cache as `kasm/` (checked first against its
   manifest), so the installer's own manifest covers it and a new setup needs no internet.
3. **On the target** - `baseline-kasm-setup.timer` (enabled by `provision.sh`, retries until done, then only makes sure the VM runs) starts
   `baseline-kasm setup` once first boot has completed and Proxmox's storage is reconciled. `kasm_setup.py`: checks the volumes are mounted and the base
   matches its manifest; sizes the VM from the host (a quarter of its memory, 6-16 GiB; half its cores, 2-4; refuses a host under 12 GiB); registers three
   directory storages; makes the root as a qcow2 overlay on the vanilla base (in SESSION_TEMP) and the two data disks as bare sparse qcow2 (reserved, never written)
   in APPDATA_ADMIN and APPDATA_PERSONAL, attached by serial; builds the VM with the guest agent on; starts it; **generates the four credentials and stores them in
   the USER_ADMIN vault before the guest is told them** (a vault that cannot be written is a refusal; a rebuild reuses the stored ones because the database was made
   with them); sends them to `baseline-kasm-install` on stdin through the guest agent. Existing disks are never replaced; a rebuilt VM reattaches them under the
   recorded VMID. The page `/workspaces` (and the Home, navigation and kiosk bookmark entries) shows the state and the link.
4. **Inside the guest, `baseline-kasm-install`** - `install.sh --install-profile noninteractive --accept-eula --no-start --use-static-images` with the offline
   service archive (lists no images: they are already loaded) and the two plugin archives; then `db_init` seeds the carried workspaces from the bundle's own list
   trimmed to what is carried (six entries, each with its own image id, the persistent ones with a profile path, and `group_images` rebuilt so users can see
   them); the Postgres data is copied to a bind volume on the admin disk and the stack is started by `baseline-kasm-start`; it waits for the health check and
   writes `installed.json` last.
5. **Every later boot** - `baseline-kasm.service` (in the base) mounts the disks by serial and runs `baseline-kasm-start`: the `kasm` user comes with the base,
   the Docker network and the DB volume binding are re-created (Docker's record of them is on the disposable root; the data is not), and `docker compose up -d` runs
   with no pulls.

## Workspaces offered (the user's choice of shape, from the reference conversation)
Browser (temporary, nothing kept), Browser (personal, its own profile), Development desktop, VS Code, Firefox, Terminal. A personal workspace must be started
with `persistent_profile_mode: Enabled`: neither the profile path nor the "enforce persistence" flag alone mounts it. Documents are meant to live in the user's
own data, not inside a profile. Resetting a profile through Kasm's API is destructive and, when built, goes through explicit authorization (not built).

## Verified, and how (QEMU test guest on this machine, no network: user-mode networking with `restrict=on`)
- The base builds in about 7 minutes plus flattening; **15.5 GiB** compressed, all 13 image digests recorded.
- Offline install on a fresh overlay: Kasm installed in 87 s with no registry access and reported healthy; the user signs in and sees the six workspaces.
- A personal session mounts the profile from the dedicated disk (`/mnt/kasm_profiles/<user>/<image>` -> `/home/kasm-user`); Postgres's data is on the admin
  disk (the volume is a bind onto `/opt/kasm/data/db`).
- **Reset-root proof (twice):** the overlay was thrown away and a new one booted over the same base and the same two disks: Kasm came back healthy without a
  reinstall, with the same user id and workspace ids, and a file written in the personal workspace before the reset was there afterwards. A file written in the
  temporary workspace was not there in the next temporary session.
Problems found on the way and fixed: no network in the build guest with an emulated e1000 NIC (virtio needed); a failed build step left the VM running (now a
failure marker and poweroff); a 22-character disk serial was truncated (limit 20); the seed rolled back silently because `group_images` named removed images and
`db_init -q` was wrong; `db_init -i` recreates the DB volume without the bind (copy then swap); a stopped container held the volume; the fresh root lacked the
`kasm` user and network and `bin/start` pulled `-rolling` images (own start script, `--use-static-images`); the installer fetches two Docker plugins from the registry
even in offline mode (now packed in the base).

## Verified on a real Proxmox VE 9.2 (a QEMU guest with nested KVM; the earlier rehearsal's installed system, its disk enlarged to 128 GiB)
`baseline-kasm setup` run on it, with the base shared read-only at the installer cache's `kasm/` path:
- It checked the 16 GB base against its manifest, asked the three role volumes for room (they grew: APPDATA_ADMIN 5 GiB, APPDATA_PERSONAL 3 GiB, SESSION_TEMP
  13 GiB), registered the three directory storages, built VM 101 (4 cores, 6 GiB, sized from the 24 GiB host) with the root overlay on SESSION_TEMP and the
  two data disks on the AppData volumes, attached by serial, started it, generated the four credentials into `/mnt/USER_ADMIN/vault` (mode 0600), installed Kasm
  through the guest agent, and reported the VM's address. Kasm reported healthy.
- A second `setup` is a one-second no-op (no base check, no guest work); `baseline-kasm-setup.service` runs it under its real unit sandbox.
- **Reset-root** (`baseline-kasm reset-root`): same user id and workspace ids afterwards; a file written in the personal workspace before was there; one written
  in the temporary workspace was not.
- **Rebuild** (the VM's definition and its OS disk deleted outright, then `setup`): a new VM 101 reattached the same admin and profile disks, reused the vault's
  credentials, and the same checks passed (same ids, personal file kept, temporary file gone).
Found and fixed on the way: the AppData volumes start at 1 GiB and the growth check runs every ten minutes, which Kasm's first writes would outrun; setup now asks
each volume for room first (`ROOM_NEEDED`) and stops with the volume's own reason if it cannot be given.

## Verified from a fresh installer (rehearsal run 24, 2026-10-16/17)
A new offline cache was built (406 packages, 531 files, 18.9 GB, carrying the Kasm base and the new firmware packages), an installer ISO built from it, and the self-contained installer
run in a QEMU VM (16 GiB, 128 GiB sparse disk, no network) with the normal first-boot flow: all nine first-boot steps ran, the CONFIRM screen appeared and was confirmed, and the kiosk
showed the Proxmox login. **Without any further step**, `baseline-kasm-setup.timer` fired, and `baseline-kasm setup` built VM 100 (`baseline-kasm`, 3 cores, 6 GiB, sized from the 16 GiB host)
from the carried base, generated the four credentials into the vault, installed Kasm through the guest agent, and finished: Kasm reported healthy, eight containers were running, and all six
workspaces were seeded. The persistence and rebuild proofs above were run earlier on the same code path.
Not exercised in that run: the supported-OS list step (the ISO predated it; it is covered by unit tests only), a browser session in a workspace (the rehearsal host has no IPv4 to reach it).

## Not verified (each a step of the plan, not an assumption to hide)
- Real hardware (the Proxmox here was itself a VM; KVM-in-KVM is slower and the sizes were small).
- A browser session inside a workspace on the fresh-installer setup (the earlier proofs used the same code on a nested Proxmox that had an address for it).
- Kasm Workspaces Community Edition is free to use and is **not fully open source** (the platform's license restricts it; KasmVNC and the workspace images are
  open). Used without activation; its limits apply. The page says so.
- Smaller base: the Ubuntu desktop image alone is about 11 GB uncompressed; dropping it (or carrying only Chrome and VS Code) cuts the base to a fraction.
  Open choice for the operator.


## Update 2026-10-17: persisted layers, run modes, dehydrate/rehydrate (operator decision)
"Kasm should use overlays that persist ALL configuration and user data to allow rehydration of the VM without the VM becoming permanent; or run a VM with reset to where it was when started up."
The first build kept the OS layer disposable (on SESSION_TEMP); that is replaced. Layers, over the read-only base in INSTALLER_CACHE:
- **persisted** (all of it): the OS layer (Docker state, anything set in the VM) and Kasm's state on APPDATA_ADMIN, the profiles on APPDATA_PERSONAL. The VM itself is not permanent: `baseline-kasm dehydrate --yes` removes
  only its Proxmox definition (recording memory, cores and address) and leaves every layer; `setup` builds it again under the same VMID and address. A persisted layer records the base it was made on and is not used with a different one.
- **session** (reset mode only): a layer on SESSION_TEMP over all three, made fresh at every start, so everything done during a run is discarded and the VM comes back as it was when it started.
`baseline-kasm mode persist|reset` switches (restarting the VM); the Workspaces page has both choices and the removal. `reset-root` now discards the persisted OS layer and needs `--yes`. One action runs at a time (a lock), so the
timer that keeps the VM running cannot start it while a mode change or a removal has it stopped.
**Verified on a real Proxmox (the installed rehearsal host, scratch copy):** a fresh layout-2 setup; markers in the OS layer, Kasm's state and the profiles; dehydrate (VM gone from Proxmox, all layers kept) then rehydrate (same address,
all three markers back); reset mode (changes visible during the run, all gone after a restart); persist mode (changes kept after a restart).
Two real defects found and fixed on the way: Kasm's installer restarts Docker in quick succession and tripped systemd's start-rate limit on a slow host (the limit is lifted for the install and restored); and after a rebuild the guest
agent answers before the VM has mounted its data disks, so the installer's "already installed?" check looked at an unmounted folder (the disks are now brought up first, host-side, and in the script for the next base build).
Not yet: the script-order fix is in the source but the carried base predates it (the host-side step covers it until the base is rebuilt).

## Update 2026-10-17: the Kasm recipe (components used and not used)
Operator: build the recipe/templates so the components used and not used are known and considered when building, and a future build can adapt.
`kasm_recipe.py` is that template: Kasm's components named by the installer roles Kasm itself gives them (`db`, `app`, `agent`, `proxy`, `guac`), each with its images and a state (`required`, `used`, `unused`), the plugins, and the
workspaces. It is checked against the release's OWN `docker-compose-all.yaml` at build time: every image the release starts must have a state, and a component naming an image the release does not start is refused, so a new Kasm
version that adds a component cannot be built until someone decides what it is. The recipe is recorded in the base's manifest and the Workspaces page shows it.
What it records for this setup: the database, application, agent and proxy are required; **the `guac` role (RDP, VNC and SSH to other machines: `kasm-guac`, `rdp-gateway`, `rdp-https-gateway`) is carried but unused** by every workspace offered, because
Kasm's all-in-one install starts it; the network sidecar plugin is likewise carried and unused. Dropping the unused ones is possible through Kasm's separate roles (db, app, agent, proxy) but is not built, and the recipe says so next to them.
A recipe file (`config/local/kasm-recipe.json`, git-ignored; `config/kasm-recipe.example.json` shows it) replaces the default; the supported-OS list's Kasm entry can still name the workspaces.
**Verified against the real release:** the default recipe validates against Kasm 1.19.0's actual compose file and covers exactly the eight service images the build had been carrying by hand.
**Not decided here (to discuss with the operator): what to record about settings changes and errors, and whether that is Baseline's own SQLite or Kasm's.** Facts read from a running Kasm 1.19.0:
its database holds 87 server settings (name, title, category, value, description, whether a restart is needed; many values encrypted) with NO history of changes and no audit-log table; it keeps a `logs` table (561 rows after one test run), metrics tables
(`system_metrics`, `metrics_components`), session records and accounting; and each service writes structured JSON log files under `/opt/kasm/current/log/` (on the persisted admin disk).

## Update 2026-10-17 (later): settings, registry and telemetry (operator answers)
Operator: (1) Baseline supports the 87 server settings and builds them from scratch, stays compatible with how Kasm encrypts, remains the history and the builder, and sets itself up as a Kasm third-party registry; (2) actual values matter, counts are a report;
(3) frequency drives what Baseline builds and what it suggests, with telemetry on RAM, CPU, drivers, applications, services and OS components.
**How Kasm encrypts, and the licensing boundary (a mistake corrected).** Kasm stores settings encrypted at rest by its own API server with a key tied to the install. To answer "where and how", I read the names and constants of the compiled code inside Kasm's own image.
**That went further than I should have:** Kasm's EULA forbids reverse engineering, decompiling or deriving source code from the Software, and circumventing technological restrictions. I stopped, did not use or record what I saw, and changed approach. Baseline never implements, holds or
reproduces Kasm's key handling. The supported route is Kasm's own documented **slip-stream install**: the installer is given our `conf/database/seed_data/default_properties.yaml` (the format of Kasm's export, with its documented template variables) and Kasm itself seeds and encrypts every value. Anything
Baseline writes is therefore compatible by construction, whatever Kasm does with it in a later release.
- `kasm_settings.py`: the catalogue of all 87 settings from the release's own seed (name, category, type, default, secret or not, which services restart when it changes); overrides checked by name and type; a secret (9 of them) is never set from a recipe, it stays generated by Kasm. Round-trip checked on the
  real seed: only the chosen values change and all 133 template variables survive. The recipe's `settings` are applied this way at base build time.
- `kasm_registry.py`: builds a workspace registry in Kasm's published schema 1.1 (shape confirmed against Kasm's own public registry and its documentation) from the release's own workspace definitions. The installer's documented `--default-registry-url` is how a fresh install is told our registry's address
  (recipe `registry.enabled` + `list_url`; handed to the guest installer as a non-secret). NOT yet done: hosting the file where Kasm can fetch it, and confirming on a live Kasm that an unsigned third-party registry is accepted (the official registry is signed; third-party ones are documented only as "trust the publisher").
- `kasm_telemetry.py` + `baseline-kasm telemetry collect|report` + a 5-minute timer: a read-only probe run inside the VM reports memory, CPU and I/O pressure, disks, failed services, container restarts and memory kills, kernel driver/firmware/storage errors and Kasm's own error log lines (redacted before storage).
  SQLite on APPDATA_ADMIN: samples, events (a repeating error is ONE fingerprint seen many times), setting changes with the real old and new values (a secret's value is never stored), and usage. Counts and frequencies are computed reports. Suggestions (more memory, a core, disk full, failing services, drivers, repeating Kasm errors,
  an image nobody started in 30 days) each carry the evidence and what they buy; the one that would change a build only ever asks the person. Shown on the Workspaces page.
- Found and fixed on the way: the installer's registry-address check used a bash bracket expression wrongly and refused good addresses; the test now runs the check in bash.
Not built yet: collecting Kasm's own usage (accounting) and a settings snapshot into the history (needs endpoints confirmed on a live Kasm), merging Proxmox's own VM metrics, hosting the registry, and acting on a suggestion automatically (only described).

## Verified live, 2026-10-17 (slip-stream, registry address, telemetry feeds)
On a base built from a recipe that set `log_retention=14`, `debug_retention=2` and a registry address, installed offline: Kasm's own database held the registry address (replacing the official one), and **Kasm's own admin API returned all 87 settings with the two values exactly as set**. So slip-stream
works as documented, Kasm encrypted everything itself, and the same endpoint is the supported way to read settings back for the history.
Run inside that live Kasm: the telemetry probe (memory, CPU and I/O pressure, disks, Kasm's real error log lines), the settings script (82 values and 6 secrets marked; a secret's value never left the VM), and the accounting query (empty: no sessions yet) all work.
The live data found two defects, both fixed with regression tests: the registry-address check in the installer (a bash bracket expression) refused good addresses, and the redaction mangled an ordinary log line ("decoding token: Not enough segments"); Kasm's JSON log lines are now reduced to their message, so request addresses and user agents are not kept.
Collection now covers: probe (metrics, failing services, container restarts and memory kills, kernel driver/firmware/storage errors, Kasm errors), settings (values kept on change; a secret is noted once, never its value), and usage and failed sessions from accounting (no user name or address read).
Still open: hosting the registry file where Kasm can fetch it and confirming that an unsigned third-party registry is accepted; merging Proxmox's own metrics for the VM; the build adapting from the usage history (today it only suggests, and only the person approves).

## Update 2026-10-17: Baseline as a Kasm workspace registry, verified on a live Kasm
**Result: a real Kasm 1.19.0 accepted Baseline as a third-party registry and listed all five workspaces (Browser, Development desktop, VS Code, Firefox, Terminal), served by Baseline's real web handler.** It marks the registry `is_verified: false` (Kasm's own is signed; ours is not) and reports no error.
What it needed, learned from Kasm's own log and API:
- Kasm first reads `<registry>/versions.txt` (the schema versions offered: ours is `1.1`) and then `<registry>/1.1/list.json`. Without `versions.txt` it reports "does not appear to have a valid schema list". Plain http was accepted. It fetches when an administrator lists or updates registries (`do_auto_update` is on), not by itself at install.
- `kasm_registry.files()` produces both files; the base build writes them next to the base (`registry/`), the offline cache carries them (covered by its manifest), and Baseline's web app serves them.
**The one public exception in the web app, deliberate:** `GET /kasm-registry/versions.txt` and `GET /kasm-registry/1.1/list.json`, no login, because Kasm's servers fetch them and cannot sign in. They list only workspace names and images. Exactly those two paths, GET only, one folder, links never followed, a missing or malformed file is a plain 404; the `list_url` inside is set to the address
the client used (a Host header that is not an address is ignored). Everything else still needs a session (tested: the exception opened nothing else).
The address Kasm is told at install is the recipe's `registry.list_url`, or, when empty, this host's own address on the VM bridge (`vmbr0`) on port 8100; if there is no IPv4 address to give, none is offered rather than a wrong one.
Test-harness note (not a product fact): QEMU's `guestfwd` to a TCP target serves one connection and then stalls, which made Kasm time out fetching `list.json`; direct reachability showed the registry itself was fine.
Not yet: workspace icons (entries name `<image>.png`; nothing serves them), a signature, and reaching the registry across a real Proxmox bridge with Baseline's web firewall rule in between (the rule allows private networks to the web app, which is expected to cover the Kasm VM, unverified).
