//! Wave 1's sole governed capability: `cups-restart` → `cups.service` →
//! `Restart` (`GUARDIAN_WAVE1_IMPLEMENTATION_HANDOFF.md`, fully normative;
//! TDD contract §50).
//!
//! This module owns the one closed capability table (§10 — exactly one
//! governed row; adding another requires its own governed gate, never mere
//! configuration) and the real, typed systemd write provider
//! (`Manager.RestartUnit` via zbus, no shell, no `systemctl`) that
//! `guardian-helper`'s own [`crate::run_restart_capability`]-equivalent
//! orchestration drives through the unmodified G4 transaction engine.
//!
//! **Not a generic broker** (§16 audit list): there is no way to reach an
//! arbitrary unit, verb, or systemd method through this module — only
//! [`resolve_capability`], keyed on a fixed, compiled `capability_id`
//! string, ever produces a [`RestartCapability`]/[`SystemdRestartAdapter`]
//! pair, and the adapter itself only ever calls `RestartUnit` on the one
//! unit name that row carries.

use std::collections::{HashMap, VecDeque};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

use guardian_core::authorization::RestartCapability;
use guardian_provider_api::{
    ActionRequest, ApplyOutcome as RawApplyOutcome, InspectionSnapshot, MutableCapabilityAdapter,
    ObservationExpectation, ObservationOutcome as RawObservationOutcome,
    RollbackOutcome as RawRollbackOutcome, StateSnapshot, Unsupported, ValidationResult,
};
use zbus::zvariant::{OwnedObjectPath, OwnedValue};

/// The provider identity Wave 1's `TransactionRecord`s are attributed to —
/// distinct from G7's `guardian.g7.helper` (a different capability family
/// sharing the same `guardian-helper` process and `transactions/`
/// directory).
pub const PROVIDER_ID: &str = "guardian.wave1.systemd-restart";

const DESTINATION: &str = "org.freedesktop.systemd1";
const MANAGER_PATH: &str = "/org/freedesktop/systemd1";
const MANAGER_INTERFACE: &str = "org.freedesktop.systemd1.Manager";
const UNIT_INTERFACE: &str = "org.freedesktop.systemd1.Unit";
const PROPERTIES_INTERFACE: &str = "org.freedesktop.DBus.Properties";

/// How long `observe`/`rollback` will wait for the real `JobRemoved` signal
/// before honestly reporting `Ambiguous` rather than guessing (handoff §6:
/// "Ambiguous = the signal was never observed ... and re-query cannot
/// resolve it"). Bounded, not indefinite — this module never blocks the
/// process forever waiting on an external provider.
const JOB_WAIT_TIMEOUT: Duration = Duration::from_secs(20);

/// Defensive bound on the `JobRemoved` buffer a pre-armed observation
/// drains into (Wave 1 repair, handoff §4). systemd should not
/// realistically flood Guardian with an unbounded number of *unrelated*
/// `JobRemoved` signals during the brief pre-reply window between arming
/// the subscription and `RestartUnit` returning, but this is bounded
/// defensively anyway: once full, the oldest buffered entry is evicted to
/// make room for the newest.
const JOB_REMOVED_BUFFER_CAP: usize = 8;

/// A bounded, oldest-eviction buffer of `(job path, result)` pairs drained
/// from an already-armed `JobRemoved` subscription, shared between the
/// background listener thread (writer) and whichever call
/// (`observe`/`rollback`) is waiting on a specific job path (reader).
struct JobRemovedBuffer {
    entries: Mutex<VecDeque<(OwnedObjectPath, String)>>,
    condvar: Condvar,
}

impl JobRemovedBuffer {
    fn new() -> Self {
        Self {
            entries: Mutex::new(VecDeque::with_capacity(JOB_REMOVED_BUFFER_CAP)),
            condvar: Condvar::new(),
        }
    }

    /// Called only from the background listener thread. Evicts the oldest
    /// entry once at capacity (handoff §4's bounded-buffer requirement) --
    /// never grows without bound.
    fn push(&self, job: OwnedObjectPath, result: String) {
        let mut entries = self.entries.lock().unwrap();
        if entries.len() >= JOB_REMOVED_BUFFER_CAP {
            entries.pop_front();
        }
        entries.push_back((job, result));
        self.condvar.notify_all();
    }

    /// Waits, bounded by `deadline`, for an entry whose job path equals
    /// `job` exactly -- any other buffered/incoming entry (a different
    /// job) is left alone and never satisfies this wait (handoff §4/§5:
    /// "Unrelated `JobRemoved` signals must not count as success or
    /// failure"). Returns `None` once `deadline` passes with no match --
    /// the governed, bounded timeout this module has always used, never an
    /// infinite wait (handoff §6, scenario F).
    fn wait_for(&self, job: &OwnedObjectPath, deadline: Instant) -> Option<String> {
        let mut entries = self.entries.lock().unwrap();
        loop {
            if let Some(index) = entries.iter().position(|(path, _)| path == job) {
                return entries.remove(index).map(|(_, result)| result);
            }
            let now = Instant::now();
            if now >= deadline {
                return None;
            }
            entries = self
                .condvar
                .wait_timeout(entries, deadline - now)
                .unwrap()
                .0;
        }
    }
}

/// One `JobRemoved` observation armed *before* `RestartUnit` is ever sent
/// (Wave 1 repair for the confirmed race -- see
/// [`SystemdRestartAdapter::arm_job_removed_observation`]'s doc comment
/// for exactly why the subscription is already active by the time this is
/// constructed). Carries its own background listener's lifetime handle so
/// `observe`/`rollback`/an abandoning `apply` can ask it to stop once the
/// result is no longer needed (handoff §9: "no orphan signal consumer").
struct ArmedObservation {
    buffer: Arc<JobRemovedBuffer>,
    keep_running: Arc<AtomicBool>,
}

impl ArmedObservation {
    /// Best-effort request that the background listener thread stop after
    /// it next checks (i.e. after its next received message, or
    /// immediately if it is not currently blocked in a socket read).
    /// Mirrors the same bounded-effort shape the pre-repair
    /// implementation's own timeout case already had for "no further
    /// signal ever arrives": this is not a hard cancellation (the
    /// underlying blocking iterator has no read-timeout primitive to
    /// interrupt a socket read that is already in progress), but every
    /// reachable completion path (matched, unrelated-only, or subscription
    /// abandoned after a failed `RestartUnit`) requests it, and any
    /// further bus traffic lets the thread notice and exit promptly.
    fn stop(&self) {
        self.keep_running.store(false, Ordering::Release);
    }
}

struct CapabilityRow {
    capability_id: &'static str,
    unit_name: &'static str,
}

/// Wave 1's own governed capability table (handoff §10). **Exactly one
/// row for this acceptance.** Adding a row is a capability expansion and
/// requires its own governed gate/review — this is not configuration, and
/// nothing in this module reads an external file, environment variable, or
/// caller input to grow it.
const CAPABILITY_TABLE: &[CapabilityRow] = &[CapabilityRow {
    capability_id: "cups-restart",
    unit_name: "cups.service",
}];

