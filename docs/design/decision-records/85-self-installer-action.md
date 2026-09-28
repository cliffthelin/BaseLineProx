# Decision record: `build_self_installer` - a real, web-driven action to make a drive prove itself as a laptop self-installer

Status: **implemented, unit-tested (1339/1339 full suite). The orchestration pipeline itself is proven only against fakes for each of its five composed stages (acquire/prepare-iso/iso-build/QEMU-launch/device-safety) - not yet run for real against a physical drive from this action.**

## What was asked

"Please use the web application and make one of the 512GB SK Hynix disks ready to prove itself as a self installer for my laptop." The existing `install` action only builds a persistence LVM structure (no bootloader, no OS) - running it would not have achieved the goal. The actual capability (a self-contained bootable ISO: `iso_builder.py`, decision record unnumbered-but-real from `6f8205e`) existed only as a CLI tool, with no path from the web app at all.

## What was built

`baseline/lib/self_installer.py` - `build_and_write_self_installer()`, composing five already-real, already-tested stages without reimplementing any of them:

1. `physical_device_safety.validate_target_device` - the safety gate, first, always. No later stage runs if this refuses.
2. `drive_setup_acquire.acquire_and_verify` (skipped if the assistant binary is already cached).
3. `drive_setup_answer.prepare_iso_defensively(fetch_from="http")` - the only accepted mode for a real (non-QEMU-only) install, per decision record 02's still-standing finding.
4. `iso_builder.build_current_iso` - remasters that into the genuinely self-contained ISO (this repo's own `boot/provision.sh` + `baseline/` tree baked in, so no separate deployment step is needed after install - the actual meaning of "self installer").
5. `drive_setup_install.build_sparse_install_invocation`, `target_image` pointed at the **real** device path (never a QEMU sparse file) - launches the real automated install, plus the matching `EphemeralAnswerServer`.

**Disclosed, not solved**: this function's own success means "launched", never "installed correctly" - confirming actual completion still needs a human or vision-capable agent reading a screendump, the same honest ceiling `drive_setup_install.py` already established and this record does not pretend to lift.

`drive_admin.build_self_installer()` wires this into the web app for real, using plain unauthenticated real runner instances for all five stages (correct, not an oversight: none of them need root - device queries are unprivileged reads, and the QEMU step only needs `disk`-group-level device access, a different privilege tier than the LVM wipe/create calls `rebuild_persistence_lvm` needs `SudoRunner` for).

## Real conflict found and resolved by direct instruction, not silently

Adding this as a fourth top-level action broke an existing, explicit test: `test_describe_actions_lists_exactly_install_update_selected_and_repair`, whose own docstring recorded prior direct feedback capping the action list at exactly three. Flagged this directly rather than editing the test unilaterally; given explicit instruction to relax the cap, updated it to assert the real four-action set, with a docstring explaining why the cap changed - matching this project's standing rule that a test only changes for a real, acknowledged design change, never silently to obtain green.

## Real mechanical gap found and fixed in passing

`self_installer.py` and its three transitive dependencies (`drive_setup_acquire.py`, `drive_setup_answer.py`, `drive_setup_install.py`) were missing from `provision.sh`'s copy list - caught immediately by this project's own `test_check_provision_deploys_all_imports.py`, the same class of staging gap decision records 80/81 already found for other modules. Fixed.

## Verification performed

- RED confirmed first: `ModuleNotFoundError: No module named 'self_installer'` before implementation.
- 5 new tests (`tests/unit/test_self_installer.py`), all FakeRunner-scripted across every composed stage's own existing test fakes (cross-file reuse, matching `test_firstboot_statemachine.py`'s established precedent) - device-safety refusal, acquire-skip-when-cached, acquire-failure propagation, prepare-iso-failure propagation, and never-reaches-QEMU-on-earlier-failure.
- Full suite: 1339/1339 (1334 before this record).
- **Not verified**: no real acquire, no real prepare-iso, no real ISO remaster, no real QEMU launch against a physical device has been run through this action yet. The web app itself was started and exercised for real this session (confirmed both SK hynix drives correctly identified as NVMe via the `get_usb_bridge_model` heuristic), but `build_self_installer` specifically was not invoked against real hardware in this pass.
