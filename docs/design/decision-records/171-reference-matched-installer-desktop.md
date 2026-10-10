# DR171 — Match the requested Installer desktop reference

2026-10-08. Corrects the visual gap reported after DR170. It supersedes the
screen-geometry description in DR168–170; those records remain history for
their authenticated build flow and initial browser interactions.

The operator's supplied screenshot and accompanying specification are the UI
source of truth. The previous extra display mode still looked like the boxed
Installer dashboard, despite the new saved tabs and shortcuts. Chromium had
already proved the old page did not fill the browser. The new shell fills the
viewport, places a narrow icon rail at left, app icons and labels in a compact
top strip, VM/container configuration tabs below it, and the Object Manager
across the lower desktop. Its remembered-group corner is top-right, with
directional gestures and a fixed Edit action; a lower-left Edit opens the mode
dialog. The initial Object Manager category is Drivers to match the supplied
reference. Other live categories are selectable. Full/split geometry is kept
in the owner-scoped Installer display preference. The nav rail collapses
secondary Baseline pages behind More.

The application/OS/drive catalog remains the data source. No guest is called
running because a configuration page exists. The Drivers panel explicitly
reports that no verified universal package is built and links to observed
device bindings; it does not invent package contents. Its package build and
machine-specific cache/profile behavior remain open.

Confirmed RED against the prior boxed layout: the browser geometry check found
the desktop root was not viewport-sized and the group corner was not in the
specified browser corner. The current Chromium integration passes at full and
narrow widths, exercises the display switcher, icon assets, taskbar hold/swipe,
group edit/hide/restore/create, Object Manager full/split and driver-unavailable
report, VM/container tabs, and settings copy/move. Evidence is in
`docs/verification/171/`. These tests use synthetic disks and a synthetic
privileged executor. No real disk was written, no driver was installed, and no
Proxmox guest was started by this UI verification. The operator has not yet
accepted a live browser screenshot.
