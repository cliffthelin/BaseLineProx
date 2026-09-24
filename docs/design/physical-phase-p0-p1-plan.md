# Physical validation plan: Phase P0 (read-only preservation) and Phase P1 (disposable-drive install)

Status: **planning and implementation preparation complete; the real privacy verification gate is pending operator action, not passed.**

```
identity_scan:                pending_operator_verification
development_blocked:          false
physical_P0_closeout_blocked: true
```

The three original implementation gaps, four security hardening corrections, and both remaining verification items (coverage accounting, and a local-only interactive runner for the real external-identity scan) are closed - see "P0 implementation gaps closed", "Security hardening before an authoritative P0 capture", and "Coverage accounting and the interactive local-only scan runner" below. Nothing in this document has been run against any physical host. No physical drive has been touched, mounted, written to, or installed to.

**The one remaining action before the first P0 capture is for the operator to run the interactive scanner locally** (`python3 tools/interactive_denylist_scan.py`) and type the three real protected values at its hidden prompts - Claude never sees them, never asks for them in chat, and the mechanism is designed so they cannot reach any log, transcript, file, or fixture. This has **not** been run by any session as of this writing - `identity_scan` stays `pending_operator_verification`, never `passed`, until an operator runs it and reports a clean result back. A `findings` or `scan_incomplete` result reopens the privacy gate regardless of anything else in this document; it does not invalidate unrelated architecture or planning work done in the meantime. Blocked by the pending gate: final P0 privacy closeout, physical Phase P1, production identity enrollment, and publication of any retained evidence as privacy-clean. Not blocked: documentation, schema/unit-test-only design work, and synthetic (no real hardware, no real identity) experimentation - see [testpersistence-prd.md](testpersistence-prd.md) for the current instance of that.

## P0 implementation gaps closed (2026-09-24)

Three concrete gaps were identified after this plan's first version and are now resolved in code (not just documented as future work), each with unit tests and a full-suite run - no QEMU rerun, per instruction:

