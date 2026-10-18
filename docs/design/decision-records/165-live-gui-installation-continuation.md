# DR165 — Live GUI installation continuation

2026-10-05. In progress; physical cold boot remains unverified.

Session restrictions were removed. Local sockets, actual Chromium and KVM now
work. PC401 serial <PC401 drive serial> was freshly validated and booted through a
new qcow2 overlay with explicit read-only raw physical backing. No physical
source write was performed. The old runtime133 overlay was not reused because
its kernel-assigned backing-device name no longer identified its original disk.

Current-source provision.sh completed in the clone. Live testing exposed:

- Historical healthy firstboot discovery could lack required facts, causing an
  invariant exception after CONFIRM. The healthy branch now rechecks current
  facts, records actual failure cleanly, and refuses package installation when
  verification fails. Two regressions failed before the fix; 36 firstboot tests
  passed afterward. The real clone firstboot committed with fresh evidence.
- ReadOnlyPaths in the persistence mount service gave it a private mount
  namespace. Its successful bind mounts were invisible to dependent services.
  That mount publisher now shares the host namespace. Root-owned code without
  group/world write permission remains enforced; other services retain their
  read-only code mount. The service-specific regression failed before the fix.
  70 firstboot/deployment tests passed afterward. Actual host-visible bind
  mounts and the storage gate were verified inside the clone.
- The threaded web server exposed LocalAppStore's thread-bound SQLite connection.
  A shared connection with a reentrant lock now serializes DB operations and
  compound section updates. An eight-thread update/read regression failed before
  the fix; 143 settings tests passed afterward. Actual Playwright authentication,
  page rendering and durable Ubuntu preparation/creation jobs were exercised.

The shipped baseline-kiosk service rendered the real Proxmox login page through
cage/Chromium, using APPDATA_ADMIN for its profile (verification/165/host-kiosk.png).
This is KVM clone proof, not a physical display/cold-boot claim.

The installed clone's old 8-GiB BASELINE role was smaller than the VM store's
10-GiB headroom requirement. It was extended to 50 GiB only within the disposable
clone after serial/root/VG inspection. Proxmox local-lvm also retained vgname pve
after VG isolation; its clone configuration was corrected to the validated VG.
Production sizing and VG/configuration reconciliation still require follow-up.

Canonical's pinned Ubuntu image was acquired by the authenticated real web
workflow. A new managed desktop environment was created through Proxmox and
started with locale en_GB.UTF-8, a Proxmox homepage and retained home disk. Its
cloud-init seed contains a fixture-only proxy for the isolated test network.
GUI login, Firefox rendering, effective overlay verification and retained-data
rebuild proof are still in progress; do not claim them complete yet.

## Completion evidence — 2026-10-05

Supersedes the in-progress status above. Both real virtual GUI/browser paths
passed: shipped host cage/Chromium authenticated to Proxmox, and managed Ubuntu
GDM/Firefox rendered and authenticated to the configured Proxmox endpoint. Two
actual web-requested OS-overlay rebuilds retained login, document SHA256 and a
Firefox-created bookmark; the OS-only marker disappeared. Read-only stopped-guest
home inspection confirmed retention and clean unmount/NBD disconnect. Native
configuration verification passed; GUI evidence remains separately observed.

Production follow-up is implemented: new BASELINE profiles reserve 50 GiB,
storage-policy v2 preserves v1 validation, and serial-validated native Proxmox
storage reconciliation repairs only an absent old pve VG reference. Existing or
foreign VGs fail explicitly. Shared Firefox policy construction aligns emitted
seed and native verification; desktop autostart explicitly opens the homepage.
These changes had confirmed failing regressions before fixes.

Final full unit suite: **3412 passed**. An earlier run exceeded AF_UNIX path length;
using a short temporary test directory passed without weakening or skipping tests.
An orderly virtual host powerdown/relaunch also passed: all storage, firstboot,
web and kiosk services active, globally visible /etc/baseline bind, and actual
Chromium Proxmox rendering without repair. Evidence: docs/verification/165.

Fixture limitations: browser recovery required Start New Session, and the
disposable self-signed endpoint required certificate acceptance. A mistimed
console input exposed only a generated disposable guest credential; it was
rotated through the native reset-login workflow and temporary captures removed.
No operator credentials were handled. Physical backing stayed explicitly
read-only. Physical native cold boot remains unverified.