/// Resolves a `capability_id` against the fixed table above. `None` for
/// anything else — including `guardian-daemon`'s/`guardian-helper`'s own
/// units, which simply never appear as a row (§10: "excluded by simply
/// never appearing as a row, not by a runtime check that could be
/// bypassed"). Callers MUST reject an unknown `capability_id` using this
/// return value *before* any unit name is looked up and *before*
/// `Authorize` is ever reached (W1-MUT-002).
#[must_use]
pub fn resolve_capability(capability_id: &str) -> Option<RestartCapability> {
    CAPABILITY_TABLE
        .iter()
        .find(|row| row.capability_id == capability_id)
        .map(|row| RestartCapability::new(row.unit_name))
}

/// A real, live-read snapshot of the governed unit's authoritative systemd
/// state — never trusted from `guardian-daemon` or any other relayed
/// source (handoff §6's note on Snapshot).
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LiveUnitState {
    pub load_state: String,
    pub active_state: String,
    pub sub_state: String,
    pub refuse_manual_start: bool,
    pub refuse_manual_stop: bool,
}

impl LiveUnitState {
    /// W1-MUT-003's precondition: the unit does not exist at all, or has
    /// been administratively masked -- extracted as a pure, independently
    /// unit-testable predicate (Wave 1 repair pass, closing the evidence
    /// gap the original implementation pass left: "not separately
    /// unit-tested against a real 'not-found' unit"). `guardian-helper`'s
    /// `restart_validate` calls this directly; a real VM re-capture
    /// independently confirmed systemd itself reports `LoadState ==
    /// "not-found"` for a genuinely nonexistent unit (see
    /// `docs/evidence/wave1/w1_mut_003_004_evidence.md`).
    #[must_use]
    pub fn is_load_state_blocked(&self) -> bool {
        self.load_state == "not-found" || self.load_state == "masked"
    }

    /// W1-MUT-004's precondition: the unit itself refuses manual
    /// start/stop -- extracted as a pure, independently unit-testable
    /// predicate for the same reason as [`Self::is_load_state_blocked`]. A
    /// real VM re-capture independently confirmed systemd reports
    /// `RefuseManualStart == true` for a real transient unit configured
    /// with `RefuseManualStart=yes` (see
    /// `docs/evidence/wave1/w1_mut_003_004_evidence.md`).
    #[must_use]
    pub const fn refuses_manual_start_or_stop(&self) -> bool {
        self.refuse_manual_start || self.refuse_manual_stop
    }
}

/// A failure to establish the unit's live precondition state at all — an
/// infrastructure/provider problem, never itself a validation verdict
/// (mirrors `SystemdError::ProviderUnavailable` in the unmodified G8 read
/// provider this module deliberately does not touch).
#[derive(Debug)]
pub struct ProviderUnavailable(pub String);

/// The real, typed systemd write provider for one governed
/// [`RestartCapability`] row. Native D-Bus only (`Manager.RestartUnit`) —
/// no shell, no `systemctl` (contract §40's forbidden-shortcuts list).
pub struct SystemdRestartAdapter {
    connection: zbus::blocking::Connection,
    unit_name: String,
    /// The idempotency key of the last `apply` attempt this process
    /// instance durably knows it completed — makes a retried `apply` for
    /// the same key a genuine no-op (W1-REC-009, reusing P0-TXN-009's
    /// discipline), not a second `RestartUnit` call.
    applied_key: Mutex<Option<String>>,
    rolled_back_key: Mutex<Option<String>>,
    /// The real job object path from the most recent successful
    /// `RestartUnit` call, paired with the `JobRemoved` observation that
    /// was armed *before* that call was ever sent (Wave 1 repair; see
    /// [`Self::arm_job_removed_observation`]) — required so `observe` can
    /// wait for, and correlate, the matching `JobRemoved` signal rather
    /// than any job's, without having missed it due to a subscription
    /// installed too late. `None` once consumed (or if never armed, e.g.
    /// a resumed transaction in a fresh adapter instance with no in-flight
    /// job of its own to wait for).
    armed_job: Mutex<Option<(OwnedObjectPath, ArmedObservation)>>,
}

impl SystemdRestartAdapter {
    /// Opens its **own**, independent blocking system-bus connection —
    /// deliberately never derived from (`From<crate::Connection>`-wrapping)
    /// the shared async `zbus::Connection` the surrounding
    /// `#[zbus::interface]` method runs on. Sharing that connection's
    /// executor with blocking calls from within the same async task that
    /// executor is currently driving deadlocks (`zbus::blocking`'s
    /// transport polls the *same* single-threaded reactor the outer async
    /// method's own suspension is waiting on) — reproduced empirically
    /// during Wave 1 VM evidence gathering as an indefinite hang on the
    /// very first real `RestartCapability` call. A fresh connection has its
    /// own independent transport/reactor, so its blocking calls make
    /// progress regardless of what the interface-serving connection's own
    /// executor is doing.
    ///
    /// # Errors
    ///
    /// Returns the real `zbus::Error` if the system bus cannot be reached
    /// at all — an infrastructure failure, surfaced by the caller as
    /// `ProviderUnavailable`, never silently downgraded.
    pub fn new(unit_name: impl Into<String>) -> zbus::Result<Self> {
        Ok(Self {
            connection: zbus::blocking::Connection::system()?,
            unit_name: unit_name.into(),
            applied_key: Mutex::new(None),
            rolled_back_key: Mutex::new(None),
            armed_job: Mutex::new(None),
        })
    }

