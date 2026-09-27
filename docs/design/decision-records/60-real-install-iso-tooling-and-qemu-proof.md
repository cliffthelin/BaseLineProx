# Decision record: real install-ISO tooling built and proven - QEMU end-to-end install, real answer-server proof, two real bugs found and fixed, hardware-identity pinning made optional

Status: **QEMU disposable install proven end-to-end for real (genuine post-install Proxmox login prompt, not inferred). The real (`--fetch-from http`) answer-serving mechanism proven end-to-end for real against a local HTTPS server (hardware-match, hardware-mismatch, and replay all independently confirmed). Two real bugs found and fixed. Still not run against actual real target hardware - this machine has no physical access to it.**

## What was asked

"please push it and the make anew iso for installing it" - pushed the prior session's commits to `origin` (never `cliff`), then asked which artifact was actually wanted; answered "All 3": a QEMU-testable proof, a real-bare-metal-intended ISO, and the `baseline-drive-setup` `.deb`.

## Part 1: real acquisition (Step 1, already-proven chain, re-run for real)

Ran `drive_setup_acquire.acquire_and_verify` for real against `download.proxmox.com`'s live repository. Two real caller-error bugs found and fixed in the *call*, not the module (the module's own hash-verification correctly refused both before they could do damage - exactly its stated job):

1. `packages_relative_path` must be relative to `dists/trixie/` (no `dists/trixie/` prefix) - the `Release` file's own SHA256 block lists paths that way.
2. `mirror_base_url` must be the repo root (`.../debian/pve`), not `.../debian/pve/dists/trixie` - `Packages`' own `Filename` field already includes `dists/trixie/...`, so passing the deeper path doubles it and fetches a 404 (silently accepted by HTTP, then correctly rejected by the hash check).

Both are exactly the class of doubled-path/wrong-relative-root mistake decision record 18 already found once; re-derived independently here rather than remembered, then fixed. Real, hash-verified `proxmox-auto-install-assistant` 9.2.8 extracted (`dpkg -l` confirmed empty before and after - no host package DB touched).

## Part 2: QEMU-testable ISO - `--fetch-from iso`, the accepted QEMU-only exception

Per decision records 21/22/27 (not 19, which only proved ISO-preparation postconditions, never an actual boot): `--fetch-from iso` is the right mode for a disposable QEMU proof - sidesteps decision records 15-16's still-unresolved `guestfwd`/SLIRP answer-fetch blocker entirely, since `iso` mode needs no inbound network delivery at all.

Built a real answer.toml (synthetic fqdn/password), ran `prepare_iso_defensively` for real - passed clean, no bugs, first try. Booted it under real KVM-accelerated QEMU (`build_sparse_install_invocation`), captured periodic screendumps over the monitor socket:

- 40s in: 60.1% (`extracting` phase).
- 70s in: 99.0% (`make system bootable`).
- 85s in: the installer's own boot menu reappeared with "Install Proxmox VE (Automated)" defaulted and a 2-second countdown - decision record 04's known reboot-loop defect, recognized immediately, `quit` sent to the monitor socket before the countdown expired (confirmed: QEMU exited cleanly, no self-reinstall).
- Booted the resulting disk with `build_postinstall_boot_invocation` (no CD-ROM attached): **a real, literal, unambiguous Proxmox login prompt** - "Welcome to the Proxmox Virtual Environment... baseline-qemu-test login:" - the exact `fqdn` from the answer file. This is direct, first-hand proof, not inferred from partition structure or exit code.

