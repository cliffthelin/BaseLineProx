# DR172 — Make the Installer a tab-free environment desktop

2026-10-08. This corrects DR171's implementation after the operator clarified
that every section and environment belongs in the vertical icon rail. The
horizontal strip is reserved for the selected group's shortcuts; it is not a
second navigation row. VM/container selection lives in the rail, and the main
surface combines drive assignment, Proxmox, operating system, hardware profile,
drivers and applications for the active environment. Each environment has its own
settings modal containing these six related setup blocks and its editable name;
the default `testvm1` is labeled as a setup draft, not a running guest.

The desktop mode removes the environment tab strip, legacy text navigation and
unrelated administration links from the environment rail. The rail contains
only the active VM/container picker, seven configuration groups (applications,
operating system, drive assignment, Proxmox, hardware, drivers and advanced settings),
and the add-environment/Object Manager actions. The main surface presents six
setup cards and an environment-wide settings modal; a Setup group mirrors them in the horizontal icon strip. Object
Manager opens with all object types grouped together, rather than an empty
Drivers-only view. Click selects available catalog objects; right-click opens
settings, with detailed controls collapsed under Advanced settings. Drivers
remain a grayed unavailable item because no verified universal package is
registered. Colored application icons mean available to add, not installed or
tested in a guest.

Browser screenshots and test scope are recorded in `docs/verification/172/`.

Browser acceptance uses real Chromium/HTTP with synthetic drives and a
synthetic privileged executor. It verifies the focused configuration rail,
all-type Object Manager, six setup cards, Setup and Drivers icon groups, group
gestures, object copy/move, phone-width layout without horizontal overflow,
and saved display behavior.
Focused Installer/page tests pass 22. No real drive, VM, Proxmox host, or
universal driver package was changed or verified. Physical installation,
network/firewall behavior, persistent overlays, workload execution and
machine-specific driver profiles remain in the existing physical and workload
queues. This record supersedes DR171's layout description only; DR171 remains
history for the earlier screenshot-driven implementation.


## Operator clarification — 2026-10-08

Each VM/container owns one environment-settings modal containing its related
drive assignment, Proxmox, OS, hardware, drivers and application setup blocks.
The default environment is named `testvm1` and explicitly labeled an
unprovisioned setup draft; “Baseline” is not presented as a guest name. Drive
configuration is called “Drive assignment,” since “Storage” does not tell a
new user what action belongs there. Browser acceptance now checks the modal,
name, draft status and drive terminology.