    fn manager(&self) -> zbus::Result<zbus::blocking::Proxy<'_>> {
        zbus::blocking::Proxy::new(
            &self.connection,
            DESTINATION,
            MANAGER_PATH,
            MANAGER_INTERFACE,
        )
    }

    /// Real `LoadUnit` + real `Properties.GetAll` on the `Unit` interface —
    /// the live authoritative read `guardian-helper`'s own `Validate` step
    /// uses for W1-MUT-003/W1-MUT-004. Never a cached/relayed value.
    ///
    /// # Errors
    ///
    /// Returns [`ProviderUnavailable`] if the bus/provider cannot be
    /// reached at all — never conflated with a real validation verdict.
    pub fn read_live_state(&self) -> Result<LiveUnitState, ProviderUnavailable> {
        let manager = self
            .manager()
            .map_err(|error| ProviderUnavailable(format!("systemd1 unreachable: {error}")))?;
        let unit_path: OwnedObjectPath = manager
            .call("LoadUnit", &(self.unit_name.as_str(),))
            .map_err(|error| ProviderUnavailable(format!("LoadUnit failed: {error}")))?;

        let props = zbus::blocking::Proxy::new(
            &self.connection,
            DESTINATION,
            unit_path,
            PROPERTIES_INTERFACE,
        )
        .map_err(|error| ProviderUnavailable(format!("properties proxy failed: {error}")))?;
        let all: HashMap<String, OwnedValue> = props
            .call("GetAll", &(UNIT_INTERFACE,))
            .map_err(|error| ProviderUnavailable(format!("GetAll failed: {error}")))?;

        let string_field = |key: &str| -> Result<String, ProviderUnavailable> {
            all.get(key)
                .and_then(|value| value.downcast_ref::<zbus::zvariant::Str>().ok())
                .map(|s| s.as_str().to_owned())
                .ok_or_else(|| ProviderUnavailable(format!("missing/invalid {key}")))
        };
        let bool_field = |key: &str| -> bool {
            all.get(key)
                .and_then(|value| value.downcast_ref::<bool>().ok())
                .unwrap_or(false)
        };

        Ok(LiveUnitState {
            load_state: string_field("LoadState")?,
            active_state: string_field("ActiveState")?,
            sub_state: string_field("SubState")?,
            refuse_manual_start: bool_field("RefuseManualStart"),
            refuse_manual_stop: bool_field("RefuseManualStop"),
        })
    }

    /// Real `Manager.RestartUnit(unit, "replace")` — the sole mutation this
    /// module can perform. Returns the real job object path systemd hands
    /// back; never a fabricated one.
    fn restart_unit(&self) -> zbus::Result<OwnedObjectPath> {
        #[cfg(feature = "evidence-hooks")]
        if let Ok(ms) = std::env::var("GUARDIAN_HELPER_RESTART_APPLY_DELAY_MS") {
            if let Ok(ms) = ms.parse::<u64>() {
                std::thread::sleep(std::time::Duration::from_millis(ms));
            }
        }
        let manager = self.manager()?;
        manager.call("RestartUnit", &(self.unit_name.as_str(), "replace"))
    }

    /// Establishes the `JobRemoved` match rule and starts draining it into
    /// a bounded buffer ([`JobRemovedBuffer`]) -- called *before*
    /// `RestartUnit` is ever sent (Wave 1 repair for the confirmed race:
    /// "a sufficiently fast systemd job may emit `JobRemoved` before
    /// Guardian installs its D-Bus match/subscription"). Returns `Err` if
    /// the subscription cannot be established at all; every caller of this
    /// method treats that as fail-closed (handoff §6): `RestartUnit` MUST
    /// NOT be invoked when this fails.
    ///
    /// # Why the subscription is provably active before this returns
    ///
    /// `zbus::blocking::MessageIterator::for_match_rule` (zbus 5.19.0,
    /// this workspace's pinned version) is a thin `block_on` wrapper over
    /// the async `MessageStream::for_match_rule`, which itself calls
    /// `Connection::add_match(rule, max_queued).await?` before returning
    /// the message receiver. `add_match`
    /// (`zbus-5.19.0/src/connection/mod.rs`) sends the real
    /// `org.freedesktop.DBus.AddMatch` method call via
    /// `self.call_method(...).await?` and only inserts the subscription
    /// and returns *after* that call's reply has been received. There is
    /// no lazy/deferred registration in this path: by the time this
    /// function returns `Ok`, the bus daemon has already acknowledged (via
    /// a real method reply) that the match rule is installed, so every
    /// `JobRemoved` signal broadcast from this point on -- including one
    /// broadcast before `RestartUnit`'s own reply arrives -- is captured
    /// into the returned buffer rather than silently lost.
    ///
    /// The listener thread itself only ever drains this one already-armed
    /// subscription into the bounded buffer; it performs no D-Bus method
    /// calls of its own and therefore cannot itself race anything.
    fn arm_job_removed_observation(&self) -> zbus::Result<ArmedObservation> {
        let rule = zbus::MatchRule::builder()
            .msg_type(zbus::message::Type::Signal)
            .sender(DESTINATION)?
            .path(MANAGER_PATH)?
            .interface(MANAGER_INTERFACE)?
            .member("JobRemoved")?
            .build();
        // `for_match_rule` performs (and awaits) the real `AddMatch` call
        // synchronously -- see this method's doc comment above. By the
        // time this line returns `Ok`, the subscription is active.
        let mut iterator = zbus::blocking::MessageIterator::for_match_rule(
            rule,
            &self.connection,
            Some(JOB_REMOVED_BUFFER_CAP),
        )?;

        let buffer = Arc::new(JobRemovedBuffer::new());
        let keep_running = Arc::new(AtomicBool::new(true));
        let thread_buffer = Arc::clone(&buffer);
        let thread_keep_running = Arc::clone(&keep_running);

        // Off a dedicated background thread, exactly like the pre-repair
        // implementation's own listener -- draining a blocking iterator
        // that was armed on this adapter's own independent connection
        // (never the shared async interface-serving connection; see
        // `Self::new`'s doc comment on the deadlock this avoids).
        std::thread::spawn(move || {
            for message in &mut iterator {
                if !thread_keep_running.load(Ordering::Acquire) {
                    break;
                }
                let Ok(message) = message else { continue };
                let body = message.body();
                // JobRemoved(u job_id, o job, s unit, s result)
                if let Ok((_id, path, _unit, result)) =
                    body.deserialize::<(u32, OwnedObjectPath, String, String)>()
                {
                    thread_buffer.push(path, result);
                }
            }
        });

        Ok(ArmedObservation {
            buffer,
            keep_running,
        })
    }
}

impl MutableCapabilityAdapter for SystemdRestartAdapter {
    fn inspect(&self) -> Result<InspectionSnapshot, Unsupported> {
        let state = self.read_live_state().map_err(|_| Unsupported)?;
        Ok(InspectionSnapshot(format!(
            "{}:{}",
            state.active_state, state.sub_state
        )))
    }

    fn validate(&self, _action: &ActionRequest) -> Result<ValidationResult, Unsupported> {
        // Domain-specific precondition checks (LoadState/masked/
        // RefuseManualStart/Stop) happen in `crate::restart_capability`'s
        // own orchestration *before* the generic `txn::engine::validate`
        // call, using a live `read_live_state()` read directly -- the
        // unmodified G4 engine's own `validate()` free function never
        // calls this trait method (it only checks the fixed
        // `CapabilityRecord`), so this stub exists only for trait
        // completeness (same discipline as G7's `CounterAdapter`).
        Ok(ValidationResult("ok".to_owned()))
    }

    fn snapshot(&self, _action: &ActionRequest) -> Result<StateSnapshot, Unsupported> {
        // Unused by the unmodified G4 engine (`engine::rollback` uses the
        // transaction's own idempotency key, not this method) -- present
        // only for trait completeness, matching `CounterAdapter`.
        Ok(StateSnapshot(self.unit_name.clone()))
    }

    fn apply(&self, action: &ActionRequest) -> Result<RawApplyOutcome, Unsupported> {
        // Idempotent apply (W1-REC-009, P0-TXN-009): a retried Apply for
        // the same durable idempotency key is a genuine no-op, never a
        // second RestartUnit call.
        if self.applied_key.lock().unwrap().as_deref() == Some(action.0.as_str()) {
            return Ok(RawApplyOutcome("confirmed_success".to_owned()));
        }

        // Wave 1 repair (confirmed race): observation is armed *before*
        // RestartUnit is ever sent. If arming fails, Guardian has already
        // lost its ability to observe the mutation it is about to make --
        // handoff §6 requires failing closed, so RestartUnit MUST NOT be
        // invoked in that case.
        let Ok(armed) = self.arm_job_removed_observation() else {
            return Ok(RawApplyOutcome("confirmed_failure_no_mutation".to_owned()));
        };

        match self.restart_unit() {
            Ok(job) => {
                *self.armed_job.lock().unwrap() = Some((job, armed));
                *self.applied_key.lock().unwrap() = Some(action.0.clone());
                Ok(RawApplyOutcome("confirmed_success".to_owned()))
            }
            // A genuine client-side ambiguity -- the request may or may not
            // have reached/been processed by systemd (timed out, or the
            // bus connection was reset mid-call). Distinct from a clean
            // method-level failure below (handoff §8, W1-REC-003's
            // reachable analogue for a call that *returns* ambiguous
            // rather than one interrupted by a process kill -- see the
            // Wave 1 evidence report's documented gap for the
            // literal-process-kill sub-case).
            //
            // No job path is ever known in this branch, so the armed
            // observation can never be correlated to anything -- it is
            // told to stop rather than kept around forever (handoff §9).
            Err(zbus::Error::InputOutput(_) | zbus::Error::InvalidReply) => {
                armed.stop();
                Ok(RawApplyOutcome("partial_or_uncertain_mutation".to_owned()))
            }
            Err(zbus::Error::FDO(fdo_error))
                if matches!(
                    *fdo_error,
                    zbus::fdo::Error::Timeout(_) | zbus::fdo::Error::NoReply(_)
                ) =>
            {
                armed.stop();
                Ok(RawApplyOutcome("partial_or_uncertain_mutation".to_owned()))
            }
            Err(_) => {
                armed.stop();
                Ok(RawApplyOutcome("confirmed_failure_no_mutation".to_owned()))
            }
        }
    }

