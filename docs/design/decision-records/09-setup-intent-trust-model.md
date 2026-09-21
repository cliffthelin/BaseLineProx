# Decision record: Setup-intent trust model consolidation

Date: 2026-09-21
Investigator: Claude Code
Status: complete — entirely offline/synthetic, no authorization of any kind triggered or attempted.

## Scope discipline

This investigation used only already-installed libraries (`cryptography`, `pynacl` both present; nothing was installed). All keys are freshly generated Ed25519 test keys held in memory. All ledger state lives under a temp directory (`experiments/m0-inv9/`, gitignored). No device access, no host configuration change, no sudo/pkexec/polkit/D-Bus call, no credential prompt, no keyring, no network call of any kind was made or attempted — every operation in this investigation is a pure, local Python computation. Nothing was "tried once to see if permission is available" — per instruction, any operation that might require authorization was skipped outright and recorded as unverified rather than attempted.

## 1. Threat-model sentence

**This mechanism detects accidental corruption or mismatch between what the installer GUI's operator chose and what offline staging/first-boot actually applies — it does not defend against a hostile actor who has write access to the target filesystem**, because (per §3 below) the verification key is deployed beside the bundle on that same filesystem in the shape this investigation and the PRD describe. Protected asset: the integrity of the operator's actual choices as they flow from the GUI session to first-boot execution. Attacker capability assumed defeated: none with filesystem write access — the boundary this mechanism actually holds is against non-adversarial corruption (a bad copy, a stale bundle, a mismatched target), not tampering by someone who can edit files on the drive.

## 2. Threat/failure coverage table

| Failure mode | Mechanism that catches it | Demonstrated here? |
|---|---|---|
| Accidental corruption (bit flip, truncated copy) | Signature verification fails against canonical bytes | Yes — tampered-payload test |
| Offline modification of the bundle after signing | Signature verification fails | Yes — tampered-payload test |
| Key substitution (attacker signs with their own key, claims a trusted key_id) | Verifier looks up the public key by key_id and checks the signature against *that* key, not whatever key actually produced it — a forged claim fails | Yes — substituted-key test |
| Replay (same intent reapplied) | Existence-based consumed-intent ledger, checked before any other policy is allowed to matter | Yes — replay test |
| Stale intent (expired) | `expires_at` checked against verification-time `now` | Yes — expired-intent test |
| Target mismatch (bundle applied to wrong install) | `target.install_session_id` must equal the expected session id | Yes — target-mismatch test |
| Action expansion (execute more/different than what was signed) | Every proposed action must be a member of the signed action set *and* the caller's allowed-action policy | Yes — action-expansion test |
| Schema downgrade (older/unrecognized schema silently accepted) | Verifier maintains an explicit known-schema allowlist; anything else is rejected, not best-effort parsed | Yes — schema-downgrade test |
| Unknown key | Same code path as "signature invalid" — verifier never distinguishes "wrong signature" from "key not in trust store" at the API boundary, to avoid leaking which failure occurred | Yes — unknown-key test |
| Consumed-intent rollback (attacker/accident restores an older ledger snapshot to un-consume an intent) | **Not demonstrated** — this requires real filesystem snapshot/restore, which this investigation could not touch. Documented as a known, undemonstrated gap: the ledger's durability guarantee (fsync+atomic rename) proves the *write* path is crash-safe, not that the *storage medium itself* resists rollback by an attacker who can restore an old snapshot. |

## 3. Integrity/corruption detection vs. authentication — the distinction the PRD's "signed" language must not blur

