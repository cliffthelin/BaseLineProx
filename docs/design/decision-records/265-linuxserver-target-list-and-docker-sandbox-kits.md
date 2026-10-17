# 265 - The LinuxServer.io target list, and Docker Sandbox kits as a first-class workload

Date: 2026-10-17. Status: INVESTIGATED and recorded; the choices at the end are the operator's before anything below is built. Corrects DR264: its default of LinuxServer's two Kasm-tagged browsers is withdrawn (see "Correction"). Data: `docs/design/data/linuxserver-target-list-2026-10-17.json`.

## Operator direction (2026-10-17)
1. The target is the whole LinuxServer.io repository list (https://github.com/orgs/linuxserver/repositories?type=all), not two browsers.
2. Docker Sandbox kits must not be left out. They must work either in Kasm or from Proxmox, and use the constant volumes (the persistent, user-owned layers).

## Correction to DR264
The `:kasm` images behind LinuxServer's registry are **deprecated by LinuxServer**: the `kasm` branch of `docker-chromium` and `docker-firefox` carries an `init-deprecate` service that prints "This image is deprecated. We will not offer support for this image and it will not be updated.", and `readme-vars.yml` sets `project_deprecation_status: true`. Their KasmVNC base image has not been pushed since 2025-07-12, and their registry was last modified 2025-09. I had read the registry but not those repositories before making the two browsers the built-in default. An unpatched browser must not be a default, so the built-in and example recipes take **no** outside source now and the example says why. The import mechanism (kasm_sources) stays: it is what any maintained registry would use.

## The list: 321 repositories, what they are (read from the organisation today)
- 29 are archived. 68 are not `docker-*` container repositories (libreelec, nano, templates, proot, kclient and similar); of these only `proot-apps`, `sealskin-apps` and `selkies-layers` bear on workspaces.
- The 227 live `docker-*` repositories fall into four kinds (counted from each repository's `Dockerfile` base image and `readme-vars.yml`):

| Kind | Count | What it is | Examples |
|---|---|---|---|
| Graphical apps on **Selkies** | 96 | A desktop app streamed by LinuxServer's own Selkies base on ports 3000/3001 with its own sign-in. NOT KasmVNC, so not a Kasm container workspace as built. | 21 games and emulators, 11 browsers, 7 developer tools, 5 chat, 5 office, CAD and 3D, image and video editors, Thunderbird, KeePassXC, Wireshark, Webtop |
| **Services with a web UI** | 97 | An ordinary service container (Sonarr, Nextcloud, Bookstack, Duplicati ...) with its own web page. Nothing to stream. | media managers, downloaders, wikis, monitoring, books, backup |
| Services with no web port | 12 | Daemons and tools (fail2ban, ddclient, duckdns, plex ...). | |
| Infrastructure | 22 | Base images, CI and build tooling, templates, docs. | not workloads |
Only two repositories (`docker-chromium`, `docker-firefox`) have a `kasm` branch; no others ever will, as the line is deprecated.

## How each kind can reach a Kasm user (verified in Kasm's documentation, not tried live)
- **Service web UIs (97)**: Kasm's **Web App Gateway** serves "any web app" through an isolated browser container as long as Kasm can reach it, and a **Link** workspace is a plain URL. So these need a place to RUN the container (a Docker host or LXC on Proxmox, using the constant volumes for `/config`) and a catalogue entry that points Kasm at its address. This is the natural fit and needs no change to the images.
- **Selkies GUI apps (96)**: three routes, none free.
  1. Run the container as it is (Docker on Proxmox, `/config` on a constant volume) and reach it through the Web App Gateway: Kasm streams a browser that shows LinuxServer's own stream. Works for all 96 with no rebuild; it is a stream inside a stream (some added latency), and the app's own sign-in applies.
  2. **proot-apps**: LinuxServer's catalogue of 122 portable apps (57 of the 96 are in it: browsers, GIMP, Blender, LibreOffice, Kdenlive, KeePassXC, VS Code and more) installable with no privileges into `$HOME`, which Kasm already persists per user. One maintained Kasm-based "app desktop" workspace plus proot-apps would give those 57 without one image each. Not tried; it assumes proot-apps runs on a Kasm base (it asks only for curl and bash).
  3. Rebuild each on a maintained KasmVNC base (`kasmweb/core-*`): per-app work and a rebuild stream; only worth it for the few that matter.
- **Infrastructure and no-web services**: not workspaces.

## Docker Sandbox kits (what they are, from Docker's documentation and the Docker Hub registry today)
- A kit is an **OCI artifact** (`artifactType application/vnd.docker.sandbox.kit.v2`; its `spec.yaml` is the artifact's config blob; optional `files/` in one small layer). Samples read from `docker.io/sbx/*`: `task-kit`, `code-server-kit`, `playwright-kit`, `claude-ollama-kit` are all a few KB and pull anonymously over the ordinary registry API. 546 are published, all by Docker. A **Distribution registry stores them as they are**, so the same registry that mirrors images is where kits would be kept.
- A `spec.yaml` declares: `kind` (`sandbox`, a whole agent, or `mixin`, added to a base agent), the base `image` (needs a non-root `agent` user, UID 1000, sudo), `setup.install` (commands, run as root by default, once) and `setup.startup`, `environment`, `files`, `ports`, `volumes` (block-backed or tmpfs, size, attached only at creation), `credentials` (injected by a host proxy; a kit cannot read host files or environment), and `permissions.network` allow and deny.
- **Most kits are not self-contained**: `setup.install` downloads from the internet when the sandbox is created (code-server from `code-server.dev` and GitHub; Task from a pinned GitHub release with a SHA-256). The kit lists those hosts in its network allow list. Offline use needs what they download mirrored too; kit signatures cover `spec.yaml` and `files/` only, not what the install fetches, and Docker says to pin those by digest.
- **The runtime is Docker's `sbx`**: one microVM per sandbox, each with its own Docker daemon and image cache; workspace directories are passed through (virtiofs) at the SAME absolute path as on the host; stopping keeps everything, `sbx rm` deletes it. On Linux it needs KVM and an Ubuntu 24.04 or later host (Rocky 8 packages exist; Debian is not listed; derivatives are unsupported), nested virtualization if the host is itself a VM, the `docker-sbx` apt package, and "sign in to Docker" (`sbx login`, a device-code flow) is a stated prerequisite. **The binary is proprietary (Docker Inc.)**, so Baseline would install it from Docker's repository on the person's machine and never redistribute it. The kit format and CLI are stated to be subject to change. Docker warns against network-attached storage for a workspace because every read and write crosses the network.

## What this means for "in Kasm or from Proxmox, on the constant volumes"
- **Not inside Kasm.** A Kasm workspace is a container; a sandbox is a microVM that needs KVM. Kasm is the right FRONT END (a Terminal workspace on the sandbox host; the Web App Gateway or a Link to a kit's published port, for example code-server on 8080) but not the place sandboxes run.
- **From Proxmox, as its own VM** (recommended): an Ubuntu 24.04 "sandbox host" VM with nested virtualization, built with the same layered pattern as the Kasm VM (read-only base, a persisted OS layer on APPDATA_ADMIN, an optional per-run layer in reset mode, dehydrate and rehydrate). The **constant volumes** are then: the APPDATA_PERSONAL disk attached to that VM and mounted where sandbox workspaces live (so `sbx run` workspaces and kit `volumes` survive removing a sandbox AND rebuilding the VM), and the sbx state directory (the sandbox VM images and their Docker caches) on the APPDATA_ADMIN layer. A workspace stays on a local disk, never on the network, as Docker advises.
- **Directly on the Proxmox host** is possible (Proxmox has KVM, so no nesting) but puts a proprietary third-party tool, its Docker repository and a Docker sign-in on the hypervisor, on a distribution Docker does not list. Not recommended.
- **Trust and review, as for registries**: a kit installs software as root and can ask for credentials and network access. Baseline would keep a catalogue of the kits the person names, each pinned to the kit's manifest digest and a hash of its `spec.yaml` (reviewed by a person, shown with its network allow list, install commands and credentials), turn on `kit.requireSignature` and `kit.trustedSigners` where the publisher signs, and refuse a changed kit until read again, exactly as kasm_sources does for registry workspaces.
- **An alternative that needs no proprietary tool**: Baseline's own kit runner (Docker containers on a Proxmox LXC or VM, applying a kit's image, install, files, ports, volumes and network rules itself). It needs no Docker account and works offline, but is a container, not a microVM, so weaker isolation; Baseline would have to supply the credential proxy and egress policy that `sbx` provides; and it chases a format Docker says will change. Reasonable as a second runner later; not as the first.

## Build order if the operator agrees (nothing here is built)
1. Kit catalogue and review (pure Python, testable with no `sbx`): fetch a named kit from a registry, store its digest, spec hash and report; mirror it into the Distribution store with what its install downloads.
2. Sandbox host VM (Ubuntu 24.04, nested KVM, `docker-sbx`), layered like the Kasm VM, with the constant volumes mounted and sbx state on the admin layer; Docker sign-in done by the person, never typed by Baseline.
3. Baseline page to run a kit in a sandbox with a chosen workspace folder, list sandboxes, stop and remove them.
4. Kasm front end: a Terminal workspace to the sandbox host and Web App Gateway entries for kit ports.
5. Service-container host (LXC or VM with Docker, `/config` on constant volumes) for the 97 service web UIs and the Selkies apps, with Kasm Web App Gateway entries.

## Decisions for the operator
1. For sandbox kits: official `sbx` in an Ubuntu 24.04 VM (proprietary, Docker sign-in, nested KVM, real microVM isolation), or Baseline's own runner (open, offline, containers only), or `sbx` first and the runner later (recommended)?
2. Is a Docker account (the `sbx login` prerequisite) acceptable on a machine that otherwise holds no outside accounts, given Baseline can never type its password?
3. For the 96 Selkies apps: start with the reach-through-the-Web-App-Gateway route (all 96, no rebuilds), add proot-apps for the 57 it covers, and leave per-app rebuilds for the few that matter?
4. For the 97 service web UIs: a service-container host on Proxmox (LXC or VM) with constant volumes for each service's `/config`, fronted in Kasm by the Web App Gateway, as the next thing after kits?
5. Which of the 227 do you want first? A short list beats all 227: say the ones, or the categories (browsers, office, media, emulators, developer tools).