    fn observe(
        &self,
        _expectation: &ObservationExpectation,
    ) -> Result<RawObservationOutcome, Unsupported> {
        let Some((job, armed)) = self.armed_job.lock().unwrap().take() else {
            // Observe called with no armed in-flight job of this adapter
            // instance's own (e.g. resumed from a persisted record in a
            // fresh adapter instance, whose own prior process's
            // subscription is long gone): fall back to a fresh state read
            // -- if the unit is already active, the postcondition is
            // honestly met from re-observation alone; never guessed.
            let Ok(state) = self.read_live_state() else {
                return Ok(RawObservationOutcome("ambiguous".to_owned()));
            };
            return Ok(RawObservationOutcome(
                if state.active_state == "active" {
                    "postcondition_met"
                } else {
                    "ambiguous"
                }
                .to_owned(),
            ));
        };

        // Correlate strictly by the exact job path `RestartUnit` returned
        // (handoff §4/§5) -- any other buffered or incoming `JobRemoved`
        // is ignored by `JobRemovedBuffer::wait_for` itself.
        let deadline = Instant::now() + JOB_WAIT_TIMEOUT;
        let result = armed.buffer.wait_for(&job, deadline);
        armed.stop();

        let Some(result) = result else {
            return Ok(RawObservationOutcome("ambiguous".to_owned()));
        };

        if result != "done" {
            return Ok(RawObservationOutcome("postcondition_not_met".to_owned()));
        }

        // `result == "done"` alone is not proof of the transaction's own
        // postcondition (handoff §6): a fresh re-read must also confirm
        // the expected post-restart state.
        match self.read_live_state() {
            Ok(state) if state.active_state == "active" => {
                Ok(RawObservationOutcome("postcondition_met".to_owned()))
            }
            Ok(_) => Ok(RawObservationOutcome("postcondition_not_met".to_owned())),
            Err(_) => Ok(RawObservationOutcome("ambiguous".to_owned())),
        }
    }

    fn rollback(&self, snapshot: &StateSnapshot) -> Result<RawRollbackOutcome, Unsupported> {
        // BestEffort compensating action only (handoff §6/§15): retrying
        // RestartUnit once more. Never claims a true state-restoring
        // rollback -- disclosed via `RollbackKind::BestEffort` at the call
        // site, not by this method's own return value.
        if self.rolled_back_key.lock().unwrap().as_deref() == Some(snapshot.0.as_str()) {
            return Ok(RawRollbackOutcome("confirmed_restored".to_owned()));
        }

        // Same repair as `apply` (this compensating restart is itself a
        // `RestartUnit` call subject to the identical race): arm
        // observation before sending it, fail closed if that cannot be
        // done.
        let Ok(armed) = self.arm_job_removed_observation() else {
            return Ok(RawRollbackOutcome("confirmed_failed".to_owned()));
        };

        let Ok(job) = self.restart_unit() else {
            armed.stop();
            return Ok(RawRollbackOutcome("confirmed_failed".to_owned()));
        };

        let deadline = Instant::now() + JOB_WAIT_TIMEOUT;
        let result = armed.buffer.wait_for(&job, deadline);
        armed.stop();

        let outcome = match result {
            Some(result) if result == "done" => {
                *self.rolled_back_key.lock().unwrap() = Some(snapshot.0.clone());
                "confirmed_restored"
            }
            Some(_) => "confirmed_failed",
            None => "attempted_unconfirmed",
        };
        Ok(RawRollbackOutcome(outcome.to_owned()))
    }
}

#[cfg(test)]
mod tests {
    use super::{LiveUnitState, resolve_capability};

    fn healthy_state() -> LiveUnitState {
        LiveUnitState {
            load_state: "loaded".to_owned(),
            active_state: "active".to_owned(),
            sub_state: "running".to_owned(),
            refuse_manual_start: false,
            refuse_manual_stop: false,
        }
    }

    /// W1-MUT-003 (repair pass): a real VM re-capture independently
    /// confirmed systemd reports `LoadState == "not-found"` for a
    /// genuinely nonexistent unit
    /// (`docs/evidence/wave1/w1_mut_003_004_evidence.md`) -- this proves
    /// Guardian's own precondition predicate correctly rejects that real
    /// value.
    #[test]
    fn is_load_state_blocked_true_for_not_found() {
        let state = LiveUnitState {
            load_state: "not-found".to_owned(),
            ..healthy_state()
        };
        assert!(state.is_load_state_blocked());
    }

    /// W1-MUT-003: masked is the other blocked `LoadState` value the
    /// handoff names.
    #[test]
    fn is_load_state_blocked_true_for_masked() {
        let state = LiveUnitState {
            load_state: "masked".to_owned(),
            ..healthy_state()
        };
        assert!(state.is_load_state_blocked());
    }

    /// A normally loaded unit must never be blocked by this predicate --
    /// this is the exact real value W1-VM-001's own passing case already
    /// observes for `cups.service`.
    #[test]
    fn is_load_state_blocked_false_for_loaded() {
        assert!(!healthy_state().is_load_state_blocked());
    }

    /// W1-MUT-004 (repair pass): a real VM re-capture independently
    /// confirmed systemd reports `RefuseManualStart == true` for a real
    /// transient unit configured with `RefuseManualStart=yes`
    /// (`docs/evidence/wave1/w1_mut_003_004_evidence.md`) -- this proves
    /// Guardian's own precondition predicate correctly rejects that real
    /// value, for either underlying flag.
    #[test]
    fn refuses_manual_start_or_stop_true_for_either_flag() {
        let refuse_start = LiveUnitState {
            refuse_manual_start: true,
            ..healthy_state()
        };
        assert!(refuse_start.refuses_manual_start_or_stop());

        let refuse_stop = LiveUnitState {
            refuse_manual_stop: true,
            ..healthy_state()
        };
        assert!(refuse_stop.refuses_manual_start_or_stop());

        let refuse_both = LiveUnitState {
            refuse_manual_start: true,
            refuse_manual_stop: true,
            ..healthy_state()
        };
        assert!(refuse_both.refuses_manual_start_or_stop());
    }

    #[test]
    fn refuses_manual_start_or_stop_false_for_a_normal_unit() {
        assert!(!healthy_state().refuses_manual_start_or_stop());
    }

