# 258 - Prebuilt OS environments with interchangeable application containers (requirements; not built)

Operator, 2026-10-12, after testing PC601 on a laptop. Recorded verbatim in intent; no code exists for this yet.

## What was asked
1. After install there is a VM or CT for **Ubuntu**, with the **agreed default applications installed and configured**.
2. The **user information for the OS is in the overlay** (USER_PERSONAL / APPDATA_*, never USER_ADMIN - DR257).
3. **Every OS ISO the drive carries is spun up beforehand** and configured with the default applications.
4. Each application is available in **its own application container, interchangeable**, with **adapters** for the operating systems that
   need a helper.
5. The browser profile applies to all users, no exception (decided separately: the machine's browser window is one profile on USER_ADMIN,
   settings by Chromium managed policy; per-user profiles live under /home, which is on USER_ADMIN).

## What already exists to build on
- `application_bundle.py`: the agreed apps (vscode, spotify, chrome, chatgpt, claude) as verified, per-app bundles with recipes.
- `ubuntu_environment.py`: Ubuntu VM from a pinned cloud image, disposable root, retained /home, one authenticated admin account.
- `vm_provision.py` / `pct_provision.py`: guest creation on `session-temp`; DR257's layering (a read-only base, an overlay per user/OS on
  USER_PERSONAL or APPDATA_*, session layer in SESSION_TEMP) is designed and proven to work natively in Proxmox, not yet built.
- OS ISOs carried on INSTALLER_CACHE (storage `installer-cache`), offered at install time.

## Open decisions (answers needed before building)
1. **Which apps, which OS.** The five apps above for every OS, or per-OS lists? Ubuntu first, the rest follow the same recipe?
2. **"Spun up previously".** At build time (inside the installer VM, so the drive ships with ready bases) or at first boot on the real
   machine? Build-time is faster for the user and uses the cache; first boot is cheaper to carry. Disk impact: one prepared base per OS.
3. **Application container form.** One OCI container (Podman/Quadlet) per app exporting its display to the OS guest via an adapter (Wayland
   socket / VNC / Xpra), or the app installed inside the guest from a per-app overlay layer? "Interchangeable" suggests the first.
4. **Helper OSes.** Which of the carried images need a helper (a Windows-class guest, an installer-only live image such as the rescue
   image, a distro without a package the app needs) and what the adapter is for each.
5. **Credentials in the overlay.** The OS user account is created from USER_PERSONAL data at first run; the base image carries none.
6. **Network at build time.** Several apps are downloaded (not distro packages): build-time needs internet or the offline cache must
   carry their bundles (the cache builder already collects some).

## Not decided here
Sizes (volumes only grow when used, DR257), the overlay's association table (USER_DATA holds the association to APP_DATA per user and OS).

## Queued by the operator, 2026-10-12 (second laptop review) - not built
- **A Baseline browser page equivalent to the TUI**: hardware, network, tether, sensors, VMs and the AI chat as web pages, so the browser
  alone is enough. Today the browser has `/console` (one button that shows the text console, loopback only) and the web app's own pages.
