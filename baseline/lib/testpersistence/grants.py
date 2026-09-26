"""Application access grants (PRD §8, §10) - separate from ownership
(ownership.py). A grant's `effective` flag reflects automatic
suspension on application disable/uninstall; only explicit revocation
removes access permanently, and revocation is terminal - it never
returns to active or suspended, including via reactivate() or
expire()."""
import dataclasses
import enum


class GrantState(enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclasses.dataclass
class Grant:
    grant_id: str
    person: str
    application: str
    collection: str
    access_mode: str
    duration: str  # "until_revoked" or an expiry marker
    authorized_by: str
    state: GrantState = GrantState.ACTIVE

    @property
    def effective(self) -> bool:
        return self.state == GrantState.ACTIVE

    def suspend(self) -> None:
        """Automatic suspension on application disable/uninstall
        (PRD §10). Never moves a revoked or expired grant, which stay
        in their own terminal state."""
        if self.state == GrantState.ACTIVE:
            self.state = GrantState.SUSPENDED

    def reactivate(self) -> None:
        """Re-enabling an application does not automatically reactivate
        a grant - the PRD leaves the reactivation policy open (§10), so
        this method exists but callers must invoke it explicitly, never
        as an implicit side effect of re-enable alone."""
        if self.state == GrantState.SUSPENDED:
            self.state = GrantState.ACTIVE

    def revoke(self) -> None:
        """Terminal: a revoked grant never returns to active or
        suspended, including via reactivate()."""
        self.state = GrantState.REVOKED

    def expire(self) -> None:
        """Terminal, like revoke() - never overwrites an already-
        revoked grant. A grant can expire while ACTIVE or SUSPENDED;
        once REVOKED (or already EXPIRED), this is a no-op. Without
        this guard, expire() would silently un-revoke a REVOKED grant
        into EXPIRED, contradicting this module's own "revocation is
        terminal" invariant."""
        if self.state in (GrantState.ACTIVE, GrantState.SUSPENDED):
            self.state = GrantState.EXPIRED
