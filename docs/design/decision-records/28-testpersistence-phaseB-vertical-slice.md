# Decision record: TestPersistence Phase B - narrow creation/rebuild/reattach vertical slice

Status: **complete, real QEMU execution, all 24 recorded sub-steps passed on the final run.** Entirely synthetic (`TestSystem-A`, `TestSystem-B`, `TestPersistenceDisk-001`, `TestPersistence-001`, `TestPerson-001`, `TestDocuments`, `TestApplication-A`, `TestGrant-001`). No physical hardware, no `/dev/sdX`, no host privilege escalation, no live internet access from inside either guest, no history rewrite. Builds on Milestone 2 (commit `d31d509`) and Phase A's static safety layer (commit `e5144a9`, this branch's own `local/testpersistence-m3-qemu`) - neither is merged into `main`.

```
identity_scan.current_content: pending_full_scan
identity_scan.git_history:     known_findings_scope_unknown
identity_scan.full_scan:       pending_operator_verification
```

This experiment is entirely synthetic and does not touch that gate either way - it neither depends on it nor resolves it. It is recorded here unchanged, not claimed passed.

## Base image - resolved, verified, immutable

- Filename: `debian-13-genericcloud-amd64-20260914-2601.qcow2`
- Source directory: `https://cloud.debian.org/images/cloud/trixie/20260914-2601/` (a dated build directory, resolved from the trixie listing - never the `latest` symlink)
- Size: 340,983,808 bytes
- SHA512: `95e110dfcdbd0ed8a82a75ed9579802f9950cabf51a810dcc6388e81bc778188713878b9f28d583a0ea602fbf48b35996ae9ad37f584166d8fbd6489df248f53` - matched exactly against the published `SHA512SUMS` for this build.
- Signature chain, reported honestly: Debian's *current* genericcloud images are **not GPG-signed** - confirmed directly against Debian's own cloud-images documentation (only legacy OpenStack-directory images carry a `.sign` file; the documented method for current images is TLS+DNSSEC delivery from `cloud.debian.org`/`cdimage.debian.org`). No signature was fabricated to fill this gap. TLS delivery was used and the serving certificate was inspected (a Let's Encrypt certificate for the specific mirror `cloud.debian.org`'s CDN resolved to at fetch time, not a `debian.org`-issued certificate - Debian's cloud-image CDN routes through its mirror network, which is documented, expected behavior, not a shortcut taken by this experiment).
- The base image was never referenced directly by any QEMU argument. `TestSystem-A.qcow2` and `TestSystem-B.qcow2` are each independent `qemu-img convert` copies (confirmed no `backing_file` reference each time), created fresh inside the Phase-A-validated experiment root every run.

## Offline package closure - resolved, verified via the signed APT chain

`cryptsetup-bin` and its full 16-package dependency closure (`libcryptsetup12`, `libpopt0`, `dmsetup`, `libdevmapper1.02.1`, `libjson-c5`, `libssl3t64`, `libzstd1`, `zlib1g`, `openssl-provider-legacy`, `libblkid1`, `libuuid1`, `libselinux1`, `libudev1`, `libc6`, `libgcc-s1`) were downloaded from `deb.debian.org` and verified through the real, GPG-signed APT chain:

1. The trixie archive signing key (published fingerprint `04B5 4C3C DCA7 9751 B16B C6B5 2256 29DF 75B1 88BD`, cross-checked against two independent Debian sources) was fetched and its fingerprint confirmed to match exactly.
2. `dists/trixie/Release`'s detached GPG signature was verified against that key - **good signature** (two other signatures on the same file, for keys not imported here, were left unverified and reported as such, not silently ignored).
3. `main/binary-amd64/Packages.xz`'s SHA256 was checked against the value inside that *signed* Release file.
4. Every one of the 16 `.deb` files was checksum-verified against that verified `Packages` index before use.

This closure was built into a read-only ISO9660 image (`pkgs.iso`), attached to each guest as `media=cdrom,readonly=on`, and installed via `dpkg -i` entirely offline - **neither guest has a network device at all**, so nothing in this experiment could depend on live internet access even if it tried.

## Pre-flight facts

- `qemu-system-x86_64` / `qemu-img`: both 10.2.1 (Debian 1:10.2.1+ds-1ubuntu3.2)
- `/dev/kvm`: usable without authorization (operating account already in the `kvm` group); `-accel kvm` was used. The harness falls back to `tcg` automatically if `/dev/kvm` isn't accessible - no authorization is ever requested for that fallback.
- Guest tools (`cryptsetup`, `dmsetup`, `mkfs.ext4`, `python3`): the base image does **not** include `cryptsetup-bin` (confirmed directly - `dpkg-query` showed it absent before install, then `install ok installed` for both `cryptsetup-bin` and `dmsetup` after); `mkfs.ext4` and `python3` were already present in the base image, as expected for any Debian system with an ext4 root filesystem and cloud-init's own Python runtime.

## Step-by-step result (final passing run, all 24 recorded sub-steps `OK`)

| # | Step | Result |
|---|---|---|
| 1 | Boot `TestSystem-A` with `TestPersistenceDisk-001` attached (separate, blank carrier each run) | OK |
| 1 | Login as the synthetic operator account | OK |
| 2 | **Detection alone causes no auto-format/unlock**: `blkid /dev/vdb` shows no signature, `lsblk` shows the raw disk, nothing mounted | OK |
| 3 | Explicit authorization gate before creating the encrypted store (no default, no timeout - see "Authorization gates" below) | OK |
| 4 | Synthetic LUKS key material written to a guest-local file (32 bytes, confirmed via `wc -c`) | OK |
| 4a | Offline `cryptsetup-bin` closure installed from read-only media, no live network | OK |
| 4b | `cryptsetup luksFormat --type luks2` (real LUKS2 header written to `TestPersistenceDisk-001`) | OK |
| 4c | `cryptsetup open` (real kernel dm-crypt mapping opened) | OK |
| 4d | `mkfs.ext4` + mount (real EXT4-fs kernel mount confirmed in dmesg) | OK |
| 5 | Authenticated synthetic manifest + chained authority-ledger written for `TestPersistence-001` / `TestPerson-001` / `TestDocuments` / `TestApplication-A` / `TestGrant-001` | OK |
| 6 | Manifest dumped and captured before shutdown | OK |
| 6 | Clean unmount + `cryptsetup close` before shutdown (dmsetup confirms "No devices found" afterward) | OK |
| 7 | Clean shutdown of `TestSystem-A` (`shutdown -h now`, guest process exits on its own) | OK |
| 8 | **Only** the exact validated `TestSystem-A.qcow2` deleted (`os.unlink`, not a glob); `TestPersistenceDisk-001.qcow2` preserved untouched | OK |
| 9 | `TestSystem-B` created independently from the same verified base image, booted, logged in | OK |
| 9 | Offline package closure installed on `TestSystem-B` too (a fresh base image copy needs it again) | OK |
| 10 | On `TestSystem-B`: the reattached carrier reports `cryptsetup isLuks` true (a real LUKS2 signature) but is **not mounted** and required no credential to detect - i.e. locked/untrusted, no inherited authorization from `TestSystem-A`'s session | OK |
| 11 | Second explicit authorization gate before import/unlock on `TestSystem-B` | OK |
| 11 | Unlock (same synthetic passphrase, supplied fresh on this system - never inherited) + mount | OK |
| 12 | Manifest dumped again on `TestSystem-B` | OK |
| 12 | **Continuity verified**: same `logical_identity` (`TestPersistence-001`), same `generation`, same `person`/`documents` data, same `grants`, **and the authority-ledger's HMAC chain cryptographically verifies host-side using the real `baseline.lib.testpersistence.manifest` module** (not a re-implementation - the actual Milestone-2 code) | OK |
| - | Clean shutdown of `TestSystem-B` | OK |

## Authorization gates (PRD "no default or timeout acceptance")

`authorize(step_name, granted)` takes no default for `granted` - a call that omits it raises `TypeError` before anything proceeds. This script calls it with `granted=True` at exactly the two points your own message explicitly authorized as steps 3 and 11 of this exact sequence; nothing in this script waits on live interactive input, because the whole 12-step slice was itself the prior, explicit authorization for both gates. This is a deliberate, documented modeling choice, not a claim that a live human clicked anything during execution.

## Scope claims - stated precisely, not generalized

- **Clone detection**: not exercised in this slice at all. Only the simultaneous-attachment case is claimed provable by the PRD (§5) and the Milestone-2 evidence model (§4); this experiment does not attempt it.
- **Revocation vs. rollback**: not exercised in this slice. Milestone 2's `snapshot.py` proves (in pure-code tests, acceptance case 9) that revocation survives rollback **when the authority ledger is outside the rollback domain** - this Phase-B slice does not test snapshot/restore at all, and in particular makes **no claim** about surviving rollback of the entire encrypted persistence carrier. That would require an independent monotonic trust anchor this PRD has not yet selected (§11, §16 blocker).
- **Application isolation / access broker**: **not implemented or exercised** in this slice. No broker boundary exists yet beyond the manifest's own `grants` namespace being written and read back correctly. Per your instruction, this stops here rather than claiming isolation that isn't backed by an actual enforcement boundary - application-grant enforcement is the next experiment, not this one.
- **Production key provisioning, cloud backup, GUI/browser work, physical drives**: none attempted, none implied.

## Real bugs found and fixed while getting this to genuinely pass (not simulated)

1. **TTY echo raced the "done" marker.** A raw serial console echoes typed input back essentially immediately; the marker text this harness used to detect command completion therefore appeared in the buffer the instant it was *sent*, not when the command actually finished - every early run's "successes" were spurious. Fixed by disabling tty echo (`stty -echo`) immediately after login, so a marker can only ever appear as genuine output. An intermediate fix (count two occurrences instead) was tried and also broke, under bracketed-paste redraw artifacts that could echo input more than once - removing the echo at the source, rather than working around it, is what actually held up.
2. **LUKS2's default Argon2id memory cost (~1GiB) thrashed on a small experiment VM.** `cryptsetup open` stalled well past a 30-60s timeout under memory pressure on a 1024MB guest. Fixed with an explicit `--pbkdf-memory 65536` at format time (a test-tuning parameter for this bounded experiment, not a security posture claim) and more guest RAM (2048MB).
3. Several evidence-recording bugs where a step was marked `ok=True` unconditionally regardless of what actually happened (`step2`, `step6`'s original hardcoded `True`) were found and fixed during this same pass, and the corrected checks are what the final table above reflects.
4. `cryptsetup isLuksDevice` is not a valid subcommand (`isLuks` is) - caught because the wrong invocation's usage-text output failed the check rather than silently passing.

## Retention

No credentials, encryption keys, prepared ISOs, or disk images were retained after this record was written. Deleted after evidence capture: `TestPersistenceDisk-001.qcow2`, `TestSystem-B.qcow2`, `seed.iso`, `seed-b.iso`, `pkgs.iso` (all via `qemu_harness_safety.delete_validated_image` - exact validated paths, never a glob or recursive delete), and the entire download cache (verified base image + APT verification workspace, ~396MB - no longer needed once its checksums were recorded above). `TestSystem-A.qcow2` was already deleted by the experiment itself as step 8. Nothing under `experiments/testpersistence-m3-phaseB/` remains except this record's own evidence, which was checked for prohibited identifiers and absolute host paths (none found) before this commit.

## Verification performed before this commit

- Evidence JSON checked for real identifiers and absolute host paths - none found.
- Full repository test suite: 530/530 passing (no regressions from the harness commit).
- This record itself checked for the same before commit.
