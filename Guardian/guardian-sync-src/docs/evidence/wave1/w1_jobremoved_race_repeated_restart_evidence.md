# Wave 1 JobRemoved race repair — real VM repeated-restart evidence

Command:
```
sudo target/debug/deps/guardian_helper-8a788ef310cd2e85 \
  repeated_real_restarts_are_all_correlated --ignored --nocapture --test-threads=1
```

Test: crates/guardian-helper/src/restart_capability.rs ::
restart_capability::tests::repeated_real_restarts_are_all_correlated_and_never_ambiguous

Result: 1 passed; 0 failed; finished in 0.15s (5 real RestartUnit calls against
the real cups.service on guardian-g9, each with a distinct idempotency key).

Every iteration:
- SystemdRestartAdapter::apply armed the JobRemoved subscription (synchronous
  AddMatch reply received) BEFORE RestartUnit was sent.
- RestartUnit returned confirmed_success.
- observe() reported postcondition_met (never ambiguous) -- proving each
  real JobRemoved signal was correlated to the correct job path, even
  though (per the journal capture) all 5 restarts completed within the same
  wall-clock second.
- The real unit's InvocationID changed exactly once per iteration (read via
  a real LoadUnit + Properties.GetAll call), proving each iteration
  triggered exactly one real restart -- no unnecessary second restart was
  ever triggered by a misclassified observation.

Real systemd journal for the run (see w1_race_repeat_cups_journal.txt in
this same directory for the full capture):

```
Sep 05 11:03:11 guardian-g9 systemd[1]: Stopping cups.service - CUPS Scheduler...
Sep 05 11:03:11 guardian-g9 systemd[1]: cups.service: Deactivated successfully.
Sep 05 11:03:11 guardian-g9 systemd[1]: Stopped cups.service - CUPS Scheduler.
Sep 05 11:03:11 guardian-g9 systemd[1]: Starting cups.service - CUPS Scheduler...
Sep 05 11:03:11 guardian-g9 systemd[1]: Started cups.service - CUPS Scheduler.
[... x5 total restart cycles, all within the same second ...]
```

This is exactly the fast-job timing the confirmed race depends on: five
restart cycles completing within roughly 150ms total (an average of ~30ms
per full stop/deactivate/start/started cycle) is well within the range
where the pre-repair implementation (subscribing only inside the later
Observe step) could plausibly miss JobRemoved. Every iteration here was
correctly correlated by the repaired pre-armed-subscription ordering.

## Companion real-VM regression checks (Wave 1 repair item 11)

Run the same session, same VM, same real system bus/authority:

- `restart_unit_apply_is_idempotent_for_the_same_key_against_real_systemd`
  (W1-REC-009, unchanged pre-existing real-VM test) -- re-run and passed
  under `sudo`, confirming the pre-repair idempotency guarantee is intact
  after this change.
- Scenario F (`no_matching_signal_is_bounded_and_reports_ambiguous`, private
  bus, not real systemd) -- re-run with `--ignored`, passed in 20.01s
  (bounded by `JOB_WAIT_TIMEOUT`), reporting `ambiguous` and exactly one
  `RestartUnit` call -- no infinite wait introduced by the repair.
- Full `cargo fmt --check && cargo clippy --workspace --all-targets
  --all-features -- -D warnings && cargo test --workspace` on this VM
  (which has `libadwaita-1-dev`, unlike the host workstation): all green,
  347 passed, 0 failed, 2 ignored (up from the pre-repair candidate's
  ~334 passed, 0 failed, 1 ignored).
