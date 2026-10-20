# DR171 evidence

- `01-before-desktop.png`: Chromium capture before the geometry correction.
- `02-after-desktop.png`: Chromium at 1596x1089, matching the supplied
  reference's viewport proportions. Application data and command execution are
  synthetic; the HTML/CSS/JS renderer is the real application implementation.
- `02-after-desktop.png` is the retained Chromium screenshot; the same capture
  was inspected at `/tmp/baseline-installer-manager-initial.png` during the
  visual check.
- `/home/cane/Applications/.venv/bin/python
  tests/integration/verify_installer_desktop_browser.py`: passed in Chromium.
  It exercises real HTTP/browser UI with synthetic disks and privileged
  executor; it does not execute on physical hardware.
- `/home/cane/Applications/.venv/bin/python -m pytest -q
  tests/unit/test_installer_desktop.py tests/unit/test_install_plan_page.py
  --tb=short`: 22 passed.

The browser checks validate visible viewport geometry, compact shortcut icons,
the displayed driver-package error, display-mode dialog and URL persistence,
taskbar gestures and edit order, Object Manager catalog categories and
full/split geometry, environment tabs, drag/drop, and configuration transfer.
The first sandboxed pytest attempt could not bind loopback test sockets; the
focused suite passed when rerun with the authorized local-loopback environment.

No physical disk was written; no native driver was installed; no Proxmox guest,
firewall, or internet connection was started or proved by this visual check.
