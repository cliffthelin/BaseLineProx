# DR169 — Additional Installer desktop and grouped taskbar display mode

2026-10-07. Extends DR168's display work. Physical deployment/boot status is unchanged.

The operator requested an additional display mode, preserving the current view,
with phone-style pages and a collapsible horizontal application group taskbar.
Installer now offers Current workspace and Phone desktop & taskbar. Each owner
saves the choice and layout in a separate installer-display draft with optimistic
revision checks. Installation and recipe drafts remain separate. Credential
keys remain prohibited; malformed page/group identities and references are
rejected. A conflicting editor cannot silently overwrite the stored layout.

Each configuration page has its own tab and supports mouse/touch swipes on empty
body space plus keyboard tab navigation. Pages can represent Baseline, VMs or
containers. The corner control retains its group's remembered icon with arrows
above and to its right. Horizontal swipes open/close the icon bar; vertical
swipes open/close group selection. Holding opens the bar with the remembered
icon pinned. The icon strip scrolls independently of the trailing Edit and
corner controls. Icons keep titles below them. Edit permits ordering/removing
icons, renaming the group and removing its bar presence. Object Manager restores
hidden groups and creates additional groups.

Object Manager groups the current catalog by Applications, Operating systems
and Drives. It offers search, full-page or split-screen display, adding an
application definition, drag-and-drop placement and right-click configuration.
An object can remain available only in the manager. Right-click Copy to / Move
to validates the currently edited configuration and persists it with the shortcut
on the chosen page/desktop/group. Move removes source placements and source
configuration when changing pages. Manager-only destinations remove existing
pins. This is configured-object placement; it neither migrates a running VM nor
copies private application files. New pages are explicitly Installer
configuration pages, not fabricated running workloads. Native provisioning and
migration retain their existing separate controls and verification requirements.

Confirmed RED preceded display endpoint, shape validation, provisioning-copy,
mode persistence, group restoration, per-page transfer, body gestures,
Object Manager placement, custom-group and dynamic-catalog implementations.
All missing/erroring interactions observed during browser testing were repaired.
The new module is included in boot/provision.sh; the copy guard was first tested
failing rather than leaving an import that only works in the development tree.

Verification: actual local HTTP and Chromium mouse/touch/rendering were used
with synthetic disks, accounts and privileged executor. No physical drive was
written, resized or booted; no new VM/container runtime acceptance is claimed.
See verification/169/RESULTS.md. Native cold boot, broader distro/application
provisioning and hardware-driver profile/cache work remain under queue72/74/75/76/78.
DR168 remains historical; current INSTALL and handoff are updated for both modes.
