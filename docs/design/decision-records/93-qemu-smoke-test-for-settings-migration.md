# Decision record: QEMU disposable-install smoke test finds and fixes a real, would-have-shipped bug

Status: **real QEMU install, twice (before and after the fix), genuine post-install login prompt confirming the exact fqdn resolved from the real database. Disposable artifacts deleted after verification per this project's established retention discipline.**

## What was asked

"Now run the QEMU disposable-install smoke test for these changes" - verifying that the settings-to-SQL migration (decision records 87-92) doesn't just pass its own unit tests, but actually produces a working install when driven through the real Proxmox installer.

## The real bug this found

`self_installer.ANSWER_TEMPLATE` rendered `lvm.maxroot`/`lvm.maxvz`/`lvm.swapsize` as **quoted strings** (`lvm.maxroot = "40G"`), and `LVM_SIZE_PRESETS` stored their values as `"20G"`/`"40G"`/`"80G"`-style strings to match. Proxmox's real answer-file schema requires these three fields as a plain number (f64) - a quoted string is a hard TOML-schema parse error:

```
Error: Error parsing answer file: TOML parse error at line 15, column 15
   |
15 | lvm.maxroot = "40G"
   |               ^^^^
invalid type: string "40G", expected f64
```

**This would have failed every real self-installer run**, on real hardware or under QEMU, the instant `prepare-iso` tried to embed the answer file - after the dependency pre-install gate passed, after settings resolved correctly, after the ISO download and acquire stage succeeded - the failure would only ever have shown up at the one step no unit test ever actually exercises for real. Every existing test used `FakeAnswerRunner`, which intercepts the `prepare-iso` call entirely and never validates the answer-file content against the real assistant binary's own parser - the exact shape of gap this project's own QEMU-smoke-test discipline (decision records 59, 60) exists to catch, and did.

## What was fixed

- `self_installer.ANSWER_TEMPLATE`: `lvm.maxroot = "{lvm_maxroot}"` → `lvm.maxroot = {lvm_maxroot}` (same for `maxvz`/`swapsize`) - unquoted, so the rendered TOML carries real numbers.
- `LVM_SIZE_PRESETS`: `"20G"`/`"30G"`/`"2G"` etc. → plain ints `20`/`30`/`2` (GB, matching Proxmox's own schema - the unit is implicit, never embedded in the value).
- `build_and_write_self_installer`'s `lvm_maxroot`/`lvm_maxvz`/`lvm_swapsize` parameter defaults updated to match (`int`, not `"NNG"` strings).
- New tests (`test_self_installer.py`): `test_answer_template_renders_lvm_sizes_as_real_numbers_not_quoted_strings` actually parses the rendered template with `tomllib` (stdlib) and asserts real numeric types for every preset - not a string match for absent quotes, a genuine TOML-schema-shaped check; `test_lvm_size_presets_are_plain_numbers_not_g_suffixed_strings` guards the preset source values directly.

## The disposable-install run itself, for real

Built a throwaway driver script (not checked into the repo - matches decision record 60's own precedent of one-off verification scripts) that:

1. Ran the real pre-install dependency gate (`dependencies.run_checks(phase=PRE_INSTALL)`) - passed clean.
2. Resolved real settings via `settings_store.export_bootstrap_snapshot` against the real database set up in decision record 92 - `lvm_size_preset=medium`, `fqdn=baseline.local`, `memory_mb=3072`.
3. Built a real answer.toml using those resolved values (QEMU-appropriate `disk-list = ["vda"]` in place of `self_installer.py`'s own real-hardware `filter.ID_SERIAL_SHORT` - matching this project's established experiment precedent for disposable QEMU targets, never the real-hardware serial-filter path).
4. `prepare_iso_defensively(fetch_from="iso")` against the cached, already-verified Proxmox 9.2-1 ISO and assistant binary - failed with the bug above on the first run, passed clean (all postconditions green, including a real `inspect-iso` confirming `maxroot = 40` / `maxvz = 60` / `swapsize = 4` as real numbers) after the fix.
5. Booted under real KVM-accelerated QEMU (`build_sparse_install_invocation`), captured periodic screendumps: real package extraction progress (60% → 99% "make system bootable"), reaching the installer's own reboot-menu reappearance at ~120s - decision record 04's known self-reinstall trap, confirmed still real.
6. **Caught the trap in progress, not just in principle**: the driver script's own 10-second screendump polling interval was too coarse to catch the 9-second reboot countdown, and the disk was reinstalled a second time before `quit` reached the monitor socket. Recovered by watching more tightly and sending `quit` directly the moment the menu reappeared on the second pass - clean exit (`process.poll() == 0`), no third reinstall.
7. Booted the resulting disk with `build_postinstall_boot_invocation` (no CD-ROM attached) - **a real, literal, unambiguous login prompt**: `baseline login:`, exactly the `fqdn` value that came from the real database three steps earlier. Direct, first-hand proof the whole chain - dependency gate, settings resolution, answer-file generation, real Proxmox install, real boot - works end to end with the migrated settings/dependency infrastructure driving it.

## Verification performed

- Full unit suite: 1422/1422 (1420 before this record's two new tests).
- Real, twice-run QEMU install (once failing on the real bug, once succeeding after the fix) - not a fake, not asserted from code reading alone.
- Disposable artifacts (8.3GB sparse disk image, 1.6GB prepared ISO, intermediate screendumps) deleted after verification; two screendumps (the reboot-menu evidence and the final login-prompt proof) and the driver script kept under `/tmp` for this record's own reference, not committed to the repo.
- **Not verified**: this smoke test targets a QEMU sparse file, never a real block device - `self_installer.py`'s own real-hardware path (`filter.ID_SERIAL_SHORT`, `physical_device_safety` gating) was not exercised by this run, matching every other QEMU-only proof in this project's history (decision records 02, 59, 60). The `LVM_SIZE_PRESETS`/`ANSWER_TEMPLATE` fix applies identically to both paths, but only the QEMU path has now actually consumed the fixed values through a real Proxmox installer.
