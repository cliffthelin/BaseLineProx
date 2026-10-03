# Five applications and remaining environment workflows

Current2026-10-03 after DR133. All five native applications were installed and
rendered on Ubuntu24.04.5 and Debian13.7 in disposable KVM; this is not physical
installation or authenticated account/playback/chat verification.

| Area | Implemented and verified | Planned, not done |
|---|---|---|
| VS Code | Exact publisher archive/source lock, private launch, five-setting native capture/apply, fresh payload/private restore, Ubuntu/Debian GUI | Keybindings/snippets, extensions and dependency locks, broader settings, Windows/macOS/container adapters |
| Spotify | Official native DEB lock/extraction, private D-Bus and GUI, retained private home, Baseline scale recipe | Native settings inspection/export/apply and playback/authentication tests; Spotify does not actively support Linux |
| Chrome | Native DEB lock/extraction, private profile, homepage capture/apply, explicit homepage launch after crash, Ubuntu/Debian GUI, optional code-only URI browser | TLS trust setup for Proxmox, account/keyring migration, richer settings/dependency locks, graceful shutdown/recovery |
| ChatGPT | Official Linux-preview DEB, private native GUI on both OSes, retained home and Baseline scale recipe, declared codex callback | Native preference export/apply, authenticated login/chat/callback, runtime SDK classification/locks, other platforms |
| Claude Desktop | Official Linux-beta DEB, private native GUI on both OSes, retained home and Baseline scale recipe; actual public browser/native claude action dispatch | Native preference export/apply, authenticated callback/chat, broader platforms and reviewed MCP configuration |
| App persistence/isolation (74) | Per-app writable HOME/XDG, read-only code, namespace/private bus, explicit exchange/URI grant; stopped Ubuntu profile restore; actual Debian root rebuild retained five identities and30,827 regular files | Managed physical mounts and distinct Linux service identities, full X11/audio/network boundaries, actual authenticated migration and live/database consistency |
| Recipe builder (76) | Strict five-app native locks, suite compose/retarget/build, reviewed native VS Code/Chrome capture/apply, desktop entries; actual clean Debian root reacquisition/install | General OS recipe-stack integration, durable web guest reconciler, dependency/extension locks, richer native adapters, interrupted-download quarantine/recovery and storage-class routing |
| Durable recovery (75) | Earlier VM/LXC jobs and scoped recovery; app launch locking and incomplete generations explicit | App durable jobs, candidate promote/rollback, incomplete initial/restore repair, graceful app checkpoints and power-loss proof |
| Backup/restore (59/60) | Earlier stopped LXC restore on separate virtual disk; stopped app archives restored/tested on Ubuntu | Full split-VM coverage, encrypted recurring private app sets, authenticated/keyring restore, independent physical destination |
| Replacement device (77) | Requirement and queue; Debian retained-home root replacement is a narrower same-device proof | Independent encrypted remote destination, original-device-independent keys/identity, manifest, fresh hardware/storage mapping and actual original-unavailable restoration |
| Environment deployment (72/73) | Ubuntu/11 LXC-family virtual proofs; native apps on Ubuntu/Debian | Full physical/ordinary-network firstboot, requested other OS installs, Harvester adapter |

The shared five-app lifecycle now exists as software. It does not mean every
native preference or all planned environment features are complete. Three apps
currently share only Baseline launch options in portable recipes; their native
profiles stay private and are retained/archived separately. No opaque profile
or account tokens are exported into shareable configuration templates.

Next: ship the CLI/docs in the installer, provide editable storage/OS/app defaults,
and turn the current actual Debian/Ubuntu evidence into a user-operated walkthrough.
Then wire durable guest reconciliation and richer native capture. The existing
physical six-volume layout must be discovered by UUID/serial, not overwritten to
match an imagined layout. No AI runtime is required for these software workflows.

DR134 implements current app/tasker source and documentation staging, two
registered Ansible roles, editable app-recipe autofill and revision-scoped
compatibility observations. Actual tasker runs: Debian five apps, Ubuntu Chrome;
both changed=0 repeats. This closes the absence of reusable app task execution,
not the general OS/physical installer or durable guest reconciler. See the
[walkthrough](../BASELINE_BUILD_WALKTHROUGH.md).