- **Integrity/corruption detection**: the verification key lives beside the bundle, on the same target filesystem the bundle itself is written to. Under this deployment shape, the signature proves the bundle wasn't accidentally altered between signing and verification (a real, useful guarantee against corruption, transfer errors, and version mismatches) — but it proves nothing against an attacker who can write to that filesystem at all, since they could simply replace the key alongside the bundle and re-sign with a new keypair of their own. **This is the deployment shape this investigation's tests model**, and it is the honest framing for the PRD to use unless the deployment shape changes.
- **Authentication**: the trust anchor (the verification public key, or a fingerprint/hash of it) is provisioned through a channel independent of the bundle's own filesystem — e.g. baked into the first-boot TUI's own binary/image at build time, not read from the same drive the bundle rides on. Under that shape, and only that shape, the signature defends against a filesystem-writing attacker, because they cannot also rewrite the verifier's independently-provisioned trust anchor. **This investigation's `verify_intent()` takes `trusted_keys` as a parameter precisely so this distinction is structural in the code**: the caller decides where that dict comes from, and the module makes no assumption either way. Which shape the real system uses is a deployment decision the PRD needs to state explicitly — this record does not resolve it, only documents that the difference is real and the consequences are opposite (one is a corruption check, the other is a real access-control boundary).

## 4. Minimum signed fields — implemented and exercised

All present in `make_payload()` / `SignedIntent`, and each was exercised by at least one policy-rejection test:

- **Schema and version**: `payload["schema"]` — checked against an explicit allowlist (`KNOWN_SCHEMAS`), rejecting anything unrecognized rather than best-effort parsing.
- **Unique intent ID**: `payload["intent_id"]` — the replay ledger's key.
- **Creation and expiration times**: `payload["created_at"]` / `payload["expires_at"]` — both checked (future-dated AND expired are separately tested).
- **Target identity constraints**: `payload["target"]["install_session_id"]` — must equal the verifier's expected value.
- **Exact requested actions and parameters**: `payload["actions"]` — a list of `{action, params}`; the verifier checks membership against an allowed-action set, not just presence.
- **Policy bounds**: `payload["policy_bounds"]` plus a caller-supplied `max_actions` cap enforced independently of what the bundle itself claims its bounds are (a bundle can't declare its own policy bounds as unlimited and have that trusted — the cap is supplied by the verifying context, not the document).
- **Signer and key identity**: `signed["signer_key_id"]`, resolved against the verifier's own trust store, never trusted at face value (the substituted-key test specifically proves a forged `signer_key_id` claim doesn't help an attacker who lacks the matching private key).

## 5. Canonical serialization

Implemented as: `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)` — deterministic key order, no incidental whitespace, ASCII-escaped so byte representation doesn't vary by encoding environment. Signed and verified bytes are always this canonical form, never the original wire bytes (which might be pretty-printed, differently ordered, etc.).

Separately, **parsing** uses `object_pairs_hook` to reject any JSON object containing a duplicate key outright (`DuplicateKeyError`), rather than relying on canonicalization alone — Python's default `json.loads` silently keeps the *last* value for a duplicate key, which means a naive implementation could display one value while a different tool (or a different JSON library entirely) reads the *other* value from the same bytes. Rejecting duplicates at parse time closes that ambiguity before canonicalization ever runs, rather than hoping canonicalization papers over it. Demonstrated directly in the duplicate-key test.

## 6. Replay protection

Implemented as a durable, **existence-based** consumed-intent ledger: `record_consumption()` writes to a temp file, `fsync`s the file, atomically renames it to `<intent_id>.json`, then `fsync`s the containing directory (the same fsync-file+fsync-dir+atomic-rename pattern proven durable under `SIGKILL` in Investigation 6). `is_consumed()` checks only whether that final-named file **exists** — it deliberately never parses the file's contents to make the block/allow decision.

This existence-only design was a deliberate choice, tested directly: a ledger entry with genuinely corrupted, unparseable content (test 9b) still correctly counts as "consumed" and blocks replay, because the file's mere presence at the canonical path is the signal, not its content. The alternative (parse-then-decide) would fail open on corruption — exactly the wrong direction for a security-relevant durable record.

