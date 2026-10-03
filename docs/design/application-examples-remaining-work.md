# VS Code / Spotify and remaining environment workflows

Current2026-10-02 after DR130. Evidence levels are separate from roadmap.

| Area | Done | Planned, not done |
|---|---|---|
| VS Code configuration | Five-setting JSONC preview/allowlisted export, CLI new-profile staging; actual installed Linux VS Code consumed those settings in fresh profile | Verified clean package install, app recipe binding, VM/container capture/apply, keybindings/snippets, extension/source/dependency locks, richer reviewed settings, cross-OS tests |
| Spotify | Selected second example; official install/support documentation reviewed | Config inspection/export adapter, portable/private classification, source/install recipe, fresh apply/playback readiness without publishing credentials, per-platform tests |
| App persistence/isolation (74) | Planner path corrections; no runtime confinement claimed | Actual mounted AppData ownership, app identities, profile migration, isolated launch, two-app denial and explicit sharing, rebuild/reset retention |
| Recipe builder (76) | Narrow recipe validation/export/stack lock/CLI/web; managed Ubuntu deb metadata inspection; VS Code settings artifact | Source verification/acquisition and package locks, broader schema/composition, reviewed capture promotion, deterministic guest reconciler, actual fresh VM builds and candidate promote/rollback |
| Durable recovery (75) | VM/LXC jobs, interruption review, scoped rebuild/login recovery | Incomplete initial create/template/restore repair, running partial/orphan/native task reconciliation, broader guest/backend adapters, power loss |
| Backup/restore (59/60) | Stopped LXC retained-data restore on separate virtual disk, same-host base | Full split-VM/app backup, encrypted recurring retained sets, cross-host/base reacquisition and actual independent physical off-drive recovery |
| Replacement device (77) | Requirement/queue only | Independent encrypted remote destination and key/identity recovery, manifest, replacement storage mapping, restore wizard, originals unavailable proof |
| Environment deployment (72/73) | Scoped Ubuntu and11 LXC-family KVM evidence | Full shipped provision/ordinary-network/physical firstboot, requested distro installs/retained mounts, Harvester adapter |

Next application sequence: verified VS Code installation source and recipe binding,
managed fresh target install/apply with actual launch checks; then richer capture
and retained-state/isolation tests. Spotify requires its own version/platform
adapter, not copying VS Code assumptions. Fresh-profile success is not fresh VM
installation, total-device-loss recovery, or app confinement. No AI runtime needed.
