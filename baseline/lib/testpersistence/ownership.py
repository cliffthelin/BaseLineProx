"""Store-level ownership/recovery authority (PRD §5, §8) - kept
separate from application access grants (see grants.py). Ownership is
not created or implied by an application's grant."""
import dataclasses


@dataclasses.dataclass(frozen=True)
class RecoveryAuthority:
    held_by: str  # synthetic person identifier, e.g. "TestPerson-001"
    mechanism: str  # e.g. "test-passphrase-placeholder"


def can_authorize_import(authority: RecoveryAuthority, requester: str) -> bool:
    """Only the recovery-authority holder can authorize importing this
    store onto a new host (PRD §5's "explicit local import
    authorization") - a grant, however broad, never substitutes."""
    return authority.held_by == requester