- **Behavior after interruption**: a crash between writing the temp file and the atomic rename leaves *no* file at the final path — the intent correctly reads as **not consumed** (test 9), since the rename never happened. This is the correct direction for an *interrupted* write (nothing was actually applied yet, so not-consumed is honest) and is distinct from *corruption of an existing, already-renamed record* (test 9b), which fails closed the other way.
- **Restoration of an older filesystem snapshot**: **not tested** — this would require real filesystem/device-level snapshot and restore, outside what a synthetic, no-privilege investigation can touch. Documented as an explicit, undemonstrated gap: if an attacker (or an accidental backup restore) can roll the ledger directory back to a state predating a consumption record, the durability guarantee proven here (the write path is crash-safe) says nothing about resistance to that class of rollback. A real implementation needs either a monotonic/tamper-evident ledger (e.g. hash-chained entries, or a ledger location outside what a snapshot restore would affect) if rollback resistance is actually required — this investigation does not claim the current design provides that.
- **Loss or corruption of that record**: corruption is tested and fails closed (blocks replay, per above). Outright *loss* (the ledger directory itself destroyed) was not separately tested but follows directly from the existence check: a missing file reads identically to "never consumed," so total ledger loss silently re-enables replay of every previously-consumed intent. This is a real, stated limitation, not a claim that loss is handled — the ledger's durability depends entirely on the durability of its storage location, which this investigation did not evaluate.

## 7. Fail-closed handling — all conditions exercised

| Condition | Test | Rejected? |
|---|---|---|
| Malformed (no payload / no actions / bad timestamps) | Structural checks in `verify_intent` | Yes (code path exercised via other malformed-shape tests; explicit malformed-only test not separately added given time budget — see Remaining uncertainty) |
| Expired | Test 5 | Yes |
| Future-dated | Test 5b | Yes |
| Unknown key | Test 3b | Yes |
| Revoked key | Same mechanism as unknown key (removal from trust store) | Yes, by construction — not separately re-tested since it's the identical code path |
| Mismatched target | Test 6 | Yes |
| Previously consumed | Test 8 | Yes |
| Downgraded schema | Test 7b | Yes |
| Over-broad / expanded actions | Test 7 | Yes |

Every branch in `verify_intent()` is a named rejection reason; there is no default-permit fallthrough — the function can only return `(True, "ok")` by passing every check in sequence.

## 8. First-release key provisioning and rotation — options and recommendation

Options considered (documentation only — no provisioning was implemented, per "do not create a production installer framework"):

1. **Ephemeral per-run keypair, public key embedded in the bundle itself.** Simplest, but reduces the mechanism to corruption-detection only (§3) even in the best case, since there's no independent trust anchor at all — anyone who can write the bundle can also write a fresh keypair. Rejected as insufficient for anything beyond the corruption-detection framing, but note that corruption-detection is the actual approved use case per §1, so this option is not wrong, just needs to be labeled honestly.
2. **Persistent signing key, held by the installer GUI build/release process, with the corresponding public key baked into the first-boot TUI's own image at build time.** This is the shape required for the "authentication" framing of §3 to actually hold, since the verifier's trust anchor no longer lives on the same filesystem as the bundle. Requires real key-lifecycle management (generation, secure storage during CI/release, rotation) that this investigation explicitly did not implement or test.
3. **Per-installer-instance keypair with a separate out-of-band fingerprint distribution** (e.g. operator manually confirms a short fingerprint). Strongest against filesystem-only attackers, worst for the "install a drive on a machine with no human present at first boot" use case central to this PRD, since it reintroduces a manual step the first-boot design otherwise avoids.

**Recommendation**: Option 2, with the explicit, stated limit that **this investigation did not build or test the key-lifecycle plumbing** — real work for Milestone 1+ includes where the persistent signing key is generated and stored during release builds, how compromise of that key is detected/rotated, and how already-shipped first-boot images (with an old baked-in public key) are handled after rotation. Recommending the shape does not mean the shape has been validated; only the verification-side logic (structurally separating trust-store lookup from signature math) has been.

