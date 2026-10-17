# 266 - Queue: Docker Sandbox kits, the service host, and the LinuxServer apps (after the Kasm and OS work)

Date: 2026-10-17. Status: QUEUED by the operator. Nothing below is built. The operator's order: finish the Kasm and per-OS custom-build work first, and keep these expansions queued. Analysis behind every item is in DR264 and DR265.

## Operator answers to DR265's questions (2026-10-17), recorded as given
1. "Lets queue up the install and support for sbx."
2. "Yes Docker account is acceptable need needed from Proxmox." Read as: a Docker account is acceptable, and it is signed in from the Proxmox side (the sandbox host VM); Baseline never types its password, the person does the device-code sign-in. If "need needed" meant something else, it is the operator's to correct.
3. Yes: Selkies apps start with the reach-through-the-Kasm-Web-App-Gateway route, then proot-apps for the 57 it covers, per-app rebuilds only for the few that matter.
4. Yes: a service-container host on Proxmox (LXC or VM) with constant volumes for each service's `/config`, fronted in Kasm by the Web App Gateway, is next after kits.
5. Priority of the apps: browsers, developer tools, "I tools" (read as AI tools; to be confirmed), media, AI image tools, office tools, in that order. "If a helper install setup wrapper can be made for each, that is to be added to recipes for each."

## The queue, in order
1. **Docker Sandbox support (`sbx`)**: first the kit catalogue and review (kits pinned by manifest digest and a hash of `spec.yaml`, shown with install commands, network allow list and credentials, refused when changed until read again; kits and what their install downloads mirrored into a Distribution store); then the Ubuntu 24.04 sandbox-host VM on Proxmox with nested KVM and `docker-sbx`, layered like the Kasm VM (read-only base, persisted OS layer on APPDATA_ADMIN, optional per-run layer, dehydrate and rehydrate), with the APPDATA_PERSONAL constant volume mounted where sandbox workspaces live and sbx state on the admin layer; then a Baseline page to run a kit in a sandbox on a chosen workspace folder, list, stop and remove; then the Kasm front end (a Terminal workspace to the host, Web App Gateway entries for kit ports). Baseline's own kit runner is a later second runner, not the first.
2. **Service-container host**: an LXC or VM with Docker on Proxmox, one constant-volume folder per service for `/config`, a catalogue entry per service, Web App Gateway entries in Kasm.
3. **The Selkies apps**: Gateway reach-through for all, proot-apps for the 57 it covers (to be tried first on a Kasm base), rebuilds for the few that matter.
4. **The apps themselves, in the operator's order**: browsers, developer tools, AI tools, media, AI image tools, office tools. For each app a **helper install and setup wrapper**: a recipe entry that says how the app is installed and configured on each route that applies (a service container with its constant volume, a Selkies container behind the Gateway, a proot-app in a Kasm base, a sandbox kit), with the settings it needs and where its data lives, so adding an app is adding one recipe entry. The catalogue to choose from is `docs/design/data/linuxserver-target-list-2026-10-17.json`; the maintained route for each is chosen app by app (never LinuxServer's deprecated Kasm-tagged images, DR265).

## To confirm when this is picked up
"I tools" meaning; the list of apps within each category (the catalogue has 227; name the first handful per category); AI image tools are not in the LinuxServer list as such (the catalogue has none named that way), so where they come from is open.