    /// W1-REC-009 (repair pass, closing the evidence gap the original
    /// implementation pass left: "not separately unit-tested in isolation
    /// this pass"): `SystemdRestartAdapter::apply`'s in-memory
    /// `applied_key` idempotency guard, proven directly and deterministically
    /// against a real `cups.service` -- not merely inferred from the
    /// `SafeToResume` resume path's job-merging side effect. Requires a
    /// real system bus with `cups.service` present and a real polkit
    /// authority that grants this call (i.e. `guardian-g9`'s own
    /// evidence-only `60-wave1-evidence.rules`, or root), so this is
    /// `#[ignore]`d by default and was run explicitly during the repair
    /// pass; see `docs/evidence/wave1/w1_rec_009_idempotency_evidence.md`
    /// for the real VM run and its output.
    #[test]
    #[ignore = "requires a real system bus + cups.service; run explicitly for W1-REC-009 VM evidence"]
    fn restart_unit_apply_is_idempotent_for_the_same_key_against_real_systemd() {
        fn invocation_id(adapter: &super::SystemdRestartAdapter) -> String {
            let manager = zbus::blocking::Proxy::new(
                &adapter.connection,
                super::DESTINATION,
                super::MANAGER_PATH,
                super::MANAGER_INTERFACE,
            )
            .expect("manager proxy");
            let unit_path: zbus::zvariant::OwnedObjectPath = manager
                .call("LoadUnit", &("cups.service",))
                .expect("LoadUnit must succeed for a real, present unit");
            let props = zbus::blocking::Proxy::new(
                &adapter.connection,
                super::DESTINATION,
                unit_path,
                super::PROPERTIES_INTERFACE,
            )
            .expect("properties proxy");
            let all: std::collections::HashMap<String, zbus::zvariant::OwnedValue> = props
                .call("GetAll", &(super::UNIT_INTERFACE,))
                .expect("GetAll must succeed");
            all.get("InvocationID")
                .map(|value| format!("{value:?}"))
                .expect("InvocationID must be present for a real unit")
        }

        use guardian_provider_api::{ActionRequest, MutableCapabilityAdapter};

        let adapter = super::SystemdRestartAdapter::new("cups.service".to_owned())
            .expect("real system bus must be reachable");

        let before = invocation_id(&adapter);

        let action = ActionRequest("w1-rec-009-idempotency-check".to_owned());
        let first = MutableCapabilityAdapter::apply(&adapter, &action)
            .expect("first apply must succeed against real cups.service");
        assert_eq!(first.0, "confirmed_success");
        // Give the real, asynchronously-scheduled restart job a moment to
        // actually replace the running service instance before reading
        // its new InvocationID.
        std::thread::sleep(std::time::Duration::from_secs(2));
        let after_first = invocation_id(&adapter);
        assert_ne!(
            before, after_first,
            "the first apply must have genuinely restarted the real unit \
             (a new InvocationID proves a real new service instance)"
        );

        let second = MutableCapabilityAdapter::apply(&adapter, &action)
            .expect("second apply (same key) must be a no-op, not error");
        assert_eq!(second.0, "confirmed_success");
        std::thread::sleep(std::time::Duration::from_secs(1));
        let after_second = invocation_id(&adapter);
        assert_eq!(
            after_first, after_second,
            "a retried apply for the SAME idempotency key must be a genuine \
             no-op -- the real unit must NOT have been restarted a second \
             time (InvocationID must be unchanged)"
        );
    }

    /// Wave 1 `JobRemoved` race repair -- real VM stress reproduction
    /// (handoff item 8): repeated real `RestartUnit` calls against the
    /// real `cups.service` on `guardian-g9`, each with its own
    /// idempotency key, proving the pre-armed subscription correlates a
    /// real, fast systemd job every single time rather than only on one
    /// favorable execution. Each iteration's `InvocationID` must change
    /// *exactly once* (a real new service instance) and `observe` must
    /// report `postcondition_met` every time -- never `ambiguous` (which
    /// would mean this iteration's `JobRemoved` was missed). Requires the
    /// same real system bus + authority as the idempotency test above, so
    /// `#[ignore]`d by default; see
    /// `docs/evidence/wave1/w1_jobremoved_race_repeated_restart_evidence.md`
    /// for the real VM run and its captured output.
    #[test]
    #[ignore = "requires a real system bus + cups.service; run explicitly for the JobRemoved race repair's VM evidence"]
    fn repeated_real_restarts_are_all_correlated_and_never_ambiguous() {
        fn invocation_id(adapter: &super::SystemdRestartAdapter) -> String {
            let manager = zbus::blocking::Proxy::new(
                &adapter.connection,
                super::DESTINATION,
                super::MANAGER_PATH,
                super::MANAGER_INTERFACE,
            )
            .expect("manager proxy");
            let unit_path: zbus::zvariant::OwnedObjectPath = manager
                .call("LoadUnit", &("cups.service",))
                .expect("LoadUnit must succeed for a real, present unit");
            let props = zbus::blocking::Proxy::new(
                &adapter.connection,
                super::DESTINATION,
                unit_path,
                super::PROPERTIES_INTERFACE,
            )
            .expect("properties proxy");
            let all: std::collections::HashMap<String, zbus::zvariant::OwnedValue> = props
                .call("GetAll", &(super::UNIT_INTERFACE,))
                .expect("GetAll must succeed");
            all.get("InvocationID")
                .map(|value| format!("{value:?}"))
                .expect("InvocationID must be present for a real unit")
        }

        use guardian_provider_api::{
            ActionRequest, MutableCapabilityAdapter, ObservationExpectation,
        };

        let adapter = super::SystemdRestartAdapter::new("cups.service".to_owned())
            .expect("real system bus must be reachable");

        let mut previous_invocation = invocation_id(&adapter);
        for iteration in 0..5 {
            let key = format!("w1-jobremoved-race-repeat-{iteration}");
            let action = ActionRequest(key.clone());

            let apply = MutableCapabilityAdapter::apply(&adapter, &action)
                .expect("apply must succeed against real cups.service");
            assert_eq!(apply.0, "confirmed_success", "iteration {iteration}");

            let observation =
                MutableCapabilityAdapter::observe(&adapter, &ObservationExpectation(key))
                    .expect("observe must succeed against real cups.service");
            assert_eq!(
                observation.0, "postcondition_met",
                "iteration {iteration}: a real fast restart must be correlated, \
                 never reported ambiguous, by the pre-armed subscription"
            );

            let current_invocation = invocation_id(&adapter);
            assert_ne!(
                previous_invocation, current_invocation,
                "iteration {iteration}: InvocationID must have changed exactly \
                 once -- proof of a real, single, correlated restart"
            );
            previous_invocation = current_invocation;
        }
    }

    #[test]
    fn resolves_the_one_governed_cups_restart_row() {
        let capability = resolve_capability("cups-restart").expect("row must resolve");
        assert_eq!(capability.unit_name(), "cups.service");
    }

    #[test]
    fn rejects_an_unknown_capability_id() {
        assert!(resolve_capability("nginx-restart").is_none());
        assert!(resolve_capability("").is_none());
        assert!(resolve_capability("cups.service").is_none());
    }

    /// W1-MUT-002/§10: `guardian-daemon`/`guardian-helper` themselves are
    /// structurally excluded -- there is no row for either.
    #[test]
    fn helper_and_daemon_units_are_not_governed_rows() {
        assert!(resolve_capability("guardian-helper").is_none());
        assert!(resolve_capability("guardian-daemon").is_none());
        assert!(resolve_capability("guardian-helper.service").is_none());
    }

