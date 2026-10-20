# Installer desktop reference and visual check

The source is the operator's supplied screenshot and adjacent detailed UI
specification. These captures use the actual Chromium renderer with synthetic
discovery and workload fixtures. Neither screenshot is a capture of the
operator's browser window.

`01-before-desktop.png` records the reported problem: a centered Installer
dashboard with a heading, three cards and a wide boxed taskbar. The selected
environment was not the full-browser desktop in the reference.

`02-after-desktop.png` captures the revised 1596x1089 view at the reference
aspect ratio. It shows five labeled app icons in the top strip, the compact
group control and pinned Edit button, the thin environment-tab row, the left
icon rail, the wallpaper/workspace surface and a Drivers manager pane that
starts at 25% viewport height. The pane states that the universal driver
package has not been built. This is a real error state, not a package claim.
The lower-left Edit opens the mode dialog. `More` expands the remaining Baseline
navigation links.

The browser integration passes its current geometry assertions, taskbar
hold/swipe and ordering, group selection/edit/restore, app and OS manager
catalogs, the explicit driver-package error, full/split mode, page tabs, and
shortcut copy/move. A view of a configured environment is not a running guest.
Physical disk execution and PC401's Proxmox/network/firewall boot remain
unverified. The user has not yet accepted the live browser screenshot.

The browser test also checks narrower 500px layout. Keyboard/focus review and
live operator screenshot acceptance remain open.