`verify_image_structure`/`scan_for_forbidden_bytes` confirmed a genuine GPT-partitioned 32GB image; the answer's password hash is present in the **installed disk's** `/etc/shadow` (expected and correct - a different artifact than the ISO file itself, which must never contain it and didn't in the real-mode ISO, verified separately below).

## Part 3: real bug found - `prepare_iso_defensively` never created `--tmp`

Building the real-hardware-intended tool (`baseline-prepare-real-install-iso`), the very first real run failed: exit code 0 (decision record 02's finding, again - never trust it) but `stderr: "Error: No such file or directory (os error 2)"`. Root cause: `prepare-iso` does not create its own `--tmp` directory, and `prepare_iso_defensively` never created it either - every `FakeAnswerRunner`-based test in `test_drive_setup_answer.py` had passed regardless, since the fake never modeled a missing-directory failure at all (the same shape of gap as this session's earlier `RealRunner.write_text_atomic` finding in `repair.py` - a fake silently diverging from real filesystem behavior, caught only by an actual end-to-end run).

Fix: added `makedirs()` to the `AnswerRunner` interface (+ `RealAnswerRunner`, + the test suite's `FakeAnswerRunner`), and `prepare_iso_defensively` now calls it on `tmp_dir` before invoking the binary. New test (`test_prepare_iso_creates_tmp_dir_before_invoking_the_binary`) proves it. Re-ran for real after the fix: clean pass, every postcondition green, including `url_matches`/`fingerprint_matches` (new postconditions this real run exercised that the QEMU-only pass never needed).

## Part 4: `baseline/bin/baseline-prepare-real-install-iso` - new tool, operationalizes docs/INSTALL.md Step 2

Real, sha256-verified assistant binary + a real self-signed TLS cert + a real `answer.toml` targeting the actual documented drive serial (`FD01N6557110C271B`, via `filter.ID_SERIAL_SHORT` - confirmed via web search against Proxmox's own forum-documented syntax, not guessed) + `prepare_iso_defensively` with `--fetch-from http` - all wired into one script. Verified for real, twice:

1. `prepare-iso` itself: every postcondition passed, including the two HTTP-specific ones (`url_matches`, `fingerprint_matches`) and `no_forbidden_canaries_in_iso` (the password hash and full answer content confirmed absent from the ISO file - the entire point of `http` mode).
2. The serving half, for real, against a local HTTPS listener: wrong hardware → `403 hardware mismatch`; correct hardware → `200` with the exact real `answer.toml` content; a replay of the same session → `403 already consumed`. All three the actual, literal server responses, not asserted from the code alone.

## Part 5: correction mid-work - "Hardware is expected to change with install"

The first version of this tool made `--target-mac`/`--target-dmi-product` **required**, treating exact pre-known hardware identity as the only trust model. Told directly this is wrong: hardware is expected to change with a real install (a replaced drive, a different or not-yet-known machine), and "adding a new drive should be allowed" - authorization for that shouldn't depend on Baseline having pre-memorized the machine's exact fingerprint.

Fix, real and tested, not just discussed:

- `drive_setup_answer._check_hardware` now accepts `None` for either expected value, meaning "don't check this fact" - `SessionState` accepts `None` for both. Three new tests (`test_none_expected_mac_accepts_any_mac` - real HTTPS round trip with a synthetic unknown MAC, actually gets `200`; `test_none_expected_dmi_product_accepts_any_product`; `test_both_none_accepts_everything`).
- `baseline-prepare-real-install-iso`'s `--target-mac`/`--target-dmi-product` are now optional; omitting either prints an explicit note about which fact isn't being checked and what the session's real trust boundary becomes instead (LAN scope + pinned TLS fingerprint + single-use + TTL) - never silent about the tradeoff.
- Re-verified for real: a session with both `None`, POSTed to with a synthetic unknown MAC (`totally:unknown:mac`) and an unknown DMI product (`BrandNewLaptop`), returned `200` with the real answer content.
- `docs/INSTALL.md`'s real-drive table gained an explicit caveat: those two rows are an example from one point in time, not permanent identity - re-derive the real serial at each install, never carry one forward from the doc without checking it against the drive actually present.

**What this does not change**: `--disk-setup`'s `filter.ID_SERIAL_SHORT` (which physical disk Proxmox's installer writes to) stays a required, explicit, per-invocation argument - that one is correctly designed already, since it's supposed to vary with whatever's actually being targeted this time, not an identity check to loosen.

## Part 6: `.deb` packaging - real bug found and fixed

Building `baseline-drive-setup_1.0.0_amd64.deb` for real (`dpkg-deb --build`) found the source tree's two executables were mode `777` (world-writable) - directly contradicting the package's own `control` file description ("installed read-only, root-owned"). A second, unrelated real finding: this filesystem's ACL-plus-setgid interaction meant a plain numeric `chmod 0755` on a directory did not clear an inherited setgid bit (`getfacl` showed the bit lived in a separate ACL "flags" field); only the symbolic `chmod g-s` actually cleared it. Fixed permissions properly (`0755` executables/dirs, `0644` data files, no setgid), built with `--root-owner-group`. `dpkg-deb -c` confirms `root/root` ownership and correct modes baked into the archive; `lintian` reports only a cosmetic missing-manpage warning; the polkit policy XML is well-formed; `desktop-file-validate` reports only a cosmetic multi-category hint. Neither cosmetic finding blocks anything.

## Verification performed

- Full suite: 902/902 passing (899 before this record's own three test additions - `test_none_expected_mac_accepts_any_mac`, `test_none_expected_dmi_product_accepts_any_product`, `test_both_none_accepts_everything`; 899 itself already included the earlier `test_prepare_iso_creates_tmp_dir_before_invoking_the_binary` fix from Part 3).
- Real QEMU install → real login prompt (Part 2), real HTTPS answer-serve round trips including the new hardware-optional mode (Parts 4-5), real `.deb` build with corrected permissions independently inspected via `dpkg-deb -c`/`lintian` (Part 6) - all genuinely exercised, not asserted.
- Disposable QEMU disk images and prepared test ISOs (multi-gigabyte) deleted after verification, per this project's established retention discipline. The `.deb` (7.2KB) was kept and handed to the user directly.
- **Not verified**: no real Proxmox host, no real target drive, no real bare-metal boot - this session has no physical access to the hardware in `docs/INSTALL.md`'s table. `baseline-prepare-real-install-iso` is ready for an operator to run for real; that run itself has not happened.
