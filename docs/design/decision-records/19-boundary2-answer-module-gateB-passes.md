# Decision record: Boundary 2 (`drive_setup_answer.py`) promoted; Gate B fully passes, real verification

Date: 2026-09-22
Investigator: Claude Code
Status: complete. `baseline/lib/drive_setup_answer.py` consolidates the four previously-separate, already-proven experiment modules (`credential.py`, `answer_server.py`, `wrapper.py`, `workspace.py` from `experiments/m0-inv3/`) into one boundary, per the PRD's own reasoning (§4). 17 new unit tests (115/115 total passing). **Gate B fully passes**, verified for real: a real `prepare-iso` run, against the real assistant binary acquired via boundary 1, with a real ephemeral answer server, produced a prepared ISO whose every postcondition — fetch mode, URL, cert fingerprint, absence of forbidden canaries — was independently confirmed via `inspect-iso` output and a raw byte scan.

## Scope discipline

No push to `cliffthelin/baseline`. No physical device. No host package installation. No privilege escalation. No authorization-triggering host call. One real, disposable `prepare-iso` run against the cached source ISO (`iso_build/proxmox-ve_9.2-1.iso`), workspace deleted afterward.

## What was built

`baseline/lib/drive_setup_answer.py`, four concerns in dependency order:

1. **Workspace** (`create_workspace`, `inventory`, `diff_inventory`) — mode-0700 per-run directory, promoted near-verbatim.
2. **Credential** (`generate_one_time_password`, `hash_password_sha512crypt`, `hash_password_yescrypt`) — argv-free by design, promoted near-verbatim. Deliberately **not** given `Runner` injection: the security property under test is precisely that the plaintext never touches argv/env/shell, and `openssl` is a standard tool always present — faking this call would test less than running it for real.
3. **Ephemeral answer server** (`EphemeralAnswerServer`, `SessionState`, `AnswerHandler`) — single-use, TTL-bounded HTTPS server, promoted near-verbatim (one field-name fix carried over from earlier investigation history: `dmi.system.name`, not `product_name`, is the real client schema).
4. **`prepare_iso_defensively`** — retrofitted with `AnswerRunner` injection, matching `drive_setup_acquire`'s pattern (this boundary's one genuinely new design choice: the original `wrapper.py` called `subprocess`/`Path` directly, not testable without a real assistant binary). Never trusts `prepare-iso`'s or `inspect-iso`'s exit code (decision record 02's finding: every observed failure still returned 0) — success is determined purely from explicit postconditions against the filesystem and the tools' own stdout text, and the wrapper owns `tmp`-directory cleanup on every exit path including failure.

## Real verification, not just unit-tested

Combined boundary 1 (real acquire + extract of the assistant binary) with boundary 2 (real answer server + real `prepare_iso_defensively`) in one disposable run:

- Generated a real one-time password and SHA-512-crypt hash.
- Started a real `EphemeralAnswerServer` with a freshly-generated self-signed cert.
- Ran `prepare-iso --fetch-from http --url <answer-url> --cert-fingerprint <fp>` for real against the real cached Proxmox ISO.
- **Every postcondition passed**: no timeout, clean stdout/stderr, output exists as a regular file inside the workspace, plausible size, `inspect-iso` confirms `Auto-install: enabled` and the correct product, fetch mode/URL/fingerprint all match, no `HTTP auth token` embedded, and — critically — a raw byte scan of the entire prepared ISO confirms **none** of the plaintext password, the password hash, or the full answer TOML content appear anywhere in it (the `--fetch-from http` mode's whole point, per decision record 01/02: the answer file is never embedded in the ISO at all).
- `tmp_cleanup_verified`: the prep tmp directory was confirmed empty afterward.

This is Gate B's stated evidence requirement (§5: "Prepared ISO verified without booting — `inspect-iso` output and a raw byte scan confirm fetch mode, URL, cert fingerprint, and the absence of forbidden strings") satisfied exactly, against the real promoted module, not the old ad hoc experiment scripts.

## Tests added

`tests/unit/test_drive_setup_answer.py`, 17 tests:
- Workspace: mode-0700 creation, inventory/diff.
- Credential: high-entropy generation, valid hash shape, newline-in-password rejection.
- Answer server (real local TLS sockets + a test-only fingerprint-pinning client, `tests/unit/pinned_client.py` — deliberately real sockets, not `FakeRunner`, since this tests actual protocol/security behavior): valid first request succeeds; second request on the same session denied (403, already consumed); expired session denied (410); wrong session ID denied (404); hardware mismatch denied (403); a client pinned to the *wrong* fingerprint is refused before ever seeing a response.
- `prepare_iso_defensively` (`FakeAnswerRunner`-scripted): full success; **exit code 0 but stderr shows `Error:` still fails** (decision record 02's core finding, directly tested); missing output file fails; a forbidden canary string anywhere in the ISO bytes fails; tmp-dir cleanup happens on every path including failure; an output path resolving outside the workspace is rejected.

One real bug caught while writing the test suite itself (not the production module): the test-only `FakeAnswerRunner`'s `path_exists` initially checked only for an exact key match, so a directory containing files it had never itself been explicitly recorded as owning read as "does not exist" — causing `test_prepare_iso_cleans_up_tmp_dir_on_every_path_including_failure` to fail for the wrong reason (cleanup skipped as a no-op, not actually verified). Fixed by making the fake's `path_exists` directory-aware (a prefix match against any recorded file), matching real filesystem semantics. A test-infrastructure bug, not a `drive_setup_answer.py` defect — flagged here for the same reason decision record 18 flagged its own real-run bug: catching and reporting this kind of thing plainly is the discipline, not something to quietly fix and not mention.

## Security implications

`preflight.py` (`require_https`, `require_cert_fingerprint`, `require_no_auth_token`) was deliberately **not** promoted into `drive_setup_answer.py`, per the PRD's own §6 list marking it test-only infrastructure. This real verification run enforced the same three constraints inline at the call site (`--fetch-from http` with a `--url`/`--cert-fingerprint` pair, no `--answer-auth-token` anywhere) rather than through a reusable checked function — **whoever writes the real Gate B/C orchestration layer (the caller of `prepare_iso_defensively`) must enforce these three constraints explicitly, since no promoted module does it for them.** This is a real gap worth carrying forward, not a decision that the checks are unnecessary.

## Whether Gate C work is unblocked

Yes. Boundary 1 and boundary 2 are both done and real-verified; Gate B passes. Gate C ("Installation reaches explicit success — the literal `Finished: 'ok'`/`Installation done` sequence captured via screendump, never inferred from QEMU exit code or partition structure alone") needs boundary 3 (`drive_setup_install.py` — QEMU invocation, `guestfwd`-isolated networking, screendump-based explicit-success detection) promoted next, reusing the same QEMU-invocation and screendump patterns this whole session's disposable install workspaces have already exercised repeatedly and successfully.
