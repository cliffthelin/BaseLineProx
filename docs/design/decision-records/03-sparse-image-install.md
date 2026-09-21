# Decision record: Image-only installation

Date: 2026-09-20
Investigator: Claude Code
Status: complete

## Summary

Built the defensive wrapper, ephemeral answer server, and argv-free credential generation specified for this investigation, then ran a real, unattended Proxmox VE 9.2-1 install entirely against a sparse regular file — no physical or virtual block device outside the workspace was ever presented to the assistant or to QEMU. The install **succeeded**: the resulting sparse image has a genuine GPT partition table (BIOS-boot + EFI System + LVM), ~7.1GB of real installed content, the plaintext one-time credential does not appear anywhere in the final image, and the answer session was consumed exactly once (a replay attempt afterward was correctly rejected). Two real defects were found and fixed along the way — an early QEMU networking assumption that turned out wrong, and a hardware-fact field-name mismatch — both documented below rather than silently corrected.

## Hard boundaries — how they were enforced, not just followed

- **Sparse regular file only**: `target.img` created via `truncate -s 16G` inside the per-run workspace; asserted in code (`workspace.py`/`run_e2e_install.py`) to be a regular file, not a symlink, and to resolve to a path beneath the workspace root before ever being referenced in a QEMU argv.
- **No block-device arguments or device nodes**: the defensive wrapper (`wrapper.py`) never accepts a caller-supplied output path without checking it resolves to a regular file postcondition; the QEMU invocation's only `-drive`/`-cdrom` targets are files created by this run. All static verification of the final image used file-based tools (`fdisk -l <file>`, `blkid -p <file>`) — **no loop device was created at any point**, including for evidence-gathering.
- **QEMU received only the installer ISO and the controlled sparse target**: confirmed by inspecting the exact argv used for the successful run (redacted form below) — two `-drive`/`-cdrom` entries, nothing else.
- **No host disk, partition, LVM volume, or `/dev/disk/*` path exposed**: the guest's only storage is the virtio-attached sparse file; QEMU's usermode networking (SLIRP) has no bridge/tap/physical-NIC involvement at all.
- **Synthetic installation identity and credentials only**: hostname `m0inv3-final.invalid`, SMBIOS product `baseline-m0-final-run`, MAC `52:54:00:ba:5e:11` (QEMU's standard locally-administered test range), a `secrets.token_urlsafe`-generated one-time password never used anywhere else.
- **No physical-device polkit capability**: none was created or touched this investigation — everything ran as the unprivileged invoking user against files in the workspace; `pkexec` was not invoked at any point.

## The defensive wrapper (`wrapper.py`)

Per Investigation 2, the assistant's exit status is untrustworthy and a failed `prepare-iso` can leave a credential-bearing temp file behind. The wrapper never checks `$?`; it determines success from explicit postconditions and owns cleanup itself:

- output exists, is a regular file (not a symlink), resolves to a path inside the workspace
- size within configured bounds
- `inspect-iso`'s own output (also postcondition-checked, not trusted by exit code) confirms fetch mode, URL, and certificate fingerprint match what was requested
- no `HTTP auth token` line present (confirms `--answer-auth-token` was never used)
- a raw byte scan of the output confirms none of the supplied forbidden strings (plaintext password, password hash, full answer content) appear
- the tmp/staging directory is inventoried before and after, with every leftover item force-removed and the directory's emptiness re-verified — cleanup failure is itself a reported postcondition, not assumed

**Verified against both outcomes, not just the happy path** (`test_wrapper.py`): a successful `prepare-iso` reports `ok=True` with all postconditions passing; an induced failure (output directory made unwritable, reproducing Investigation 2's finding) reports `ok=False` — and, critically, **the wrapper's own cleanup removed the 1.7GB credential-bearing `.tmp` file the raw tool left behind**, which is the wrapper's whole reason for existing.

**Bug found and fixed in this wrapper during testing**: the first version omitted the `prepare-iso` subcommand itself from the constructed argv (called `[binary, source_iso, --fetch-from, ...]` instead of `[binary, "prepare-iso", source_iso, ...]`), which the assistant correctly rejected as an unknown subcommand. Caught immediately by the postcondition check itself (`stdout_stderr_clean` failed on the resulting `Error: unknown subcommand` text) — direct evidence the postcondition-based approach catches wrapper bugs, not just tool bugs.

## Argv-free credential generation (`credential.py`)

`generate_one_time_password()` produces a `secrets.token_urlsafe`-based credential in process memory only. `hash_password_sha512crypt()` hashes it via `subprocess.run(["openssl", "passwd", "-6", "-salt", salt, "-stdin"], input=password+b"\n", shell=False)` — the plaintext crosses only a dedicated stdin pipe opened with a fixed argument array; it never appears in `openssl`'s own argv, in any environment variable, or in shell history (no `shell=True` anywhere, so no shell tracing/parsing of the secret is possible either).

**Methodology error caught and fixed here too**: while building the *test* canaries for this investigation's own harness (a separate, smaller mistake from Investigation 2's), the first draft of a manual `openssl passwd -6 -salt X plaintext` command was again written with the plaintext positional — caught before use in the actual credential-generation module itself, which was written correctly from the start using the stdin-pipe pattern. Worth flagging as a recurring risk: the argv-unsafe pattern is the "obvious" one to reach for, and needs active vigilance every time, not just a one-time fix.

**Yescrypt investigated, confirmed unavailable on this host**: `openssl passwd --help` lists only `-6` (SHA-512), `-5` (SHA-256), `-1`/`-apr1` (MD5 variants) — no yescrypt. `mkpasswd`/the `whois` package (which provides it) is not installed, and installing it would violate Milestone 0's no-host-modification constraint. Python's `crypt` module was removed in this host's Python 3.14. `hash_password_yescrypt()` checks for `mkpasswd` via `shutil.which` and returns `None` cleanly rather than failing when it's absent — confirmed `yescrypt_available=False` in the actual run. **Per Investigation 2, no algorithm is required or recommended by Proxmox** (`root-password-hashed` is an unvalidated opaque string) — so SHA-512 here is a pragmatic choice driven by what this host can actually produce without violating Milestone 0's constraints, not a claim that it's the strongest or preferred format Proxmox itself would recommend.

## The ephemeral answer server (`answer_server.py`)

Single-use, TTL-bounded, hardware-fact-checked, per the architecture from Investigation 2's decision record. Threat model stated explicitly in the module's own docstring (and restated per review's correction): **this protects against accidental cross-session delivery and generic/opportunistic clients — it does not authenticate a hostile client that already possesses the ISO and can reproduce the expected QEMU hardware facts**, since those facts are observable inside the guest, not secret.

### Test matrix (`test_answer_server.py`) — all 10 scenarios passed, each against its own fresh server instance

| Scenario | Result |
|---|---|
| Valid first request succeeds | PASS (status=200, exact answer content returned) |
| Second request denied | PASS (403, "already consumed") |
| Expired request denied | PASS (410) |
| Wrong session denied | PASS (404) |
| Hardware mismatch denied | PASS (403, "hardware mismatch") |
| Plain HTTP rejected pre-flight | PASS (`preflight.require_https` raises before the assistant is ever invoked) |
| HTTPS accepted (control case) | PASS |
| Missing cert fingerprint rejected | PASS (`preflight.require_cert_fingerprint` raises) |
| Empty cert fingerprint rejected | PASS |
| Redirect-to-another-origin rejected/proven impossible | PASS — proven via a real pinned-client connection to a separate "evil" TLS server presenting a *different* certificate: the pin check rejects the evil server's own certificate before any redirect response is ever read, so a redirect can't be followed to a substituted origin regardless of HTTP-level redirect handling. **Caveat stated plainly**: this proves the *pinning mechanism* rejects a mismatched certificate; it does not exercise the real `proxmox-fetch-answer` client's own redirect-following code path directly (that binary only exists inside the installer's initrd — see below for how it *was* exercised for real).

### Redaction

The server's `log_message`/`do_POST` logging never includes the full session ID (only an 8-character prefix + `...`) or raw hardware-fact values in its normal log stream — only boolean match/mismatch results. (Note: in this investigation's actual orchestration scripts, `logging.basicConfig` was never called in the long-lived server process, so even these redacted INFO-level messages produced no visible output at all — a real gap, noted under Remaining Uncertainty below, though it had no security consequence since it only means *less* was logged, not more.)

