# W1-REC-009 — repair-pass evidence closure

**Status before this repair pass**: implemented (idempotency-keyed
`applied_key`/`rolled_back_key` in-memory markers in
`SystemdRestartAdapter`, mirroring `CounterAdapter`'s precedent), "not
separately unit-tested in isolation this pass (covered implicitly by the
`SafeToResume` resume path in W1-VM-005's own evidence, which did not
double-issue `RestartUnit` beyond the one resumed attempt)".

## What was missing

The only prior evidence for this guard was indirect: one resumed-Apply
scenario that happened not to double-issue `RestartUnit`. There was no
direct, isolated proof that `SystemdRestartAdapter::apply`'s own
`applied_key` check — independent of the surrounding G4 engine's own
retry gate — genuinely prevents a second real `RestartUnit` call for a
repeated `apply()` invocation with the same idempotency key.

## What was added

`crates/guardian-helper/src/restart_capability.rs`'s test module gained
`restart_unit_apply_is_idempotent_for_the_same_key_against_real_systemd`,
marked `#[ignore]` (it requires a real system bus and a real
`cups.service`, so it cannot run in the sandboxed dev container's
`cargo test --workspace` and is excluded from that run by design, exactly
like this project's other real-bus-only tests). It:

1. Reads `cups.service`'s real `InvocationID` (`before`).
2. Calls `SystemdRestartAdapter::apply` directly, once, with a fixed
   `ActionRequest` idempotency key.
3. Re-reads `InvocationID` (`after_first`) and asserts it **changed** —
   proving a real restart genuinely happened.
4. Calls `apply` again with the **same** `ActionRequest` key.
5. Re-reads `InvocationID` (`after_second`) and asserts it is **identical**
   to `after_first` — proving the second call was a genuine no-op, not a
   second `RestartUnit`.

This is real, deterministic, VM-only evidence of the adapter's own
in-memory guard, isolated from the surrounding G4 engine's independent
retry gate (`engine::apply`'s own `ConfirmedSuccess -> return Ok(())`
short-circuit, which this test bypasses entirely by calling
`SystemdRestartAdapter::apply` directly).

## Real VM run (`guardian-g9`)

```
$ sudo /home/ubuntu/guardian/target/debug/deps/guardian_helper-41e6b8752f6202e1 \
    --ignored restart_unit_apply_is_idempotent_for_the_same_key_against_real_systemd --nocapture

running 1 test
test restart_capability::tests::restart_unit_apply_is_idempotent_for_the_same_key_against_real_systemd ... ok

test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 29 filtered out; finished in 3.01s
```

Corroborating, independently observed `cups.service` journal for the same
window (`w1_rec_009_cups_journal.txt`) — exactly one stop/start cycle, not
two, despite two `apply()` calls:

```
Sep 04 22:20:33 guardian-g9 systemd[1]: Stopping cups.service - CUPS Scheduler...
Sep 04 22:20:34 guardian-g9 systemd[1]: cups.service: Deactivated successfully.
Sep 04 22:20:34 guardian-g9 systemd[1]: Stopped cups.service - CUPS Scheduler.
Sep 04 22:20:34 guardian-g9 systemd[1]: Starting cups.service - CUPS Scheduler...
Sep 04 22:20:34 guardian-g9 systemd[1]: Started cups.service - CUPS Scheduler.
```

Run as `root` (rather than through the mediated D-Bus path) specifically
to isolate the adapter's own idempotency guard from authorization/engine
concerns already covered elsewhere — this test exercises
`MutableCapabilityAdapter::apply` directly, not
`RestartCapability`/`run_restart_capability`.

## Disposition

W1-REC-009 is now closed with real, isolated, direct VM evidence. No code
change to `SystemdRestartAdapter` was required — the existing
`applied_key` guard behaved exactly as designed; this closes the evidence
gap, not a defect.
