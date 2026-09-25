"""Structured failure/refusal outcomes (PRD §13) - one Outcome per
attachment failure mode, never a raised exception whose meaning a
caller must guess, and never silent success. No failure mode here ever
produces an auto-created empty replacement store."""
import dataclasses
import enum


class FailureMode(enum.Enum):
    MISSING = "missing"
    LOCKED = "locked"
    UNKNOWN = "unknown"
    CLONED = "cloned"
    CORRUPTED = "corrupted"
    READ_ONLY = "read_only"
    FULL = "full"
    NEWER_SCHEMA = "newer_schema"


@dataclasses.dataclass(frozen=True)
class Outcome:
    failure_mode: FailureMode
    degraded: bool
    message: str


def outcome_for(mode: FailureMode, message: str, *, degraded: bool = True) -> Outcome:
    return Outcome(mode, degraded, message)


def missing_store_outcome() -> Outcome:
    return outcome_for(FailureMode.MISSING,
                        "store was previously attached but is not present - no auto-recreate")


def full_store_outcome(ledger_append_succeeded: bool) -> Outcome:
    """PRD §13's reserved recovery/ledger capacity requirement: a
    full-store condition must always be recordable. If the reserved
    capacity itself is exhausted, that is a construction error, not a
    normal failure outcome to report quietly."""
    if not ledger_append_succeeded:
        raise RuntimeError(
            "full-store condition could not be recorded - reserved ledger "
            "capacity (PRD §13) was exhausted too, which must never happen "
            "by construction")
    return outcome_for(FailureMode.FULL,
                        "write refused, no truncation - failure recorded in reserved "
                        "ledger capacity")


def unknown_store_outcome() -> Outcome:
    return outcome_for(FailureMode.UNKNOWN,
                        "no recognizable manifest - stays below inspection_ready, "
                        "never auto-formatted")


def cloned_store_outcome() -> Outcome:
    return outcome_for(FailureMode.CLONED,
                        "identity-evidence collision - ambiguous/refusal, no silent pick-one")
