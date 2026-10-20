# DR311 — Optional parent Bluetooth transfer for every build lifecycle

Date: 2026-10-19. Clarifies and extends DR310 following the operator's instruction:
this is a reusable, optional installer feature for new builds, updates and rebuilds,
not just a repair of PC601.

## Behavior

The installer has a **Parent settings** button in desktop and workspace modes.
Its **Copy parent Bluetooth devices and pairings** checkbox defaults off. The
boolean is stored in the saved/exported installer plan at
`host_configuration.bluetooth_from_parent`, survives reload and can be disabled.
Older plans without the field remain opt-out. Plan validation rejects strings,
other non-booleans and unknown host-configuration keys. Compiled plans retain the
choice. Pairing keys are never embedded in the plan or installer source bundle.

Execution uses the existing guarded transfer implementation:

- The web installed-drive updater reads the immutable captured plan before device
  probes, and applies the choice only after verified USER_ADMIN is mounted.
- `baseline-rebuild-drive --plan FILE` honors the same saved choice. The existing
  explicit `--bluetooth-from-parent` flag remains available.
- `baseline-allscript-install --plan FILE` honors it for fresh builds and updates.
  `--bluetooth-from-parent` / `--no-bluetooth-from-parent` can explicitly override
  the plan. The choice is saved in that target's progress journal, including for
  resumed updates. Fresh builds transfer after the install VM has exited cleanly,
  through the guarded rebuild/backup/mirror path; selected fresh-build runs obtain
  root before executing the session. A run ending at the install stage alone has
  not yet reached the post-shutdown transfer step.

Truly empty first-boot Bluetooth persistence directories can now receive state.
Different existing child state still fails explicitly without replacing it. The
feature copies `/var/lib/bluetooth`, not global `/etc/bluetooth` policy, and retains
controller identity. It neither assigns controllers to guests nor fabricates
radio/connection verification. General fresh-build execution from the web page
remains the pre-existing unfinished executor; exporting its plan and using the
allscript build path consumes this option.

## Deployment and proof boundary

Targeted installer/source files were deployed to physical PC601 and its existing
BASELINE_MIRROR ROOT copy. Source and deployed bytes were compared on each.
Existing pairings were untouched. The source snapshot and installed modules were
updated together; no drive was formatted, provisioned wholesale, or booted.
System-file originals and a deployment report are on CACHE at
`baseline-build/bluetooth-feature-20261019/{before/,report.json}`. All deployment
mounts were unmounted.

Actual Chromium verified default off, visible controls in desktop/workspace,
selection save, reload retention, and deselection save against synthetic drives
and a real temporary draft database. Screenshot:
[installer parent settings](../../verification/311/installer-parent-settings.png).
The runnable check is `tests/integration/verify_bluetooth_installer_browser.py`.
Unit checks cover real-file transfer behavior, plan validation/compilation,
injected fresh-build sequencing and existing update/rebuild contracts. These do
not establish a physical build/update run or native Bluetooth reconnection.

## Remaining work and documentation

Queue72/76's general web new-install executor remains open; queue72/78 native
boot, radio and reconnection acceptance remain open. DR310's physical copy proof
is unchanged. Its CLI-only future-transfer description is superseded here.
Current INSTALL and work queue were updated; historical decision records remain
append-only. The existing concurrent turnkey/guest-persistence work was retained.
