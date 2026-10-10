# DR164 — Activate the GUI terminal and launch the guest browser

Date: 2026-10-05
Status: unit/native-artifact checked; live GUI acceptance still blocked.

The kiosk unit now activates tty3 using chvt after its firstboot/storage gate,
so startup explicitly selects the browser's GUI terminal. Provisioning includes
kbd, which provides chvt. Ubuntu Desktop's cloud-init overlay now installs a
standard desktop autostart entry launching Firefox after the authenticated user
logs into the graphical session. Server seeds omit that entry. No autologin or
operator credential is introduced.

Two failing tests reproduced the missing terminal switch and desktop autostart.
The focused startup/configuration/provisioning suite passed 42 tests. Actual
qemu-img/qemu-io/xorriso seed/rebuild continuity checks also passed on synthetic
blank images, not booted Ubuntu. No physical drives changed. DR163's runtime
blocker was freshly reproduced: socket creation still returns EPERM; KVM and
graphics devices and native Proxmox tools are absent in this session.

The operator selected a local runtime session with sockets, KVM and graphics.
That selection does not itself change the execution sandbox or expose devices.
Live Cage/Chromium and authenticated Ubuntu/Firefox rendering remain open under
queue72/74/75/76/78. DR163 remains historical and its tests cover the earlier code.
