"""Attachment state machine (PRD §7) - every legal transition from the
mermaid diagram, plus illegal transitions refused."""
import pytest

from testpersistence.attachment import AttachmentState as S
from testpersistence.attachment import TransitionError, attempt_transition, is_legal_transition


LEGAL = [
    (S.ABSENT, "device_appears", S.DETECTED_UNKNOWN),
    (S.DETECTED_UNKNOWN, "luks_header_recognized", S.RECOGNIZED_LOCKED),
    (S.DETECTED_UNKNOWN, "unrecognized_or_corrupt_header", S.REQUIRES_RECOVERY),
    (S.RECOGNIZED_LOCKED, "correct_key_supplied", S.UNLOCKED_UNTRUSTED),
    (S.UNLOCKED_UNTRUSTED, "manifest_parses_known_schema", S.INSPECTION_READY),
    (S.UNLOCKED_UNTRUSTED, "manifest_unreadable_or_newer_schema", S.REQUIRES_RECOVERY),
    (S.INSPECTION_READY, "logical_identity_differs", S.IMPORT_PROPOSED),
    (S.INSPECTION_READY, "logical_identity_matches_trusted", S.AUTHORIZED),
    (S.IMPORT_PROPOSED, "import_authorization_granted", S.AUTHORIZED),
    (S.IMPORT_PROPOSED, "import_authorization_declined", S.INSPECTION_READY),
    (S.AUTHORIZED, "broker_session_established", S.ATTACHED),
    (S.ATTACHED, "failure_mode_occurs", S.DEGRADED),
    (S.ATTACHED, "clean_detach", S.ABSENT),
    (S.DEGRADED, "failure_not_self_resolving", S.REQUIRES_RECOVERY),
    (S.DEGRADED, "failure_clears", S.ATTACHED),
]


@pytest.mark.parametrize("start,event,expected", LEGAL)
def test_every_legal_transition(start, event, expected):
    assert attempt_transition(start, event) == expected
    assert is_legal_transition(start, event)


def test_unknown_manifest_never_reaches_inspection_ready_directly():
    with pytest.raises(TransitionError):
        attempt_transition(S.DETECTED_UNKNOWN, "manifest_parses_known_schema")


def test_requires_recovery_has_no_modeled_exit():
    for event in ("device_appears", "clean_detach", "failure_clears"):
        with pytest.raises(TransitionError):
            attempt_transition(S.REQUIRES_RECOVERY, event)


@pytest.mark.parametrize("start,event", [
    (S.ABSENT, "correct_key_supplied"),
    (S.RECOGNIZED_LOCKED, "broker_session_established"),
    (S.ATTACHED, "import_authorization_granted"),
    (S.INSPECTION_READY, "device_appears"),
    (S.AUTHORIZED, "failure_clears"),
])
def test_illegal_transitions_are_refused(start, event):
    assert not is_legal_transition(start, event)
    with pytest.raises(TransitionError):
        attempt_transition(start, event)


def test_governing_invariant_detection_never_attaches_writable():
    # detected_unknown has no direct path to attached/authorized without
    # passing through unlock + inspection + (import or trust match).
    reachable_in_one_hop = {attempt_transition(S.DETECTED_UNKNOWN, e)
                             for e in ("luks_header_recognized", "unrecognized_or_corrupt_header")}
    assert S.ATTACHED not in reachable_in_one_hop
    assert S.AUTHORIZED not in reachable_in_one_hop
