"""Application lifecycle operations (PRD §10) - install through
delete-state, each with a defined effect on application state and any
grants that reference person data through this application. Uninstall
never deletes persistence by default; only the separate, explicit
delete_state() operation does, and that revokes grants rather than
merely suspending them."""
import dataclasses
import enum


class ApplicationLifecycleState(enum.Enum):
    INSTALLED = "installed"
    DISABLED = "disabled"
    UNINSTALLED_RETAINED = "uninstalled_retained"
    STATE_DELETED = "state_deleted"


@dataclasses.dataclass
class Application:
    application_id: str
    state: ApplicationLifecycleState = ApplicationLifecycleState.INSTALLED
    grants: list = dataclasses.field(default_factory=list)  # Grant objects this app holds

    def disable(self) -> None:
        self.state = ApplicationLifecycleState.DISABLED
        for grant in self.grants:
            grant.suspend()

    def re_enable(self, *, reactivate_grants: bool = False) -> None:
        """reactivate_grants defaults False: re-enabling alone must
        never implicitly resume access (PRD §10) - a caller opts in
        explicitly, modeling the "explicit policy" decision the PRD
        leaves open rather than resolving it silently."""
        self.state = ApplicationLifecycleState.INSTALLED
        if reactivate_grants:
            for grant in self.grants:
                grant.reactivate()

    def uninstall(self) -> None:
        """Retained by default (PRD §10): state is not deleted, and
        grants are suspended, not revoked."""
        self.state = ApplicationLifecycleState.UNINSTALLED_RETAINED
        for grant in self.grants:
            grant.suspend()

    def delete_state(self) -> None:
        """Explicit, separate operation from uninstall. Grants are
        revoked (terminal) as part of this operation, not merely
        suspended."""
        self.state = ApplicationLifecycleState.STATE_DELETED
        for grant in self.grants:
            grant.revoke()
