# 268 - Sandbox kit catalogue and the application catalogue (first steps of the queue, DR266)

Date: 2026-10-17. Status: both built and tested; the first category of applications (browsers) checked on the ready-made bases (DR267) as far as the verification route allows. The sandbox host VM and `sbx` itself are still queued and NOT built.

## 1. Docker Sandbox kits as a reviewed, pinned catalogue (`sbx_kits.py`, `baseline-sbx-kits`)
- Reads a kit through the plain registry API: anonymous pull token, size limits, and every blob (the spec and each file layer) checked against the digest the manifest names. No Docker account and no `sbx` are involved in reading. Checked live against Docker Hub: `sbx/task-kit` and `sbx/code-server-kit` read correctly (the first is two findings, the second five).
- **A kit is only used when the recipe names it, pins it to the manifest digest a person read (`reviewed`, the first 16 hex characters), and accepts each finding by name.** The findings are: `install:runs-as-root`, `install:pipes-a-download-to-a-shell`, `install:downloads-without-a-checksum`, `startup:runs-commands-at-every-start`, `network:allows-outbound-hosts`, `network:wildcard-host`, `credentials:asks-for-<service>`, `security:privileged`, `image:not-pinned-by-digest`. A kit that changed since it was read is left out with its new digest and what it now does. Real example of why: `code-server-kit` downloads and pipes an install script to a shell as root with no checksum, and `task-kit` pins a version and checks its SHA-256.
- A kept copy lets a build with no internet still use a kit it has seen. Nothing is installed or run; `baseline-sbx-kits review <ref>` prints the digest to copy and what the kit declares.
- Not done: mirroring the kit and what its install downloads into a registry store (needs the Distribution mirror, DR264), the sandbox host VM with `docker-sbx`, a page to run a kit, the Kasm front end.

## 2. The application catalogue and the install helper (`app_catalogue.py`, `config/app-catalogue.json`, `baseline-app-install`)
- One entry per application, with a route per kind of system: the system's own repository (`apt`, `pacman`), declared in a NixOS configuration (`nix`), Flatpak (`flatpak`), a portable app inside a Kasm desktop (`proot`), or a service container behind Kasm's gateway (`container`, LinuxServer's maintained images only, never the deprecated `kasm` tags). Each system has its own preference order; Ubuntu prefers Flatpak for browsers because its repository browsers are snaps; a route restricted with `only` is skipped elsewhere; a dead end is reported, not guessed. `install_script` writes a non-interactive, fail-fast script from validated catalogue values only; `baseline-app-install show|run` prints it and (as root) runs it.
- First category, as the operator ordered: **browsers** (Firefox, Chromium, Brave, LibreWolf, Vivaldi). The other categories (developer tools, AI tools, media, AI image tools, office tools) are empty until the first handful of each is named.
- Every Flatpak id was checked against Flathub's API; the five nixpkgs attributes were evaluated on the NixOS base.

### What was run on the ready-made bases (each on a throwaway layer over the base)
| System | Route | Result |
|---|---|---|
| Debian | apt, Chromium | installed (`dpkg` says installed) |
| Ubuntu | Flatpak, Chromium | Flatpak and the runtime installed, Chromium listed |
| CachyOS | pacman (`-Syu`), Chromium | installer exit 0 |
| NixOS | nix attributes | all five evaluate against the base's own channel (declared at build time, not installed at run time) |
| Bazzite | Flatpak, Firefox | **not verified**: the guest agent runs under SELinux confinement there and is refused write access to `/var/lib/flatpak`, and `setenforce` is refused too; the route is the system's own standard one |
| Omarchy | pacman | not run (no guest agent on that base) |

### Things found
- `apt-get update` exits 100 when any source cannot be read. The Debian base still had its installer-DVD source, so the first version of the apt script stopped before installing. The script now reports an update error and lets the install decide, and the Debian base build now removes the `cdrom:` lines when it tidies (a rebuild is needed for that part to reach the carried Debian base; the script copes with the existing one).
- Ubuntu's base had no apt lists (tidy removes them), so installing Flatpak needed an `apt-get update` first.
- On Arch-family systems `pacman -Syu` is used rather than `-S` after a stale database, which is also what a partial-upgrade policy wants; it upgrades the system as part of the install.

## Queue (DR266) now
1. Sandbox kits: **catalogue and review done**; mirror, sandbox host VM, run page, Kasm front end remain.
2. Service-container host: not started.
3. Selkies apps: not started.
4. The applications: **framework and browsers done**; the other categories wait for names.