- **Rename the host root volume to SUBSTRATE** (DR257 step 3). Until then Proxmox shows the root as the storage `substrate`
  (`/var/lib/vz`, the root filesystem's real size) and `local` is disabled; the 1 GiB `baseline_substrate` volume still holds only the
  storage policy.
- **Containers and VMs ready to use** (this record's main subject): nothing is prebuilt yet.
- **AI providers and harness**: a fresh drive has no provider credentials (`/etc/baseline/harness.env`) and no harness installed, so
  everything shows unconfigured. Needs a decision on where credentials come from (USER_ADMIN) and which harness ships.

## Operator decisions, 2026-10-12 (third review) - recorded
1. **Applications:** all compatible applications for all OSes the drive provides (answers question 1 above). Compatibility comes from
   `application_bundle` targets (Ubuntu 24.04/26.04, Debian 13 amd64 today); an OS outside them gets the applications through a helper
   adapter, not silently none. Not built.
2. **Credential vault:** secrets live in `/mnt/USER_ADMIN/vault` (the host's own) and `/mnt/USER_PERSONAL/vault` (a person's own).
   BUILT: `vault.py` (private files, provider status and the Claude harness read it first) and, from 2026-10-13, encryption at rest
   (`vault_crypto.py`: scrypt-derived keys, AES-256-CTR through openssl, encrypt-then-MAC; one passphrase set on `/vault`; unlocking
   writes plaintext only to the RAM-backed `/run/baseline/vault`). The passphrase is not stored: losing it loses the sealed secrets.
3. **Browser sign-in to AI providers:** BUILT for Claude (`provider_setup.GuidedSetup` runs `claude setup-token`, shows its
   claude.com link, passes the code back, stores the token in the vault; `/ai-setup`). Verified against the real CLI up to the sign-in
   link (`tests/integration/verify_claude_signin_link.py`); the human sign-in itself is the operator's. OpenAI, Gemini and OpenRouter
   offer no third-party sign-in grant for an unregistered app, so `/ai-setup` links to each provider's key page and stores the pasted key.
4. **TUI parity in the browser (all tabs):** matrix below.

| TUI tab / key | Browser | State |
|---|---|---|
| Hardware | `/hardware` | exists |
| VMs | `/vms`, `/containers` | exists |
| Sensors | `/sensors` (rows shared with the TUI through `sensors_view`) | BUILT |
| Network (+ providers, IDs `i`) | `/network` (rows shared through `network_view`) | BUILT; IDs toggle open |
| Tether `t` | button on `/network` (wording shared via `chat_page.tether_message`) | BUILT |
| Chat (harness select, ask) | `/chat` through the harness registry (Claude and OpenCode); streaming open | BUILT, streaming open |
| Console (hardware/network/tether/ask/grant write) | `/shell` (`console_commands`, same wording) | BUILT |
| `p` Proxmox / return to console | `/console` | BUILT |
| `r` refresh, `c` copy | page reload / browser | n/a |

## 2026-10-13: environments catalogue
`/environments` lists every carried OS image against the five guest applications (native / helper / none) and whether an environment of
that name exists. It claims nothing is installed. The prebuilt, configured environments themselves remain unbuilt (the work above).

## Operator requirements, 2026-10-14 (fourth review)
- **Audio and Bluetooth in the Proxmox GUI session** (input, output, tether): `/audio` lists PipeWire outputs/inputs and BlueZ devices and
  runs connect/disconnect/pair/trust/remove with validated addresses; `harness_install.run_extras` installs pipewire, pipewire-pulse,
  wireplumber, bluez and libspa-0.2-bluetooth once online (the offline cache did not carry them). NOT built: Bluetooth PAN tether
  (needs a bnep interface and DHCP through the existing tether path) and routing guest audio into VMs.
- **Two-factor** for Proxmox users: `/security` (TOTP, registered only after the person's own code verifies).
- **Ceph packages**: `/ceph` runs `pveceph install` (needs the internet). Cluster creation (monitors, OSDs) is left to the operator.
- **Not built**: prebuilt VMs/containers (above), a Proxmox "Create VM" that applies Baseline's agreed recipes (Proxmox's own dialog is
  stock), management beyond listing in the TUI's VMs tab, and "Proxmox settings stored" (unclear what is expected: needs the operator).

## Operator answers, 2026-10-14 (recorded in DR259)
- Ubuntu is one of about ten operating systems, not the special case; the user's settings (USER_ADMIN and user data) are shared from one OS
  to the next and configure each OS and its applications from the configuration, the user data and the app data.
- Proxmox's own state is overlay data on USER_ADMIN; non-public settings and data go only to USER_ADMIN, USER_DATA, APP_DATA and
  SESSION_TEMP. A phone-style web launcher with a right-click menu per VM/OS and three run modes. Built as a first slice: see DR259.
