# 261 - The operator's list of supported operating systems, and what Kasm is and is not for

Date: 2026-10-16. Status: the list mechanism is built and unit-tested; the list itself is the operator's to fill in. The Kasm assessment is a judgement from what
DR260 verified, not a new test.

## Operator instruction (2026-10-16)
"Keep it and add the list of other OS to support; they should be git ignored. Can Kasm be configured to do what I am trying to do? It's the current best
solution for what I want."

## Decision
- **Keep Kasm as built (DR260), with the full carried workspace set.** The base stays about 15.5 GiB.
- **The list of operating systems to support is the operator's own and is never committed.** Working copy on the build machine: `config/local/supported-os.json`
  (`/config/local/` is in `.gitignore`; a test fails if anything under it is tracked). Installed host: `/mnt/USER_ADMIN/config/supported-os.json` (non-public
  host configuration lives on USER_ADMIN, DR257). `config/supported-os.example.json` is committed and shows the shape. `os_list.py` reads and checks it
  (id, name, kind `vm`/`container`/`kasm`, optional ISO file name and notes) and assumes nothing when there is no list.
- The working copy holds only what the product already names (Ubuntu Desktop and Server, Debian 13, Kasm). **The remaining systems are not in the repository or in
  any message so far; the operator adds them.** Nothing reads the list yet to drive the launcher or the installer cache; that is the next step once it is filled in.

## Can Kasm do what is being built? (candid)
It covers one part well and is not the whole answer.
- **Fits:** browsers, desktops and editors streamed to any browser, one session per user and workspace, with profiles kept on the user's own volume and the platform
  state on the admin volume. DR260 verified this, including that a reset or rebuilt operating system keeps the users, workspaces and a personal profile.
- **Does not do, and is not meant to:** run whole operating systems as managed virtual machines (Proxmox does, and the launcher in DR259 fronts them); share one
  layered settings model (timezone, locale, theme, display scale, swap, per-application settings) across about ten operating systems (that is Baseline's layered
  settings, DR259; Kasm's settings are its own, per workspace); provide the volume roles, overlays and recovery rules (those are what Kasm was fitted into).
  Kasm can reach an existing machine over RDP, VNC or SSH as a "server" workspace, which is a way to put a Proxmox VM's desktop in the same browser portal if wanted;
  that is not built.
- **Open-source caveat (unchanged):** Community Edition is free but not fully open source. If that becomes a constraint, the streaming layer and workspace
  images are open, and the VM, volumes and persistence design here do not depend on Kasm's edition.
- **Conclusion:** keep it as the browser-and-desktop-workspace component inside the Baseline design, not as a replacement for the VM host and launcher.