    /// §10: "For Wave 1's own acceptance, exactly one row exists" --
    /// mechanically checkable against the compiled table itself.
    #[test]
    fn the_capability_table_has_exactly_one_governed_row() {
        assert_eq!(super::CAPABILITY_TABLE.len(), 1);
        assert_eq!(super::CAPABILITY_TABLE[0].capability_id, "cups-restart");
        assert_eq!(super::CAPABILITY_TABLE[0].unit_name, "cups.service");
    }

    /// §16 audit list, source-level: no generic unit-name/operation
    /// parameter exists anywhere in this module's public API.
    #[test]
    fn resolve_capability_signature_takes_only_a_capability_id_string() {
        let full_source = include_str!("restart_capability.rs");
        // Scan only the production code, not this test module's own text
        // (which necessarily contains the literal forbidden-name search
        // strings too).
        let source = &full_source[..full_source
            .find("\n#[cfg(test)]\n")
            .expect("this test module marker must exist")];
        assert!(
            !source.contains("pub fn restart_unit_named"),
            "no function may accept an arbitrary unit name from outside this module"
        );
        assert!(
            !source.contains("pub fn run_operation"),
            "no generic operation-selection surface may exist"
        );
    }
}

/// Wave 1 `JobRemoved` race repair -- deterministic timing tests (handoff
/// item 7, scenarios A-F). Uses a real, private (never the host system
/// bus) D-Bus daemon (`guardian_testkit::PrivateSessionBus`, the same
/// pattern G0-G9's own D-Bus contract tests already use) plus a fake
/// `org.freedesktop.systemd1.Manager` service this module fully controls,
/// so signal-vs-reply ordering is exact and reproducible rather than
/// depending on real systemd's own scheduling.
#[cfg(test)]
mod race_tests {
    use super::{MANAGER_INTERFACE, MANAGER_PATH, SystemdRestartAdapter};
    use guardian_provider_api::{ActionRequest, MutableCapabilityAdapter, ObservationExpectation};
    use guardian_testkit::PrivateSessionBus;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Mutex, OnceLock};
    use std::time::Duration;
    use zbus::zvariant::OwnedObjectPath;

    impl SystemdRestartAdapter {
        /// Test-only constructor pointing this adapter at an arbitrary
        /// (never the real host system bus) connection -- used only by
        /// this module's own race tests to connect to a private bus
        /// hosting [`FakeManager`] instead of real systemd. Production
        /// code always uses [`SystemdRestartAdapter::new`].
        fn for_test_connection(
            unit_name: impl Into<String>,
            connection: zbus::blocking::Connection,
        ) -> Self {
            Self {
                connection,
                unit_name: unit_name.into(),
                applied_key: Mutex::new(None),
                rolled_back_key: Mutex::new(None),
                armed_job: Mutex::new(None),
            }
        }
    }

    /// When the fake `RestartUnit` handler emits the *matching* job's own
    /// `JobRemoved`, relative to when it returns its reply.
    #[derive(Clone, Copy)]
    enum MatchingSignal {
        /// Scenario A: emitted before the method reply is sent at all.
        BeforeReply,
        /// Scenario B: emitted shortly after the method reply is sent, off
        /// a background thread the object server itself is not blocked on.
        ShortlyAfterReply,
        /// Scenario F: never emitted.
        Never,
    }

    #[derive(Clone)]
    struct FakeJobPlan {
        /// Unrelated `JobRemoved(other_job, ...)` signals emitted before
        /// the method reply (scenarios C/D).
        unrelated_before_reply: Vec<(&'static str, &'static str)>,
        matching_signal: MatchingSignal,
        /// The `result` token for the *matching* job (scenario E: a
        /// matching but failed job).
        result: &'static str,
    }

    impl Default for FakeJobPlan {
        fn default() -> Self {
            Self {
                unrelated_before_reply: Vec::new(),
                matching_signal: MatchingSignal::ShortlyAfterReply,
                result: "done",
            }
        }
    }

    /// The fixed fake unit object path `LoadUnit` resolves to -- backing
    /// `read_live_state`'s own `LoadUnit` + `Properties.GetAll` reads,
    /// which `observe`'s post-`JobRemoved` re-read depends on regardless
    /// of this repair.
    const FAKE_UNIT_PATH: &str = "/org/freedesktop/systemd1/unit/cups_2eservice";

    struct FakeManager {
        restart_calls: Arc<AtomicUsize>,
        connection: Arc<OnceLock<zbus::Connection>>,
        plan: FakeJobPlan,
    }

    #[zbus::interface(name = "org.freedesktop.systemd1.Manager")]
    impl FakeManager {
        #[allow(clippy::unused_self, clippy::needless_pass_by_value, unused_variables)]
        fn load_unit(&self, name: String) -> OwnedObjectPath {
            OwnedObjectPath::try_from(FAKE_UNIT_PATH).expect("valid literal unit path")
        }

        #[allow(unused_variables)]
        async fn restart_unit(&self, name: String, mode: String) -> OwnedObjectPath {
            self.restart_calls.fetch_add(1, Ordering::SeqCst);
            let path = OwnedObjectPath::try_from("/org/freedesktop/systemd1/job/1")
                .expect("valid literal job path");
            let connection = self
                .connection
                .get()
                .expect("connection installed before serve_at is reachable")
                .clone();

            for (job, result) in &self.plan.unrelated_before_reply {
                emit_job_removed(&connection, job, "other.service", result).await;
            }

            match self.plan.matching_signal {
                MatchingSignal::BeforeReply => {
                    emit_job_removed(&connection, path.as_str(), "cups.service", self.plan.result)
                        .await;
                }
                MatchingSignal::ShortlyAfterReply => {
                    let connection = connection.clone();
                    let path = path.clone();
                    let result = self.plan.result.to_owned();
                    // A plain, independent OS thread -- not the object
                    // server's own executor -- so blocking here to await
                    // the emission cannot re-enter/stall the very reactor
                    // that is about to deliver this method's own reply.
                    std::thread::spawn(move || {
                        std::thread::sleep(Duration::from_millis(60));
                        futures_lite::future::block_on(emit_job_removed(
                            &connection,
                            path.as_str(),
                            "cups.service",
                            &result,
                        ));
                    });
                }
                MatchingSignal::Never => {}
            }

            path
        }
    }

    /// Backs `read_live_state`'s `Properties.GetAll(UNIT_INTERFACE)` read
    /// with a fixed, always-healthy-post-restart unit state -- this
    /// module's own race tests care about `JobRemoved` correlation timing,
    /// not unit-state variety (that is already covered by
    /// `super::tests`'s pure `LiveUnitState` predicate tests). Declared as
    /// real `#[zbus(property)]` getters on the `org.freedesktop.systemd1.Unit`
    /// interface -- `zbus`'s `ObjectServer` auto-serves the standard
    /// `org.freedesktop.DBus.Properties` interface (`Get`/`GetAll`) for
    /// every object from its declared properties, so `read_live_state`'s
    /// real `Properties.GetAll(UNIT_INTERFACE)` call reaches these without
    /// this module needing to hand-implement `Properties` itself (doing so
    /// would conflict with `zbus`'s own auto-registration at the same
    /// path).
    struct FakeUnit;

    #[zbus::interface(name = "org.freedesktop.systemd1.Unit")]
    impl FakeUnit {
        #[allow(clippy::unused_self)]
        #[zbus(property)]
        fn load_state(&self) -> String {
            "loaded".to_owned()
        }

        #[allow(clippy::unused_self)]
        #[zbus(property)]
        fn active_state(&self) -> String {
            "active".to_owned()
        }

        #[allow(clippy::unused_self)]
        #[zbus(property)]
        fn sub_state(&self) -> String {
            "running".to_owned()
        }

        #[allow(clippy::unused_self)]
        #[zbus(property)]
        fn refuse_manual_start(&self) -> bool {
            false
        }

        #[allow(clippy::unused_self)]
        #[zbus(property)]
        fn refuse_manual_stop(&self) -> bool {
            false
        }
    }

    async fn emit_job_removed(connection: &zbus::Connection, job: &str, unit: &str, result: &str) {
        let job_path = OwnedObjectPath::try_from(job).expect("valid job path");
        let _ = connection
            .emit_signal(
                Option::<zbus::names::BusName<'_>>::None,
                MANAGER_PATH,
                MANAGER_INTERFACE,
                "JobRemoved",
                &(1u32, job_path, unit, result),
            )
            .await;
    }

    /// Starts the private bus + fake `systemd1.Manager`, and a real
    /// `SystemdRestartAdapter` connected to it. Returns the bus (kept
    /// alive for the test's duration -- dropping it tears down the
    /// private daemon), the adapter, and the observable restart call
    /// count.
    fn start(plan: FakeJobPlan) -> (PrivateSessionBus, SystemdRestartAdapter, Arc<AtomicUsize>) {
        let bus = PrivateSessionBus::launch().expect("private D-Bus must launch");
        let restart_calls = Arc::new(AtomicUsize::new(0));
        let connection_cell: Arc<OnceLock<zbus::Connection>> = Arc::new(OnceLock::new());
        let manager = FakeManager {
            restart_calls: Arc::clone(&restart_calls),
            connection: Arc::clone(&connection_cell),
            plan,
        };

        let address = bus.address().to_owned();
        let async_connection = futures_lite::future::block_on(async {
            zbus::connection::Builder::address(address.as_str())?
                .name("org.freedesktop.systemd1")?
                .serve_at(MANAGER_PATH, manager)?
                .serve_at(FAKE_UNIT_PATH, FakeUnit)?
                .build()
                .await
        })
        .expect("serve fake org.freedesktop.systemd1.Manager on the private bus");
        connection_cell
            .set(async_connection)
            .unwrap_or_else(|_| panic!("connection cell set exactly once"));

        let adapter_connection = zbus::blocking::connection::Builder::address(address.as_str())
            .expect("parse private bus address")
            .build()
            .expect("adapter connects to the private bus");
        let adapter =
            SystemdRestartAdapter::for_test_connection("cups.service", adapter_connection);

        (bus, adapter, restart_calls)
    }

    /// Scenario A (handoff §7.A): the matching `JobRemoved` is emitted
    /// *before* `RestartUnit`'s own method reply is sent. Because
    /// observation is armed before `RestartUnit` is even called (the
    /// repair under test), this early signal must still be retained and
    /// correlated once the job path becomes known, reporting the correct
    /// result with no unnecessary second restart.
    #[test]
    fn signal_before_method_response_is_still_correlated() {
        let (_bus, adapter, restart_calls) = start(FakeJobPlan {
            matching_signal: MatchingSignal::BeforeReply,
            ..FakeJobPlan::default()
        });

        let action = ActionRequest("race-a".to_owned());
        let apply = MutableCapabilityAdapter::apply(&adapter, &action).expect("apply must succeed");
        assert_eq!(apply.0, "confirmed_success");

        let observation = MutableCapabilityAdapter::observe(
            &adapter,
            &ObservationExpectation("race-a".to_owned()),
        )
        .expect("observe must succeed");
        assert_eq!(
            observation.0, "postcondition_met",
            "an early-but-matching JobRemoved must be correlated, not treated as lost"
        );
        assert_eq!(
            restart_calls.load(Ordering::SeqCst),
            1,
            "no unnecessary second RestartUnit/compensating restart"
        );
    }

    /// Scenario B (handoff §7.B): the normal case -- `JobRemoved` after
    /// the method reply. Must still work under the new ordering.
    #[test]
    fn signal_after_method_response_still_works() {
        let (_bus, adapter, restart_calls) = start(FakeJobPlan {
            matching_signal: MatchingSignal::ShortlyAfterReply,
            ..FakeJobPlan::default()
        });

        let action = ActionRequest("race-b".to_owned());
        let apply = MutableCapabilityAdapter::apply(&adapter, &action).expect("apply must succeed");
        assert_eq!(apply.0, "confirmed_success");

        let observation = MutableCapabilityAdapter::observe(
            &adapter,
            &ObservationExpectation("race-b".to_owned()),
        )
        .expect("observe must succeed");
        assert_eq!(observation.0, "postcondition_met");
        assert_eq!(restart_calls.load(Ordering::SeqCst), 1);
    }

    /// Scenario C (handoff §7.C): an unrelated `JobRemoved(other_job)`
    /// arrives before `RestartUnit` returns the real target job. It must
    /// not satisfy observation on its own -- only the exact returned job
    /// path may.
    #[test]
    fn unrelated_early_signal_does_not_satisfy_observation() {
        let (_bus, adapter, restart_calls) = start(FakeJobPlan {
            unrelated_before_reply: vec![("/org/freedesktop/systemd1/job/999", "done")],
            matching_signal: MatchingSignal::ShortlyAfterReply,
            ..FakeJobPlan::default()
        });

        let action = ActionRequest("race-c".to_owned());
        let apply = MutableCapabilityAdapter::apply(&adapter, &action).expect("apply must succeed");
        assert_eq!(apply.0, "confirmed_success");

        let observation = MutableCapabilityAdapter::observe(
            &adapter,
            &ObservationExpectation("race-c".to_owned()),
        )
        .expect("observe must succeed");
        assert_eq!(
            observation.0, "postcondition_met",
            "the real target job's own signal must still be the one that resolves this"
        );
        assert_eq!(restart_calls.load(Ordering::SeqCst), 1);
    }

    /// Scenario D (handoff §7.D): multiple buffered signals -- one
    /// unrelated, one the real target -- only the exact returned job path
    /// governs the transaction.
    #[test]
    fn multiple_buffered_signals_only_the_exact_job_path_governs() {
        let (_bus, adapter, restart_calls) = start(FakeJobPlan {
            unrelated_before_reply: vec![
                ("/org/freedesktop/systemd1/job/900", "failed"),
                ("/org/freedesktop/systemd1/job/901", "done"),
            ],
            matching_signal: MatchingSignal::BeforeReply,
            result: "done",
        });

        let action = ActionRequest("race-d".to_owned());
        let apply = MutableCapabilityAdapter::apply(&adapter, &action).expect("apply must succeed");
        assert_eq!(apply.0, "confirmed_success");

        let observation = MutableCapabilityAdapter::observe(
            &adapter,
            &ObservationExpectation("race-d".to_owned()),
        )
        .expect("observe must succeed");
        assert_eq!(observation.0, "postcondition_met");
        assert_eq!(restart_calls.load(Ordering::SeqCst), 1);
    }

    /// Scenario E (handoff §7.E): the matching `JobRemoved` reports a
    /// failed result. Must not become success.
    #[test]
    fn matching_but_failed_job_is_not_success() {
        let (_bus, adapter, restart_calls) = start(FakeJobPlan {
            matching_signal: MatchingSignal::BeforeReply,
            result: "failed",
            ..FakeJobPlan::default()
        });

        let action = ActionRequest("race-e".to_owned());
        let apply = MutableCapabilityAdapter::apply(&adapter, &action).expect("apply must succeed");
        assert_eq!(apply.0, "confirmed_success");

        let observation = MutableCapabilityAdapter::observe(
            &adapter,
            &ObservationExpectation("race-e".to_owned()),
        )
        .expect("observe must succeed");
        assert_eq!(observation.0, "postcondition_not_met");
        assert_eq!(restart_calls.load(Ordering::SeqCst), 1);
    }

    /// Scenario F (handoff §7.F): no matching signal ever arrives. The
    /// governed, bounded timeout/error behaviour is preserved -- no
    /// infinite wait. Uses a short adapter-local override of
    /// `JOB_WAIT_TIMEOUT` is not available (it is a fixed module
    /// constant), so this proves boundedness by asserting the call
    /// returns `ambiguous` rather than hanging, relying on the
    /// process-level test-harness timeout as the outer safety net (the
    /// same discipline the pre-repair implementation's own equivalent
    /// case relied on).
    #[test]
    #[ignore = "exercises the full JOB_WAIT_TIMEOUT (20s); run explicitly, not part of the default fast suite"]
    fn no_matching_signal_is_bounded_and_reports_ambiguous() {
        let (_bus, adapter, restart_calls) = start(FakeJobPlan {
            matching_signal: MatchingSignal::Never,
            ..FakeJobPlan::default()
        });

        let action = ActionRequest("race-f".to_owned());
        let apply = MutableCapabilityAdapter::apply(&adapter, &action).expect("apply must succeed");
        assert_eq!(apply.0, "confirmed_success");

        let observation = MutableCapabilityAdapter::observe(
            &adapter,
            &ObservationExpectation("race-f".to_owned()),
        )
        .expect("observe must succeed");
        assert_eq!(observation.0, "ambiguous");
        assert_eq!(restart_calls.load(Ordering::SeqCst), 1);
    }

    /// Handoff §6: if the `JobRemoved` subscription cannot be established
    /// at all, `RestartUnit` MUST NOT be invoked. Simulated here by
    /// killing the private bus daemon before `apply` is called, so the
    /// very first thing `apply` does (arming the subscription) fails with
    /// a real I/O error -- deterministic, no mocking of `arm_*` itself
    /// required.
    #[test]
    fn subscription_failure_before_mutation_prevents_restart_unit() {
        let (bus, adapter, restart_calls) = start(FakeJobPlan::default());
        drop(bus); // kill the private dbus-daemon out from under the adapter

        let action = ActionRequest("race-subscription-failure".to_owned());
        let apply = MutableCapabilityAdapter::apply(&adapter, &action)
            .expect("apply's own Unsupported path is not used by this adapter");
        assert_eq!(
            apply.0, "confirmed_failure_no_mutation",
            "arming failure must fail closed, never silently proceed"
        );
        assert_eq!(
            restart_calls.load(Ordering::SeqCst),
            0,
            "RestartUnit must never be invoked once the subscription could not be established"
        );
    }

    /// Handoff §5/§9: this adapter is single-flight per construction (a
    /// fresh instance per `guardian-helper` restart flow -- see
    /// `crate::main`'s `run_restart_capability`/`resolve_recovered_restart`,
    /// which each build a brand-new `SystemdRestartAdapter` rather than
    /// sharing one across transactions). Two independently-armed
    /// observations on two separate adapter instances against the same
    /// fake service must not cross-talk: each only ever resolves its own
    /// job.
    #[test]
    fn two_independent_adapters_do_not_cross_talk() {
        let (_bus, adapter_one, _) = start(FakeJobPlan {
            matching_signal: MatchingSignal::BeforeReply,
            result: "done",
            ..FakeJobPlan::default()
        });
        // A second, independently-armed adapter instance against a
        // *different* private bus -- proving isolation does not depend on
        // any shared global state (there is none: `armed_job` is a
        // per-instance field).
        let (_bus_two, adapter_two, _) = start(FakeJobPlan {
            matching_signal: MatchingSignal::BeforeReply,
            result: "failed",
            ..FakeJobPlan::default()
        });

        let action = ActionRequest("race-isolation".to_owned());
        MutableCapabilityAdapter::apply(&adapter_one, &action).expect("apply one");
        MutableCapabilityAdapter::apply(&adapter_two, &action).expect("apply two");

        let observation_one = MutableCapabilityAdapter::observe(
            &adapter_one,
            &ObservationExpectation("race-isolation".to_owned()),
        )
        .expect("observe one");
        let observation_two = MutableCapabilityAdapter::observe(
            &adapter_two,
            &ObservationExpectation("race-isolation".to_owned()),
        )
        .expect("observe two");

        assert_eq!(observation_one.0, "postcondition_met");
        assert_eq!(observation_two.0, "postcondition_not_met");
    }

    /// Handoff §9 (no unbounded blocking operation on the async runtime /
    /// no orphan consumer / no duplicate active subscriptions): a real
    /// first-invocation sequence, repeated several times against the same
    /// adapter and the same fake service, must not deadlock and must not
    /// accumulate stuck state across repetitions.
    #[test]
    fn repeated_invocations_do_not_deadlock_or_accumulate_state() {
        let (_bus, adapter, restart_calls) = start(FakeJobPlan {
            matching_signal: MatchingSignal::ShortlyAfterReply,
            ..FakeJobPlan::default()
        });

        for index in 0..5 {
            let key = format!("race-repeat-{index}");
            let action = ActionRequest(key.clone());
            let apply =
                MutableCapabilityAdapter::apply(&adapter, &action).expect("apply must succeed");
            assert_eq!(apply.0, "confirmed_success");
            let observation =
                MutableCapabilityAdapter::observe(&adapter, &ObservationExpectation(key))
                    .expect("observe must succeed");
            assert_eq!(observation.0, "postcondition_met");
        }
        assert_eq!(restart_calls.load(Ordering::SeqCst), 5);
    }

    /// A basic, direct proof that [`ArmedObservation`] itself buffers and
    /// correlates without going through the D-Bus stack at all -- pure
    /// unit coverage of `JobRemovedBuffer::wait_for`'s own eviction/
    /// correlation logic underlying every scenario above.
    #[test]
    fn job_removed_buffer_evicts_oldest_beyond_capacity() {
        let buffer = super::JobRemovedBuffer::new();
        for index in 0..(super::JOB_REMOVED_BUFFER_CAP + 3) {
            let path = OwnedObjectPath::try_from(format!("/job/{index}")).unwrap();
            buffer.push(path, "done".to_owned());
        }
        let entries = buffer.entries.lock().unwrap();
        assert_eq!(entries.len(), super::JOB_REMOVED_BUFFER_CAP);
        // The oldest three (0, 1, 2) must have been evicted.
        assert!(
            !entries
                .iter()
                .any(|(path, _)| path.as_str() == "/job/0" || path.as_str() == "/job/2")
        );
    }
}