## Two real defects found and fixed while getting the real install to work

### 1. `restrict=on` blocks guest→host access entirely, not just guest→LAN/internet

**Original assumption** (stated in the initial design): QEMU SLIRP's `10.0.2.2` host alias would remain reachable from the guest for arbitrary host TCP ports even with `-nic user,restrict=on`, since `restrict=on` is documented as blocking "outside" network access. **This was wrong, demonstrated directly**: with `-nic user,restrict=on,mac=...`, the guest correctly obtained a DHCP lease from SLIRP's internal server (10.0.2.2), performed IPv6 router solicitation successfully (also SLIRP-internal), but a real POST to `https://10.0.2.2:<port>/...` failed with **`io: Connection refused`** — captured directly via a VNC screendump of the installer's actual console output (see below; this output never reached the serial log at all, a separate finding).

**Root cause**: `restrict=on` blocks the guest from reaching *any* real host-bound TCP service via 10.0.2.2, not just external destinations — DHCP/DNS/router-advertisement traffic works because SLIRP implements those protocols internally, not because they're proxied to a real host socket.

**Fix, verified working**: `-netdev user,id=net0,restrict=on,guestfwd=tcp:10.0.2.100:8443-tcp:127.0.0.1:<port>` plus `-device virtio-net-pci,netdev=net0,mac=...` (the long form, since `guestfwd` isn't expressible via the `-nic` shorthand). `guestfwd` punches one explicit, single-service exception through `restrict=on`, forwarding a fixed guest-visible address/port directly to a specific host port entirely within QEMU's own userspace — no bridge, no tap device, no capability requirement. **This is actually a stronger isolation story than the original design**: instead of "block everything except the general LAN/internet path," it's "block everything, full stop, except this one named service" — a smaller, more explicit exception. Confirmed via a real POST reaching the answer server and receiving a real response once this was in place.

### 2. Hardware-fact field name assumed incorrectly from documentation paraphrase

`_check_hardware()` originally read `dmi.system.product_name` or `dmi.system.product`, guessed from the wiki's prose description rather than the real payload. The real `proxmox-fetch-answer` client's POST body was captured directly (a throwaway echo server, `echo_server.py`, run through the same `guestfwd` path) and shows the actual schema:

```json
{
  "$schema": {"version": "1.0"},
  "product": {"fullname": "Proxmox VE", "product": "pve", "enable_btrfs": true},
  "iso": {"release": "9.2", "isorelease": "1"},
  "dmi": {"baseboard": {}, "chassis": {"serial": "", "asset_tag": ""},
          "system": {"serial": "", "sku": "", "name": "baseline-m0-synthetic-inv3"}},
  "network_interfaces": [{"link": "ens3", "mac": "52:54:00:BA:5E:11"}]
}
```

The correct field is **`dmi.system.name`**, not `product_name`/`product`. Fixed in `answer_server.py`. Also note the MAC is sent **uppercase** by the real client — harmless here since both sides of the comparison are lowercased before matching, but worth stating precisely rather than assuming case doesn't matter without checking (it was checked). This mismatch is exactly why the first real end-to-end attempt (against the corrected `guestfwd` networking) still failed with a **403 hardware mismatch** — genuine evidence the whole round-trip (POST reaches the server, TLS pinning validates, session/TTL checks pass, and only the hardware-fact comparison itself was wrong) was working correctly *before* this fix, not after — the fix narrowed the actual bug rather than papering over a broader failure.

### Both defects were caught by direct observation, not assumption

Diagnosing #1 required realizing the installer's own diagnostic/log output goes to **the VGA console (tty3), not the serial port** — serial.log stayed frozen at "Loading initial ramdisk..." for the full 30-minute timeout of the *first* full-run attempt, giving no indication of what was actually happening. Switched to periodic `screendump` via the QEMU monitor socket (a Unix socket, HMP `screendump <path>.ppm`, converted to PNG with Pillow for direct viewing) — this is now the primary progress-monitoring mechanism for any future QEMU-boot-based investigation in this project; **serial-only monitoring of this installer is not viable** and should not be assumed to work in Investigation 4 or later either.

## The successful run

### Exact QEMU command (redacted — no secret material appears in it anyway, since credentials never touch argv, but the session ID/fingerprint are shown truncated for hygiene)

```
qemu-system-x86_64 \
  -enable-kvm -cpu host -m 3072 -smp 2 \
  -drive file=<workspace>/target.img,format=raw,if=virtio,cache=none \
  -cdrom <workspace>/prepared.iso \
  -boot d \
  -netdev user,id=net0,restrict=on,guestfwd=tcp:10.0.2.100:8443-tcp:127.0.0.1:<answer-server-port> \
  -device virtio-net-pci,netdev=net0,mac=52:54:00:ba:5e:11 \
  -smbios type=1,product=baseline-m0-final-run \
  -vnc :20 \
  -monitor unix:<workspace>/monitor.sock,server,nowait \
  -serial file:<workspace>/serial.log \
  -no-reboot
```

### Complete attached-device inventory

- **Storage**: exactly two entries — `target.img` (the sparse regular file created by this run, `if=virtio`) and `prepared.iso` (`-cdrom`, read-only, workspace-local). No other `-drive`, no `-hda`/`-hdb`, no `virtfs`/host directory sharing, no USB storage passthrough.
- **Network**: QEMU usermode (SLIRP) only, `restrict=on` with a single `guestfwd` exception to the answer server. No `-netdev bridge`, no `-netdev tap`, no physical NIC passthrough of any kind.
- **No host block device was ever accessible to the guest**: the only two `file=`/`-cdrom` paths given to QEMU resolve under the workspace directory (verified by construction — the wrapper and orchestration script only ever pass paths returned by `workspace.create_workspace()`, never a caller/environment-supplied path). No `/dev/*` string appears anywhere in the QEMU argv.

### Answer-server request/result timeline

Precise server-side timestamps were not captured for this specific run (the `logging.basicConfig` gap noted above), but the sequence is established with certainty from direct, independent evidence:
1. Session armed with a 1800s TTL immediately after ISO preparation completed.
2. QEMU booted; installer selected the automated-install boot entry after its documented 10s auto-timeout.
3. A screendump at t=90s (see below) shows the install already at 99% ("make system bootable"), meaning the POST → 200 response → answer parsing → disk partitioning → package installation sequence had already completed within that window.
4. QEMU exited on its own between t=120s and t=150s — consistent with `-no-reboot` intercepting the guest's post-install reboot attempt (the intended completion signal).
5. **A POST replay against the same session, issued after the real install had already used it**, was directly tested and returned `403 already consumed` — live proof the single-use enforcement held against the real client's actual usage, not just the synthetic test matrix.

### Installer completion signal

QEMU process exit (via `-no-reboot`) is the primary, mechanically-detected signal, cross-validated by: (a) the t=90s screendump showing 99% progress / "make system bootable", and (b) the resulting image's own structure (below) being a fully-formed, correctly-partitioned Proxmox install rather than a partial/empty one.

### Resulting image size and partition structure (via `fdisk -l` and `blkid -p` on the file directly — no loop device, no mount)

```
Disk <target.img>: 16 GiB, 17179869184 bytes, 33554432 sectors
Disklabel type: gpt

target.img1      34     2047     2014  1007K  BIOS boot
target.img2    2048  1050623  1048576   512M  EFI System
target.img3 1050624 33554398 32503775  15.5G  Linux LVM
```
`blkid -p` confirms `PTTYPE="gpt"` and a real PTUUID. Apparent size 16GiB (sparse); **actual allocated size 7.1GB** — consistent with a genuine, non-trivial Debian/Proxmox base install, not an empty or truncated image.

### Static installation checks

- GPT partition table present with the expected three-partition layout for a hybrid BIOS+UEFI-bootable Proxmox install (BIOS boot stub, ESP, LVM-backed root/swap).
- `blkid -p` recognizes the partition table without error.
- Real disk usage (7.1GB of 16GB sparse) is in the range expected for an installed Debian-trixie-based Proxmox VE system.
- (UEFI-vs-BIOS boot-path verification and an actual boot test of the installed system are explicitly **Investigation 4's** scope, not repeated here — this investigation confirms the partition/content structure is present and plausible, not that the resulting disk successfully boots.)

### Cleanup results

- `prep_tmp` (the assistant's own staging directory): empty after both the successful run and the induced-failure test in `test_wrapper.py`, confirmed by the wrapper's own `tmp_cleanup_verified` postcondition, which itself force-removes any leftover and re-checks emptiness rather than assuming success.
- Post-investigation artifact cleanup (not part of the wrapper, done manually after evidence was captured): all prepared ISOs (~1.7GB each, several generated across diagnostic attempts) and the sparse target images were deleted; only small logs, two representative PNG screendumps, and `state.json` were retained under `experiments/m0-inv3/runs/` (gitignored, ~7.6MB total). Nothing from this investigation was committed to git.

### Canary search results

- Plaintext one-time credential: **absent** from the final 16GB image (direct raw byte search over the full file).
- Hostname (`m0inv3-final.invalid`): **present**, as expected — this is legitimate configuration data, not a secret, and its presence confirms the answer file's content was genuinely applied, not merely fetched and discarded.
- The password *hash* was not separately searched for in the final image this run (it would legitimately appear in `/etc/shadow`-equivalent content inside the LVM-backed filesystem, which this investigation deliberately does not mount or inspect at the file level, consistent with the "no device nodes" boundary) — its presence there is expected and correct, not a leak; confirming this would require Investigation 4/6's boot-based verification, not a raw file scan of an ext4-inside-LVM-inside-sparse-file structure.

### Failure experiments

1. **Corrupted/truncated source ISO** (first 50MB only): `prepare-iso` detected this immediately and refused cleanly — `prep-tmp` empty, no partial output, matching Investigation 2's finding.
2. **Unwritable output directory** (`chmod 555`): reproduced Investigation 2's finding directly — a complete, hash-bearing `.tmp` file was left in the staging directory by the raw tool; **the wrapper's own cleanup removed it and verified removal**, which is the wrapper's core justification.
3. **30-minute timeout on the first full attempt**: genuinely occurred (not simulated) due to defect #1 above; the orchestration script's timeout-handling path fired correctly — process group killed, `indeterminate_image` reported, no automatic retry attempted. This is real evidence the required failure contract (§ from the instructions: *"A QEMU timeout or crash produces indeterminate_image, never success and never an automatic retry"*) works as specified, obtained via an actual failure rather than a staged one.
4. **Stale prepared-ISO reuse** (an unplanned, informative accident): reusing an old prepared ISO whose embedded URL pointed at a now-exited answer server produced `Connection refused` — a useful negative control confirming the "connection refused" signature is specifically about reachability, distinct from the hardware-mismatch and already-consumed rejection signatures, which all present differently and unambiguously in the installer's own output.

## Remaining uncertainty

- Server-side request logging had no configured handler in the long-running orchestration process, so precise request timestamps for the successful run rely on screendump timing and QEMU exit timing rather than the server's own log — a real gap to fix before this becomes reusable Milestone 1 code, not a security issue (it only under-logs, doesn't leak).
- The evil-redirect test proves the *pinning mechanism* rejects a mismatched certificate; it does not exercise `proxmox-fetch-answer`'s own redirect-following code directly (that binary isn't invocable outside the installer environment) — Investigation 2's finding that the source shows no explicit redirect handling remains the best available evidence for the real client's behavior specifically.
- UEFI/BIOS boot-path correctness and an actual boot of the installed system are untested here by design (Investigation 4's scope).
- The password hash's presence/correctness inside the installed filesystem was not directly verified (would require mounting, out of scope here).
- `guestfwd`'s isolation properties were validated functionally (it works, and `restrict=on` blocks everything else) but not adversarially (e.g., an attempt from the guest to reach a *different* host port than the one forwarded was not explicitly tested) — reasonable to assume `restrict=on` still blocks that given the DHCP/connection-refused evidence already gathered, but not independently confirmed.

## Accepted / rejected approach

**Accepted**: sparse-file-only image backend, defensive postcondition-based wrapper (never trusting the assistant's exit code), ephemeral single-use TTL-bounded answer server with hardware-fact binding via `dmi.system.name` (corrected field), `guestfwd`-based network isolation (stronger than the originally-planned `restrict=on`-only approach), VNC-screendump-based progress monitoring (serial-only monitoring is rejected as unreliable for this installer).

**Rejected**: relying on `-nic user,restrict=on` alone for guest→host answer-server reachability (doesn't work, demonstrated directly); relying on serial console output as a progress/completion signal (the installer doesn't write meaningful progress there); assuming documentation-paraphrased field names without capturing and checking the real payload.

## Security implications

- The `guestfwd` isolation model is preferable to the originally-planned approach precisely because it's a smaller, more explicit exception ("reach exactly this one forwarded service") rather than "reach the general host-proxied network path minus LAN/internet" — worth carrying into Milestone 1's real design as the default networking approach for any answer-server-dependent QEMU session, physical-drive milestone included (Milestone 3, once reached, should reuse this same `guestfwd` pattern rather than re-deriving it).
- Confirmed live, not just in the test matrix: single-use session enforcement holds against the real client's real usage pattern, including a genuine post-consumption replay attempt.
- The two defects found were both caused by **unverified assumptions substituting for direct observation** (SLIRP's `restrict=on` behavior, and the DMI field name) — consistent with the standing project lesson about not letting a mechanism's documented/assumed behavior stand in for what was actually checked.

## Tests added

`test_wrapper.py` (defensive wrapper, success + induced-failure paths), `test_answer_server.py` (10-scenario matrix covering the full single-use/TTL/hardware-binding/pre-flight/redirect-pinning behavior). Both are experiment-local (`experiments/m0-inv3/`, gitignored) — porting the surviving, corrected logic (`answer_server.py`'s fixed field name, `wrapper.py`'s postcondition set, `credential.py`'s argv-free pattern) into `baseline/lib/` with proper `tests/unit/` coverage is Milestone 1 work, not done here.

## Whether Investigation 4 is unblocked

**Yes.** A real, structurally-correct, unattended sparse-image install now exists and is reproducible. Investigation 4 (fresh-NVRAM boot verification, UEFI vs. legacy BIOS, portable EFI fallback, deterministic boot-success marker) can proceed against this same pipeline. Two carry-forward requirements for Investigation 4: (1) use VNC-screendump-based monitoring from the start, not serial-only; (2) this run used legacy BIOS boot (`-boot d`, no OVMF/UEFI firmware) by default — Investigation 4 needs to explicitly add the UEFI path (OVMF firmware) as its own separate, labeled run rather than assuming this run's success says anything about UEFI portability.
