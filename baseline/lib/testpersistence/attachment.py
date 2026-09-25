"""Attachment state machine (PRD §7) - the explicit legal-transition
table matches the PRD's own mermaid diagram exactly. attempt_transition
refuses any transition not in the table (raises TransitionError);
nothing here auto-advances past a decision point, and an unrecognized
manifest can never reach inspection_ready (PRD §13's "Unknown" row)."""
import enum


class AttachmentState(enum.Enum):
    ABSENT = "absent"
    DETECTED_UNKNOWN = "detected_unknown"
    RECOGNIZED_LOCKED = "recognized_locked"
    UNLOCKED_UNTRUSTED = "unlocked_untrusted"
    INSPECTION_READY = "inspection_ready"
    IMPORT_PROPOSED = "import_proposed"
    AUTHORIZED = "authorized"
    ATTACHED = "attached"
    DEGRADED = "degraded"
    REQUIRES_RECOVERY = "requires_recovery"


class TransitionError(Exception):
    pass


# (from_state, event) -> to_state, transcribed directly from the PRD §7
# mermaid diagram. requires_recovery's only PRD-documented exit is
# "human remediation decision, out of this state machine's own scope" -
# deliberately not modeled as an event here, so requires_recovery has
# no outgoing transitions in this table.
_LEGAL_TRANSITIONS = {
    (AttachmentState.ABSENT, "device_appears"): AttachmentState.DETECTED_UNKNOWN,
    (AttachmentState.DETECTED_UNKNOWN, "luks_header_recognized"): AttachmentState.RECOGNIZED_LOCKED,
    (AttachmentState.DETECTED_UNKNOWN, "unrecognized_or_corrupt_header"): AttachmentState.REQUIRES_RECOVERY,
    (AttachmentState.RECOGNIZED_LOCKED, "correct_key_supplied"): AttachmentState.UNLOCKED_UNTRUSTED,
    (AttachmentState.UNLOCKED_UNTRUSTED, "manifest_parses_known_schema"): AttachmentState.INSPECTION_READY,
    (AttachmentState.UNLOCKED_UNTRUSTED, "manifest_unreadable_or_newer_schema"): AttachmentState.REQUIRES_RECOVERY,
    (AttachmentState.INSPECTION_READY, "logical_identity_differs"): AttachmentState.IMPORT_PROPOSED,
    (AttachmentState.INSPECTION_READY, "logical_identity_matches_trusted"): AttachmentState.AUTHORIZED,
    (AttachmentState.IMPORT_PROPOSED, "import_authorization_granted"): AttachmentState.AUTHORIZED,
    (AttachmentState.IMPORT_PROPOSED, "import_authorization_declined"): AttachmentState.INSPECTION_READY,
    (AttachmentState.AUTHORIZED, "broker_session_established"): AttachmentState.ATTACHED,
    (AttachmentState.ATTACHED, "failure_mode_occurs"): AttachmentState.DEGRADED,
    (AttachmentState.ATTACHED, "clean_detach"): AttachmentState.ABSENT,
    (AttachmentState.DEGRADED, "failure_not_self_resolving"): AttachmentState.REQUIRES_RECOVERY,
    (AttachmentState.DEGRADED, "failure_clears"): AttachmentState.ATTACHED,
}


def attempt_transition(current: AttachmentState, event: str) -> AttachmentState:
    key = (current, event)
    if key not in _LEGAL_TRANSITIONS:
        raise TransitionError(
            f"no legal transition from {current.value} on event {event!r} - "
            f"refusing rather than guessing")
    return _LEGAL_TRANSITIONS[key]


def is_legal_transition(current: AttachmentState, event: str) -> bool:
    return (current, event) in _LEGAL_TRANSITIONS


def all_events_from(current: AttachmentState) -> tuple:
    return tuple(event for (state, event) in _LEGAL_TRANSITIONS if state == current)