## 9. Confirmation that signature validity never constitutes execution authorization

Confirmed by construction, not re-implemented here (Investigation 6 already built and proved the actual mechanism — this investigation deliberately did not duplicate it, per the instruction to keep this short and not build a production framework):

- `verify_intent()` returning `(True, "ok")` answers only "this bundle is authentic, current, correctly targeted, and within policy bounds" — it is a **precondition** for proposing execution, never itself an execution trigger. Nothing in this module calls or schedules any action.
- The actual execution gate is the one Investigation 6 built and tested under real `SIGKILL` conditions: facts are discovered unattended, the proposed action is displayed in full on tty1, and the flow blocks indefinitely on literal `"CONFIRM"` typed input — no timeout, no default, EOF is not treated as confirmation, tty2 remains a live escape route throughout. That mechanism is unchanged by this investigation and is the one this trust model is designed to feed into: `verify_intent`'s output becomes the "proposed action" Investigation 6's state machine displays, not a bypass of it.
- This investigation's own test suite runs zero execution — every test only calls verification/ledger functions and asserts on their return values.

## Remaining uncertainty

- Consumed-intent rollback via filesystem/snapshot restore — not tested, real device/filesystem work required (Milestone 3-class, same category as Investigation 8's remaining gaps).
- Real key-lifecycle plumbing for the recommended provisioning option (§8) — generation, secure storage, rotation, handling already-shipped verifiers after rotation — none of this was implemented or tested.
- A dedicated "malformed payload" test (missing fields entirely, wrong types) was not added as its own case; the structural checks are exercised incidentally by other tests but a explicit fuzz-style malformed-input test would strengthen this further in Milestone 1.
- No revocation-list or grace-period behavior was modeled — revocation here is simply "key removed from the trust store," which is sufficient for this consolidation but leaves open whether a real deployment needs a more nuanced revocation-with-grace-period model.

## Accepted / rejected approach

**Accepted**: canonical-bytes signing + strict duplicate-key-rejecting parsing + existence-based durable replay ledger + a single fail-closed policy chain with no default-permit branch, as the shape for Milestone 1's real implementation. **Rejected**: any framing of this mechanism as "authentication" under the PRD's currently-described deployment shape (verification key beside the bundle) — per §3, that shape only supports the honest "integrity/corruption detection" claim, and PRD language should be updated accordingly if it currently implies more.

## Security implications

- The existence-based (not content-based) replay ledger is the single most safety-relevant design choice in this investigation: it means ledger corruption fails toward blocking replay, not permitting it — verified directly (test 9b), not assumed.
- The structural separation between `verify_signature` (crypto only) and `verify_intent` (crypto + policy) means a future caller cannot accidentally treat "signature checks out" as "safe to execute" without also passing through every fail-closed policy branch — this is enforced by the API shape, not just by convention.
- §3's distinction is the record's central finding and should directly update the PRD: **"signed setup-intent bundle" currently means integrity/corruption detection, not authentication, under the deployment shape described so far** — the PRD's §5.6 language should be revised to state this explicitly rather than let "signed" imply a stronger guarantee than the current key-placement plan actually provides.

## Tests added

`experiments/m0-inv9/setup_intent.py` (the prototype module) and `experiments/m0-inv9/test_setup_intent.py` (16/16 passing) — fully synthetic, no privilege, runnable in any environment with `cryptography` installed. These are strong candidates to port into `baseline/lib/` and `tests/unit/drive_setup_tests/` once Milestone 1 begins, per the PRD's own test-plan pattern (same as Investigation 7's module).

## Whether Milestone 1 is unblocked

Milestone 0's nine investigations are now complete. Real implementation work (Milestone 1) can begin, but per explicit instruction this investigation does not start it, does not implement production key provisioning, and does not touch Investigation 8's still-open physical-device questions — those remain explicitly deferred to Milestone 3 real-hardware validation, not reopened or reframed as solved by anything in this record.
