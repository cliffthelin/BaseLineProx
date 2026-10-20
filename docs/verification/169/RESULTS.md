# DR169 verification results

- Confirmed RED then GREEN through authenticated display API and real Chromium.
- Focused configuration/Installer regressions: 97 passed.
- Full unit suite: 3454 passed in 169.30 seconds.
- After final Object Manager catalog controls: 21 focused tests passed.
- Final browser script: tests/integration/verify_installer_desktop_browser.py.
  Actual Chromium/HTTP, mouse and touch input check preserved/default workspace,
  display-mode persistence, horizontal/vertical corner gestures, hold, ordering,
  group hide/restore/create, full/split Object Manager, VM/container page tabs,
  body swipes, edited configuration copy/move, manager-only unpinning, dynamic
  registration and responsive display. Privileged commands and disk identities
  are synthetic; this is not physical deployment or native workload proof.
- Screenshots alongside this file are browser-fixture screenshots, not installed
  PC401 or live Proxmox screenshots.
- Whitespace check passed.

The physical boot/network/firewall acceptance, generalized workload execution,
installed application catalog loading and machine-grouped hardware-driver cache
and persistence remain open. No physical drive changes were made for this mode.

The real localhost:8100 Installer was reloaded with PC401 selected and PC601
protected. The plain Installer Plan URL was opened in the existing browser.
Live login HTTP200 and Referrer-Policy same-origin were checked without reading
operator credentials. This reload performed no physical installation or boot.