1. **`config_files[]` is now populated**, not hardcoded empty. `baseline/lib/inventory/collectors/config_files.py` walks a fixed allowlist (never arbitrary discovery) covering `/etc/network/interfaces` and its full resolved source closure, legacy and Deb822 APT source files, `/etc/default/grub`/`/etc/kernel/cmdline`, Baseline's own deployed files and units, `/etc/hostname`/`/etc/hosts`/`/etc/resolv.conf`, and allowlisted `modprobe.d`/`modules-load.d`/`sysctl.d`/`sysctl.conf` files. Each entry records path, file/symlink type and target, owner/group/mode/size, owning package, dpkg conffile-modified status, Baseline-managed classification, and an HMAC-backed content-identity token - never raw content. `/etc/pve` stays its own separately allowlisted collector (`collectors/proxmox.py`), untouched by this module, still never recursing into or reading `priv/`.
2. **Deb822 `.sources` repositories are now collected alongside legacy `.list` files** (`baseline/lib/inventory/collectors/apt_sources.py`), preserving URI, suites, components, enabled state, Signed-By, architecture restrictions, source filename, and a best-effort channel classification (no-subscription/enterprise/test/distro/unknown) for both formats. Credentials embedded in a repository URI are redacted. `system.py`'s `collect_apt()` now exposes a structured `repositories` list instead of a raw `sources_list` text blob.
3. **A pure, offline comparator exists** (`baseline/lib/inventory/diff.py`): takes two already-collected manifests, never touches a host, never mutates either input, never emits anything executable. Every difference gets exactly one of the five established classifications (`suggested_required`, `suggested_machine_specific`, `detected_secret_identity`, `candidate_obsolete`, `unknown`) via narrow, explicit rules - `candidate_obsolete` is applied only to Baseline's own deployed-file list, where "no longer present" has an authoritative source of truth; everything else defaults to `suggested_required` (reference-only) or `unknown` (new-build-only or a same-path value difference), reusing `validate.py`'s own secret-shape patterns for the `detected_secret_identity` safety check.
4. **Cross-run HMAC comparison is now explicit, not accidental.** `redact.Redactor` gained a `key_id` property (a non-secret SHA-256 fingerprint of the key, recorded in every manifest's `redaction_report`) so `diff.compare_manifests()` can tell whether two manifests were tokenized under the same key without ever seeing the key itself - an HMAC-tokenized value (recognized by shape, `kind:12-hex-chars`, not a hardcoded field list) is only ever compared when both manifests' `key_id` match; otherwise it is skipped, never silently treated as equal or reported as a false difference. `baseline-drive-inventory collect` gained `--key-file <path>` (must be mode `0600`, refused otherwise) and `--key-fd <N>` - **never** an argv value or environment variable, both of which can leak via `ps`, shell history, or a crash dump. A new `compare` subcommand runs the comparator and prints (or writes) its JSON report. Standalone runs with neither flag keep the original ephemeral-random-key behavior unchanged.

## Security hardening before an authoritative P0 capture (2026-09-24)

Four narrow corrections, none of them a design change or a QEMU rerun - unit/full-suite validation only, nothing run against a physical host:

1. **`shred -u` and any secure-erasure claim removed.** This project already established (`drive-setup-gui-v2-prd.md` §7) that deleting a file from SSD/flash storage is *deletion*, not *secure erasure* - wear-leveling means the underlying flash cells aren't reliably overwritten by a simple unlink, `shred`, or any other single-pass tool, and the same holds for a journaled filesystem. The comparison-key workflow below now says exactly that: retire the key (best-effort delete, or destroy the key of an encrypted container it lived in for a real crypto-erasure boundary), never "securely erase" it.
2. **Comparison-key loading hardened** (`baseline/lib/inventory/keysource.py`): a `--key-file` is opened exactly once with `O_NOFOLLOW|O_CLOEXEC` (a symlink is refused outright, never followed), and every check - regular file, owned by the effective user, mode exactly `0600`, exactly one hard link, exact `KEY_LENGTH_BYTES=32` (256-bit) length after stripping one trailing newline - runs via `fstat()` on that single already-open descriptor, never a path-based `stat()` before a separate `open()` (closing the TOCTOU window that pattern would otherwise leave). Key material is never printed, logged, or included in any error message. `--key-fd` remains the preferred form for real P0/P1 collection, since a descriptor never touches a directory entry at all. `redact.Redactor.key_id` is now explicitly domain-separated (a fixed, purpose-tagged prefix mixed into its hash input) from `tokenize()`'s HMAC-of-value, so the two can never be confused or collide by construction, not merely by happening to look different.
3. **`config_files[]` can no longer be redirected by a symlink at an allowlisted path.** An allowlisted filename that has itself been replaced with a symlink is recorded as a symlink (never followed for content - content hashing only ever applies to `file_type == "regular file"` entries, symlink or not, approved or not), and its target is disclosed in the clear only for a small, explicit allowlist of expected targets (currently: `/etc/resolv.conf` → known `systemd-resolved`/`NetworkManager` stub paths). Every other symlink target - including at `/etc/hosts`, any Baseline-managed path, or any systemd unit path, none of which have any approved target at all - is flagged `unexpected_symlink_target: true` with only an HMAC-tokenized link identity recorded, never the raw destination path. `/etc/pve` remains untouched by any of this, still its own separately allowlisted collector.
4. **A generic external-identity denylist scanner exists** (`tools/scan_denylist.py`, dev/CI-only, never deployed to a host or imported by `baseline/lib`). Prohibited terms are supplied only through a protected file descriptor (`--denylist-fd`), never argv, an environment variable, or a committed file - this repository contains no real identifiers itself, by construction, since the scanner that checks for them never carries any. A match is never printed - only the affected path (or commit, for the separate `scan-history` mode) and a generic category. `scan-tree` covers every git-tracked file (source, tests, fixtures, example manifests, docs) plus any `--extra-dir` of retained artifacts; `scan-history` walks `git log --all -p` read-only - it reports a finding for a human remediation decision and never rewrites, amends, or filters history. Repository/remote ownership metadata (this project's own GitHub account name as it appears in a remote URL, `README.md`, `LICENSE`) is excluded by an explicit path list, never by content, so that exclusion can't be used to hide anything else. A separate, always-on, no-FD-needed check (`tests/unit/test_no_persistence_typo.py`) rejects a common one-letter (a-for-e) misspelling of "persistence" anywhere in tracked content, case-insensitively - the correct spelling is the only one used throughout this project.
5. **The scanner's own resource use is bounded, after a real, observed failure.** An early version of `scan-tree` read each candidate file's full content into memory at once; pointed at this repository's own `experiments/` directory (which, independent of this work, still holds a leftover 7.1GB disposable artifact from an earlier session that was never cleaned up), it was OOM-killed by the kernel - and, in the same window, the same memory pressure contributed to Claude Desktop itself being OOM-killed (72.8GB peak, per `journalctl`). Fixed at two levels:
   - **Bounded, chunked, constant-memory reads** (`_file_contains_any_term`): every file is read in `CHUNK_BYTES`-sized pieces with a small overlap window (so a term straddling a chunk boundary is never missed), capped per-file at `MAX_SCAN_BYTES_PER_FILE` and overall at `OVERALL_SCAN_BUDGET_BYTES` across the whole run - proven with a 2GB *sparse* file (near-zero real disk/memory, but a real multi-gigabyte logical size) that the actual bytes read stay bounded by the cap regardless of the file's apparent size. `scan-history`'s `git log -p` output is now streamed line-by-line (never captured whole), under its own `HISTORY_LINE_BUDGET`. Either budget being exhausted produces a clean, explicit `scan_incomplete` result (with a `reason`) instead of either hanging or silently truncating - a CI/pre-P0 gate should treat `scan_incomplete` as a hard stop, same as a real finding.
   - **Isolated worker subprocess with a memory ceiling** (`run_scan_isolated`, the default for the CLI unless `--no-isolation` is passed): the actual scan runs in a child process spawned under `RLIMIT_AS` (an address-space limit, applied best-effort where the platform supports it), so an unexpected resource blowup can only take the worker down - reported back to the parent as `scan_incomplete: resource_limit_exceeded`, never propagated as a crash. The denylist reaches the worker via a dedicated pipe fd (never argv/env, matching the external-scanner discipline throughout), and the result comes back as one bounded JSON blob over a second dedicated pipe (capped at `MAX_WORKER_RESULT_BYTES`) - never an unbounded captured stdout/stderr stream.
   - **Bounded, deduplicated operational logging** (`tools/bounded_log.py`, a small reusable primitive - a repeated condition must consume bounded resources regardless of how long it continues): every operational event the scanner logs internally (a file-read error, a per-file cap being hit, an overall-budget skip) goes through `BoundedEventLog` - the first occurrence and a small number of early repetitions are recorded in full, further identical repetitions are suppressed (only an in-memory counter advances), and `finalize()` produces exactly one summary per distinct signature regardless of how many times it actually occurred. Proven directly with 100,000 synthetic repeated failures: total emitted records stay under 200, never anywhere near 100,000. This is offered as the template for any future Baseline diagnostic ledger with the same shape of problem - a diagnostic control plane cannot stay trustworthy if its own diagnostics can become a resource-exhaustion condition - though wiring it into Baseline's own runtime logging is not part of this pass's scope.

   Re-run against this repository's real `experiments/` directory (including the 7.1GB leftover) after the fix: both `scan-tree` and `scan-history` complete in seconds, well within a 512MB worker memory ceiling, with no OOM and no hang. The 7.1GB leftover itself is a pre-existing retention-policy violation from an earlier session, unrelated to this work - flagged here, not deleted, since it predates this pass and cleanup wasn't requested.

## Coverage accounting and the interactive local-only scan runner (2026-09-24)

Two verification items closed out the scanner before it's trusted for the real P0 capture - neither required any architecture change.

**Coverage accounting** (`scan_tree`'s `stats`, and every result's new `final_status`/`peak_rss_kb` fields) - "the directory traversal completed" is no longer conflated with "fully scanned". Every `scan_tree`/`run_full_scan` result now reports:

- `logical_bytes_present` / `allocated_bytes` (from one `os.stat()` per candidate - `st_blocks * 512`, POSIX-portable, independent of the filesystem's actual block size) and `bytes_actually_read` - so a sparse or excluded file is never silently counted as "fully scanned" just because the walk reached it.
- `files_fully_scanned` (read to EOF within budget) vs. `files_incomplete` (capped by `MAX_SCAN_BYTES_PER_FILE` or the overall budget before reaching EOF) vs. `files_excluded` (ownership metadata, un-stat-able, or skipped once the overall budget was already exhausted) - three disjoint counts, not one blended "files processed" number.
- `sparse_files_encountered` - a file whose allocated bytes are more than 4KB less than its logical size (a real gap, not filesystem rounding noise).
- `peak_rss_kb` - only ever a real number when the scan ran through `run_scan_isolated` (`resource.getrusage(RUSAGE_SELF).ru_maxrss` read inside the worker itself, right after scanning); `None` for a direct in-process call, never a fabricated value.
- `final_status` - computed the same way everywhere by one shared function (`_finalize_result`): `findings` beats `incomplete` beats `clean`. A scan that couldn't fully complete is never reported as `clean`, regardless of whether it happened to find nothing before running out of budget - directly answers "should partial scanning ever be described as clean" (no).

**`run_full_scan()`** ties the three required scopes together in one call, each in its own isolated worker (so one scope's resource use can never affect another's): `current_tracked` (git-tracked files only), `retained_evidence` (only scanned, and only reported as anything other than `not_in_scope`, if at least one directory is explicitly declared - never assumed), and `git_history` (streamed, read-only, a finding is reported for separate remediation, never auto-fixed or rewritten). `format_full_scan_report()` renders exactly the requested table shape - scope / status / findings count / incomplete count - and nothing else; per-finding paths and commit ids stay in the full result dict for separate, deliberate inspection, never in the printed summary.

**The interactive local-only runner** (`tools/interactive_denylist_scan.py`) is what actually closes the real blocker: the three protected values were never going to be safely enterable through this conversation, since a chat transcript is itself exactly the kind of log this whole design exists to keep them out of. The runner reads them one at a time via `getpass.getpass()` - the same standard-library mechanism a password prompt uses, which opens `/dev/tty` directly (not stdin) and disables terminal echo via `termios` for the duration of each prompt. The values are never accepted or exposed through chat, command-line arguments, environment variables, shell history, a repository file, a test fixture, an ordinary temporary file, or the printed report - they live only in this process's memory and the anonymous pipe fd each isolated worker subprocess receives (`run_full_scan`'s existing mechanism, unchanged). Fewer than three non-empty values aborts before scanning anything, rather than silently scanning against a short list.

Tested exclusively with synthetic identifiers, via an injectable `prompt_fn` parameter (`collect_denylist_interactively(prompt_fn=...)`) that lets tests supply fake values without ever touching a real terminal - the real `getpass`-based path is exercised only when a human runs the script directly. One test confirms by source inspection that the default path genuinely calls `getpass.getpass` (never the plain `input()` builtin, which would echo to the screen).

**Run this yourself, locally - Claude does not run it and does not see the values:**

```bash
python3 tools/interactive_denylist_scan.py --retained-evidence-dir experiments
```

It will prompt three times, hidden, for the protected values, then print the scope/status/findings/incomplete table and exit non-zero if anything is `findings` or `incomplete` (never zero on an incomplete scan). A `findings` or `incomplete` result is a stop: read the reported scope(s), and use the full result (`report["scopes"][<name>]["findings"]`, e.g. via a short Python REPL session run the same way, never printed to a shared log) for the actual remediation decision - `git_history` findings are never rewritten automatically, matching `scan_history`'s own contract.

**The workflow for an actual P0-vs-P1 comparison, once both phases run for real:**

```bash
# Once, before either collection - outside both drives being examined:
head -c 32 /dev/urandom > comparison.key   # exactly 32 bytes (256 bits) - keysource.py enforces this length
chmod 600 comparison.key
# Store comparison.key inside an encrypted administrative volume/vault
# outside both examined drives (e.g. a LUKS-backed container on the
# reviewing machine) - not bare on either drive's filesystem, and not
# copied into this repository.

# P0, on the current drive - prefer --key-fd over --key-file where the
# calling shell/orchestration can hold the descriptor open, since a
# descriptor never touches a directory entry at all:
exec 3< comparison.key
baseline-drive-inventory collect --source current-drive --out /root/p0-manifest.json --key-fd 3
exec 3<&-

# P1, on the new build, once that phase actually runs:
exec 3< comparison.key
baseline-drive-inventory collect --source disposable-vm --out /root/p1-manifest.json --key-fd 3
exec 3<&-

# After both are exported off their respective drives, on a reviewing machine:
baseline-drive-inventory compare --manifest-a p0-manifest.json --manifest-b p1-manifest.json --require-matching-key
```

**Key retirement, not secure erasure - stated precisely, not overclaimed.** This project already established (drive-setup-gui-v2-prd.md §7) that deleting a file from SSD/flash storage is *deletion*, not *secure erasure*: wear-leveling means the underlying flash cells aren't reliably overwritten by a simple unlink, `shred`, or any other single-pass tool operating above the flash translation layer - and that holds just as much for a journaled filesystem, where an overwrite can land on a different physical block entirely. Nothing in this plan claims otherwise for the comparison key either. The defensible sequence, once the final comparison report has been reviewed:

1. Delete the key file (`rm comparison.key`) - a best-effort operation, described as retirement, not verified erasure.
2. If the key lived inside its own encrypted container (recommended - see above) with a key of its own, destroying *that* container key is the stronger, more defensible crypto-erasure boundary: the comparison key becomes permanently unrecoverable ciphertext even if the underlying flash cells are never actually overwritten.
3. Nothing about this key's retirement is load-bearing for security going forward regardless: it only ever protected the *linkability* of two manifests' tokenized fields against each other, never any host credential or persistent secret. A retired key that somehow survived on a flash cell would let someone compare two already-reviewed, already-exported manifests against each other - not access the current drive, the new build, or anything not already captured in those manifests.

The key is never written into either manifest (only its non-secret `key_id` fingerprint is, itself domain-separated from any content-identity token - see `redact.py`) and is never committed to this repository - exactly the workflow this plan's first version could only describe as a manual fallback procedure.

62 new tests cover the comparison-key/comparator work (`test_config_files.py`, `test_apt_sources.py`, `test_diff.py`, `test_keysource.py`, plus `test_redact.py` and `test_baseline_config.py` additions) - missing/mismatched/matching comparison keys, deterministic same-key tokenization across two independent collection runs, malformed-manifest robustness, and every named comparison category. The coverage-accounting and interactive-runner work above adds 24 more (`test_scan_denylist.py`'s coverage-accounting and `run_full_scan` tests, `test_interactive_denylist_scan.py`'s 11 synthetic-value tests). 418/418 full suite passes; the real scan (with the actual protected values, run locally per the command above) has not been executed by this session.

## Why P0 must happen before P1

The current working BaselineOS drive is the only known-working reference this project has. Its original predecessor already failed once (`backups/failure_log_attempt2.txt` - thousands of I/O errors). Before any new drive is installed, imaged, or compared against, the current drive's actual state - not memory of what was installed, not assumptions from `provision.sh`'s deploy list - must be captured, off that drive, in a form that can be reviewed and diffed later. This is exactly what [decision-records/27](decision-records/27-milestone-1.1-provisioning-closeout.md) closed out in QEMU: the disposable-image proof is now solid, but no QEMU pass can substitute for knowing what the *specific, currently-relied-upon* physical drive actually has on it.

---

## 1. Reviewed P0 collection procedure

P0 uses the just-ported [current-drive inventory collector](current-drive-inventory-plan.md) (`baseline/lib/inventory/`, `baseline/bin/baseline-drive-inventory`), reviewed and adapted from `cliffthelin/baseline`'s `inventory/current-drive-manifest` branch into canonical `BaseLineProx` (see decision commits `f55ed13`, `c688b57`). It is read-only by construction: every collector degrades to a reported failure rather than raising or retrying with elevated privilege, the only write in the entire tool is the one explicitly-named output manifest file, and `pathsafety.py` refuses to write into the repository/deployment root, `/etc`, `/var/lib/baseline`, or `/etc/pve` regardless of what path is requested.

Procedure, matching the numbered steps already given, each mapped to what the tool actually does:

1. **Environment probe.** Run `boot/baseline-repair-env-probe.sh` (already exists, already used elsewhere in this project for the same non-mutating purpose) to confirm the host's actual state - Proxmox version, network stack in use, standalone-vs-clustered - before trusting anything downstream. Read-only.
2. **Current-drive inventory collector.** `baseline-drive-inventory collect --source current-drive ...` (exact command in section 2). This single run performs steps 3-10 below as one atomic collection pass - they are not separate commands, they are what one `collect` invocation does internally, one collector module per concern.
3. **Package versions and manually-installed packages** - `collectors/system.py::collect_packages()`: `dpkg-query` for every installed package + version, `apt-mark showhold`, and (batched, one call, never per-package) Conffiles metadata for drift evidence.
4. **The five diagnostic tools** - `collectors/tools.py`, data-driven off `tools_manifest.json`: presence (`which`) and version string for `lm-sensors`, `nvme-cli`, `smartmontools`, `iperf3`, `ethtool`. Never starts, enables, or queries a live listener - version-query commands only.
5. **Enabled/disabled services and timers** - `collectors/system.py::collect_systemd_units()` (enabled units + `systemd-delta`) and `collectors/scheduling.py` (cron, `systemctl list-timers --all`). Also, per the port's addition, explicit status for all three Baseline units (`baseline.service`, `baseline-additive-dhcp-reapply.service`, `baseline-firstboot.service`), not just one.
6. **Allowlisted `/etc/pve` configuration** - `collectors/proxmox.py`: named-path reads only (`storage.cfg`, `datacenter.cfg`, per-node `qemu-server`/`lxc` `.conf` files, firewall rules), each field-allowlisted; `priv/` is never listed, read, or even existence-checked (enforced, not just avoided - see `test_never_lists_or_reads_priv_directory`). `pvesubscription get` is never invoked, by design, not deferred.
7. **Network topology and interfaces source-closure** - `collectors/network.py`: `/etc/network/interfaces` read and redacted (address/gateway/DNS values blanked, structure preserved), DNS resolver availability. `collectors/storage.py` covers mounts/block-device topology (`findmnt`, `lsblk`) as a related but separate concern.
8. **Boot configuration, kernel command line, firmware mode** - `collectors/storage.py::collect_boot()` (grub default, redacted `/proc/cmdline`, `proxmox-boot-tool status`, EFI entry count only) and `collectors/system.py::collect_firmware_drivers()` (`lsmod`, `lspci -nnk`, allowlisted `dmidecode` fields).
9. **Baseline files, unit files, and configuration hashes** - `collectors/baseline_config.py`: `/etc/baseline/*.json` (key names only), a bounded `/var/lib/baseline` walk, and - the port's addition - `/opt/baseline/bin/*` and `/opt/baseline/lib/*.py` enumerated and `sha256sum`'d (filenames + hashes only, never content, since hashing Baseline's own known source is exactly the drift evidence this step needs).
10. **Storage, repositories, scheduled tasks, relevant sysctls** - `collectors/storage.py` (mounts/block devices), `collectors/system.py::collect_apt()` (repositories - see the known Deb822 gap in section 6 below), `collectors/scheduling.py` (already covered in step 5), `collectors/security.py::collect_sysctl()` (fail-closed: only a small reviewed allowlist ever gets a live-queried value; every other key found in config files is recorded by name only, never queried).
11. **Export the manifest somewhere other than the drive being examined.** The `collect` command's `--out` still writes to a local path first (it has to - that's how a file is created); this step is the mandatory *next* action, not something the tool does automatically: copy the written manifest off the current drive - to attached external media (USB) or directly into this project conversation as an attachment - before it is considered preserved. Do not leave the only copy on the drive whose future is in question.
12. **Hash and preserve the manifest as the "current known-working drive" baseline.** `sha256sum` the exported manifest immediately after step 11, on the *receiving* side (not the source drive), and record that hash alongside the file. This hash is the tamper-evidence anchor for every future comparison against it.

**This phase performs no install, repair, reconfiguration, or restart of anything**, by construction: `collect` never calls anything but read-only commands and filesystem reads (confirmed by the 74 carried-over + 3 new tests asserting exactly this against a fake runner that records every call attempted), and its one write target is validated three separate times (`validate_output_path()`, then `atomic_write()`'s own independent re-check, then the four forbidden-root exclusions) before anything touches disk.

## 2. Exact read-only commands

Run as the operator, on the current drive, once physical/console access is available. None of these have been run yet.

```bash
# Step 1: environment probe (already-existing, already-used tool)
bash /opt/baseline/lib/../../boot/baseline-repair-env-probe.sh
# (or wherever it's staged on that host - it is not deployed by
# provision.sh today; copy it over first if it isn't already present)

# Steps 2-10: one inventory collection pass
/opt/baseline/bin/baseline-drive-inventory collect \
    --source current-drive \
    --host-label baseline-current \
    --node <proxmox-node-name> \
    --out /root/baseline-current-drive-manifest.json

# Immediately after: read-only self-check (schema validity, output
# permissions, forbidden field names, raw-secret-shaped value scan) -
# this never writes anything, including to the manifest it's checking
/opt/baseline/bin/baseline-drive-inventory validate \
    --manifest /root/baseline-current-drive-manifest.json
```

`--node` should be passed once per Proxmox node name the host actually reports (single-node systems: once). If unsure of the exact node name beforehand, `hostname` or `pvecm status`'s own output names it - read those first, non-destructively, rather than guessing.

**Step 11 (export off the drive)** - no single fixed command, since it depends on what media is available at the time; the historical design doc's own guidance (its added "file-handoff" step) applies directly: prefer attaching the manifest and its `validate` report to this project conversation directly (no third-party service, no new software on the drive being preserved); if a USB copy is wanted instead, `cp /root/baseline-current-drive-manifest.json /media/<usb-mount>/` after mounting read-write media that isn't the drive under inventory.

**Step 12 (hash, on the receiving side, after export):**

```bash
sha256sum baseline-current-drive-manifest.json > baseline-current-drive-manifest.json.sha256
```

No `sudo`, `pkexec`, `polkit`, `mount`, package install, service change, or block-device write appears anywhere in this list, matching the standing constraint for this phase.

## 3. Intended external output location requirements

- **Never on the drive being examined**, once step 11 completes - the whole point of preservation is surviving that specific drive's eventual failure or replacement, so a copy that only exists on it proves nothing.
- **Never inside `/opt/baseline`, `/etc`, `/var/lib/baseline`, or `/etc/pve`** even transiently beyond the tool's own initial write - `pathsafety.py` already refuses this at the tool level; the operator-chosen `--out` path (e.g. `/root/...`) is outside all four by construction, but should not be moved into any of them afterward either.
- **Attached to this project conversation, or copied to separate, already-trusted media** (USB, a second machine via `scp`) - not a new cloud service, not new credentials added to the audited host, matching the historical design doc's own reviewed guidance on this exact question.
- **World-unreadable at rest**: `atomic_write()` already `chmod 0600`s the manifest at the moment of writing; whatever holds the exported copy afterward (USB filesystem permissions, the receiving machine's directory) should preserve that, not loosen it.
- **Paired with its `validate` report and its `sha256sum`** wherever it ends up - the manifest alone, without the hash anchor or the validator's pass/fail-and-degraded-categories summary, is harder to trust later.
- **Retained indefinitely as the reference baseline**, not treated as disposable test output - unlike every QEMU experiment workspace this project has produced and deleted, this file's entire purpose is to outlive the drive it describes.

## 4. Current-drive versus new-build comparison procedure

**The comparator now exists** (`baseline/lib/inventory/diff.py`, wired into the CLI as `baseline-drive-inventory compare` - see the "P0 implementation gaps closed" section above). This section is the procedure for using it, not a manual fallback.

1. Produce two manifests with the same collector, one per host: `--source current-drive` for the preserved reference (sections 1-2 above), `--source disposable-vm` for a fresh QEMU or physical build - both collected with `--key-file` pointed at the same, purpose-generated comparison key (see the workflow above), never with two independent ephemeral keys.
2. Run `baseline-drive-inventory validate` against each independently first - a manifest that fails its own validity/permission/secret-shape checks should not be trusted as an input to any comparison.
3. Run `baseline-drive-inventory compare --manifest-a <current-drive.json> --manifest-b <new-build.json> --require-matching-key`. `--require-matching-key` makes the comparator refuse outright (rather than silently skip) if the two manifests weren't tokenized under the same key - the identity-sensitive categories (`proxmox`, `boot`, `scheduling`, `network`) are otherwise meaningless to compare. Drop that flag only for a deliberately coarser pass over non-identity categories (packages, repositories, services, config-file metadata, diagnostic tools, sysctls) when a shared key genuinely isn't available.
4. Read the report's `findings` list, grouped by `findings_by_classification`:
   - `suggested_required` - present on the current drive, missing on the new build, no stronger signal either way. The most actionable category - review each one and decide whether it belongs on the new build.
   - `suggested_machine_specific` - an identity/hardware-bound difference (network addressing, boot cmdline, Proxmox node/vmid identity) found under a matching key. Expected to differ; reviewed for plausibility, not reconciled toward equality.
   - `detected_secret_identity` - a compared value matched one of `validate.py`'s own secret-shape patterns. Treat as a safety finding first, a drift finding second - investigate why a raw-looking secret/identity value reached a manifest at all.
   - `candidate_obsolete` - currently applied only to Baseline's own deployed-file list (`baseline_config.deployed_files`): present on the current drive, not part of what the new build actually deploys. A real signal that a file is no longer shipped, not a request to delete anything.
   - `unknown` - everything else: a real difference, no narrow rule confident enough to classify it further. Requires the most human judgment.
5. **Every finding is a suggestion for human review, never automatic restoration** - enforced by construction, not merely by convention: `compare_manifests()` has no code path that writes to a host, generates a command, or mutates either input manifest (see `test_diff.py`'s `test_neither_input_manifest_is_mutated` and `test_findings_never_contain_executable_or_command_shaped_fields`). This is not a policy choice invented for this procedure - it is the same posture [drive-setup-gui-v2-prd.md](drive-setup-gui-v2-prd.md) already established for `machine-id` (never auto-restored), generalized: a manifest diff is evidence a human looks at, never a trigger for code to act on unattended.
6. **Never copy machine-specific network, boot, or Proxmox identity settings blindly**, even when classified `suggested_machine_specific` - that classification exists so a reviewer can *recognize* an expected-to-differ category at a glance, not so it can be skipped past. Different NIC, different disk topology, a fresh `/etc/pve` cluster identity are all legitimate reasons these categories differ between an old and a new drive.
7. Retire the shared comparison key once the report has been reviewed - it has no further purpose after that. Delete the key file as a best-effort operation (never described as verified secure erasure - see the key-lifecycle note above) and, if it lived in its own encrypted container, destroy that container's key for a real crypto-erasure boundary. Every manifest it touched already carries only its non-secret `key_id` fingerprint, never the key itself.

## 5. Physical Phase P1 validation plan

**Not started. Nothing below has been run.** P1 only begins after P0's manifest is exported, hashed, and preserved per sections 1-3.

1. **Identify the disposable target by serial/WWN and capacity, not `/dev/sdX`.** A device path is reassigned across reboots and enumeration order; it must never be the thing that decides which physical device gets written to. The commands to run (read-only, later, not executed in this pass):
   ```bash
   lsblk -o NAME,SIZE,MODEL,SERIAL,WWN,TRAN
   udevadm info --query=property --name=/dev/sdX | grep -E 'ID_SERIAL|ID_WWN|ID_MODEL'
   smartctl -i /dev/sdX   # capacity, model, serial cross-check
   ```
   The user has identified `/dev/sdk` as the currently-attached, already-formatted candidate (a second, separate 512GB drive of the same make/model already used in QEMU-equivalent testing) - but per this phase's own rule, its device path is a starting pointer for *where to look*, not the identity confirmation itself. Before any write, the serial/WWN/capacity read above must be run and recorded, and must be re-confirmed immediately before the install step (device paths can and do shift between an identification pass and a later action, especially across a reboot or a hot-plug event).
2. **Keep the current working drive untouched and, preferably, physically disconnected** during every step below - not merely "not the target," but out of the machine, so a path-confusion mistake elsewhere cannot reach it at all.
3. **Confirm target identity a second time, immediately before the install step**, not just once at the start of the session.
4. **Install the new build** - the already-proven `prepare-iso --fetch-from iso` automated path (or the interactive Terminal-UI path, if preferred for this specific target), same as every QEMU pass in decision records 26/27, now against the confirmed physical device.
5. **Exercise the local authorization workflow** - the same tty1 CONFIRM gate, target-bound network verification, and package install/verify/commit sequence already proven in QEMU, now for real: real tty1, real keyboard, no HMP scripting standing in for a human.
6. **Validate physical NIC/network behavior** - real link negotiation, real driver binding, the things QEMU's `virtio-net`/SLIRP cannot exercise (`ethtool` link/speed/duplex against the real NIC, ping/DNS/HTTPS through it for real).
7. **Run real sensor, NVMe, SMART, and ethtool collectors** - `diagnostics.py`'s existing collectors, this time against real hardware instead of a VM (where `lm-sensors` correctly reports no chips, per decision record 27's own honest finding) - the first time any of these produce genuine, non-empty readings in this project.
8. **Verify `iperf3` remains inactive** - `systemctl is-enabled`/`is-active` + `ss -tln` for `:5201`, matching the same check already proven in QEMU.
9. **Reboot twice** - matching the QEMU proofs' own discipline: once to confirm normal persistence and non-repetition, a second time (or an interruption test, if warranted physically) to re-confirm.
10. **Generate the new-drive inventory** - `baseline-drive-inventory collect --source disposable-vm --out ...` (or a more accurate `--host-label` for a physical-but-disposable target) against the freshly built drive.
11. **Compare it with the preserved current-drive manifest** per section 4 above, and produce the suggestions-for-review list - not an automatic restoration - for a human (the user) to act on.

Explicitly out of scope for P1 and not started in this pass: GUI/browser sandbox work, the Proxmox capability adapter, Harvester evaluation, and touching the actual production/current drive in any way.
