# Live GUI and configuration evidence — 2026-10-05

Scope: actual QEMU/KVM clone of the installed PC401 Proxmox drive, plus a
Proxmox-managed nested Ubuntu Desktop guest. This is not native physical cold
boot. The physical source was serial-validated and explicitly read-only in the
QEMU block graph (`block-graph.json`). All filesystem/configuration changes
occurred in the disposable qcow2 overlay. No operator credential was used; test
logins were generated for the disposable targets and kept outside this folder.

- `unit-tests.txt`: full current unit suite, 3412 passed. Separate from live proof.
- `host-storage.json`: actual mounted role/serial verification inside the clone.
- `host-kiosk.png`: shipped cage/Chromium service renders Proxmox's login page.
- `host-kiosk-authenticated.png`: the same kiosk authenticated with the generated
  disposable root login and rendered Proxmox's real inventory.
- `vm-library.png`: actual authenticated Baseline VM page in Playwright Chromium.
- `ubuntu-configuration-before-rebuild.json`: real web/native guest-agent checks
  of locale, configuration overlay, home binding, cloud-init, GDM, agent, Firefox
  and homepage policy. This report deliberately does not infer GUI rendering.
- `ubuntu-firefox-proxmox.png`: graphical Ubuntu login completed; autostarted
  Firefox rendered the actual Proxmox endpoint after its normal self-signed
  certificate prompt was accepted for this disposable host.
- `bookmark-after-first-rebuild.txt`: the bookmark created through Firefox's
  actual UI remained in its retained profile after rebuilding the OS disk.

The first rebuild also retained the login and a user document with SHA256
37e7e1fe20de9d4138fe8012a769292d5a8d9807d85bdfdad761a4e90a9e930d,
while removing a marker written to the disposable OS filesystem. A second
rebuild also passed, including the final first-run browser policy changes.

Test networking uses a loopback-bound package/source proxy through narrowly
named QEMU guest forwards. Its settings are a fixture-only seed augmentation;
the production locale/homepage/desktop/home-disk configuration was preserved.

Final evidence:

- `ubuntu-firefox-after-rebuild.png`: real Ubuntu desktop and Firefox authenticated
  to Proxmox after two OS-overlay rebuilds, with the retained bookmark.
- `ubuntu-configuration-after-rebuild.json`: final native verification passed;
  GUI rendering flags deliberately remain separate from these configuration checks.
- `ubuntu-after-final-rebuild.txt`: cloud-init completed without errors, configured
  locale/browser policies present, OS marker absent, GDM and guest agent active.
- `retention-after-two-rebuilds.json`: stopped-guest, read-only home inspection
  confirms the document hash and Firefox-created bookmark, then clean unmount
  and NBD disconnect.
- `driver-owner-real-virtual-nic.json`: actual virtio_pci ownership verified.
- `host-after-restart.txt` and `host-kiosk-after-restart.png`: orderly virtual
  powerdown/relaunch; all five services active, global persistence bind present,
  Chromium renders Proxmox without manual repair.

New installs reserve 50 GiB for BASELINE. Legacy storage policies still validate.
Native reconciliation repairs only an absent old `pve` VG reference after serial
validation; an existing or unrelated VG is an explicit error. The final full unit
run passed 3412 tests using a short temporary path (longer paths exceeded AF_UNIX
socket limits in an earlier test run).

A disposable guest credential displayed during a mistimed console input was
rotated through the actual reset-login workflow; temporary captures were removed.
No operator credential was involved or published. Firefox's retained crash
recovery prompt required its normal Start New Session action in this fixture;
the configured homepage then loaded. The disposable self-signed Proxmox
certificate also required normal browser acceptance.

2026-10-08 cleanup: the disposable `.runtime-proof165/host.qcow2` clone and
local run scratch directory were removed after this evidence was retained.
The physical PC401 source was read-only backing; this did not alter PC401 or
PC601. The allowlisted package proxy now lives at
`baseline/lib/installer_package_proxy.py` so the installation script no longer
depends on a temporary proof directory. This verification is historical and
the clone must be recreated for a repeat run.
