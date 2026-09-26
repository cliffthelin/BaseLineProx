# Decision record: TestPersistence Milestone 5 - application-grant proof

Status: **complete, real QEMU execution, all 25 recorded sub-steps passed on the final run.** Entirely synthetic (`TestSystem-A`, `TestPersistenceDisk-001`, `TestPersistence-001`, `TestPerson-001`, `TestDocuments`, `TestApplication-A`, `TestApplication-B`, `TestGrant-001`). No physical hardware, no host privilege escalation, no live internet access from inside the guest. Builds on Milestone 2 (`d31d509`), Phase A (`e5144a9`), and Phase B (`dc22f17`/`39458d0`) - branch `local/testpersistence-m5-grants`, unmerged into `main`.

```
identity_scan.current_content: pending_full_scan
identity_scan.git_history:     known_findings_scope_unknown
identity_scan.full_scan:       pending_operator_verification
```

Entirely synthetic; neither depends on nor resolves that gate.

## What this proves (PRD acceptance cases 3, 7, 8)

Unlike Phase B, this experiment implements and exercises an actual **minimal access-broker boundary** - not just a manifest field. Two synthetic application principals (`TestApplication-A`, `TestApplication-B`) are separate Linux system accounts (`useradd -M`, `nologin` shell, each with its own private group). A grant is enforced with real `chown`/`chmod` on the collection directory inside the mounted, LUKS2-encrypted filesystem - a genuine kernel DAC boundary, tested by attempting reads **as each principal** (`sudo -u testapplication-a ...` / `sudo -u testapplication-b ...`) and checking the actual permission-denied/allowed outcome, not asserted.

## Step-by-step result (final passing run, all 25 recorded sub-steps `OK`)

| Step | Result |
|---|---|
| Boot `TestSystem-A` with `TestPersistenceDisk-001`, login | OK |
| Install offline `cryptsetup-bin` closure (same verified process as Phase B) | OK |
| LUKS key written and locked to `0600` (see "bug found" below) | OK |
| `cryptsetup luksFormat` / `open`, `mkfs.ext4` + mount (real LUKS2 + real EXT4-fs kernel mount) | OK |
| Create `testapplication-a` / `testapplication-b` as separate Linux principals, each with its own private group | OK |
| Initialize authenticated manifest + append-only ledger (`store_created`) | OK |
| Create the `TestDocuments` collection, default-deny (`root:root`, `700`) | OK |
| **Case 3**: install per-application state directories, each owned by its own principal, isolated from the other | OK |
| Issue `TestGrant-001` (`TestApplication-A` → `TestDocuments`, read) in the ledger | OK |
| Broker enforces the grant via `chown`/`chmod` to `testapplication-a` | OK |
| **Case 3 (continued)**: `TestApplication-A` can now read `TestDocuments` | OK |
| **Case 7**: `TestApplication-B` cannot read `TestDocuments` (permission denied) | OK |
| **Case 7 (continued)**: `TestApplication-B` cannot read `TestApplication-A`'s own app-state either | OK |
| Neither application principal can read the raw block device, the device-mapper node, or the LUKS key file | OK |
| Revoke `TestGrant-001` in the ledger (second explicit `authorize()` gate, no default) | OK |
| Broker enforces the revocation via `chown`/`chmod` back to `root:root` | OK |
| **Case 8**: `TestApplication-A`'s access is removed after revocation | OK |
| **Case 8 (continued)**: the underlying data is still present and readable by root - revocation removes access, never deletes data | OK |
| Manifest and ledger dumped | OK |
| **Host-side verification** (using the real `baseline.lib.testpersistence.manifest` module, not a re-implementation): event sequence exactly `[store_created, grant_issued, grant_revoked]`; ledger HMAC chain cryptographically verifies; `TestGrant-001.effective` is `False` after revocation | OK |
| Clean unmount/close, clean shutdown | OK |

## Scope claims

- This experiment is single-system (`TestSystem-A` only) - it does not repeat Phase B's carrier-migration proof; that remains proven separately in decision record 28.
- The access-broker mechanism here is deliberately minimal (Unix ownership/permission changes on one collection directory) - a real, kernel-enforced boundary, but not a generic broker daemon that reads arbitrary grants from the manifest and reconfigures arbitrary mounts. Building that generic mechanism is future work; this experiment proves the *boundary property* (isolation + revocation, kernel-enforced) holds for the one grant it exercises.
- No claim is made about simultaneous multi-grant conflicts, grant expiry (`duration` beyond `until_revoked`), or the `authorized_by`/authority-ledger separation beyond what's recorded in the manifest fields themselves.

## Real bugs found and fixed while getting this to genuinely pass (not simulated)

1. **`useradd -N` silently broke every grant-enforcement `chown`.** `-N` disables creating a user-private group, so no group named `testapplication-a` existed; `chown testapplication-a:testapplication-a ...` failed with "invalid group", and because it was chained with `&&`, every subsequent command in that chain silently didn't run either. The evidence check only looked for the trailing marker echo (which always fires via `;`), so it reported `OK` despite the real command having failed. Fixed by dropping `-N` (matching Debian's own default behavior) and by hardening the affected checks to also reject `"chown:"`/`"invalid group"` text in the captured output, not just check for the marker.
2. **The LUKS key file was created with the default umask - normally 644, world-readable**, which would have defeated the "no raw key access" proof entirely if left unfixed. Caught before running by inspection of the earlier Phase B pattern; fixed with an explicit `chmod 600` immediately after writing it, verified in the evidence (`-rw-------`).
3. **Extracting the ledger's JSON array by searching for a literal `"["` in raw console text** matched bash's own bracketed-paste-mode escape sequence (`\x1b[?2004l`, which contains a literal `[`) instead of the real array's opening bracket - `json.loads` failed with `Expecting value: line 1 column 2`. Phase B never hit this because it only ever extracted a top-level `{...}` object (no ambiguous `[` collision) and never dumped a *separate* ledger file. Fixed by wrapping each dump in unique text sentinels (`echo JSONSTART; cat ...; echo JSONEND`) and extracting between those, rather than guessing brace/bracket positions in raw terminal output.

## Retention

No credentials, encryption keys, prepared ISOs, or disk images were retained after this record was written. Deleted after evidence capture: `TestPersistenceDisk-001.qcow2`, `TestSystem-A.qcow2`, `seed.iso`, `pkgs.iso` (via `qemu_harness_safety.delete_validated_image` - exact validated paths, never a glob), and the download cache (base image + APT verification workspace, re-verified fresh for this experiment against the same checksums/signatures recorded in decision record 28, then deleted again once used). Nothing under `experiments/testpersistence-m5-grants/` remains except this record's own evidence, checked for prohibited identifiers and absolute host paths (none found) before this commit.

## Verification performed before this commit

- Evidence JSON checked for real identifiers and absolute host paths - none found.
- Full repository test suite: 530/530 passing (no regressions from the harness commit).
- This record itself checked for the same before commit.
