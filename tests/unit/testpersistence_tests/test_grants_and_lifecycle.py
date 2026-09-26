"""Grant suspension/revocation and application lifecycle (PRD §8, §10):
disable/uninstall suspend grants automatically; only delete_state
revokes them; revocation is terminal."""
from testpersistence.grants import Grant, GrantState
from testpersistence.lifecycle import Application, ApplicationLifecycleState


def _grant(grant_id="TestGrant-001"):
    return Grant(grant_id=grant_id, person="TestPerson-001", application="TestApplication-A",
                 collection="TestDocuments", access_mode="read", duration="until_revoked",
                 authorized_by="bootstrap")


def test_grant_starts_active_and_effective():
    grant = _grant()
    assert grant.state == GrantState.ACTIVE
    assert grant.effective


def test_suspend_makes_grant_ineffective_but_preserves_history():
    grant = _grant()
    grant.suspend()
    assert grant.state == GrantState.SUSPENDED
    assert not grant.effective
    assert grant.grant_id == "TestGrant-001"  # the record itself is retained, not deleted


def test_reactivate_restores_active_only_from_suspended():
    grant = _grant()
    grant.suspend()
    grant.reactivate()
    assert grant.state == GrantState.ACTIVE
    assert grant.effective


def test_revoke_is_terminal_reactivate_cannot_undo_it():
    grant = _grant()
    grant.revoke()
    assert grant.state == GrantState.REVOKED
    grant.reactivate()  # must be a no-op on a revoked grant
    assert grant.state == GrantState.REVOKED
    assert not grant.effective


def test_expired_grant_is_also_not_reactivated_by_reactivate():
    grant = _grant()
    grant.expire()
    grant.reactivate()
    assert grant.state == GrantState.EXPIRED


def test_expire_is_terminal_like_revoke_cannot_un_revoke_a_grant():
    """A revoked grant must stay revoked - expire() must never silently
    overwrite that terminal state into EXPIRED, which would erase the
    fact it was revoked."""
    grant = _grant()
    grant.revoke()
    grant.expire()
    assert grant.state == GrantState.REVOKED
    assert not grant.effective


def test_expire_acts_on_active_or_suspended_grants():
    active = _grant("TestGrant-001")
    active.expire()
    assert active.state == GrantState.EXPIRED

    suspended = _grant("TestGrant-002")
    suspended.suspend()
    suspended.expire()
    assert suspended.state == GrantState.EXPIRED


# --- application lifecycle --------------------------------------------------

def test_disable_suspends_all_grants_automatically():
    app = Application(application_id="TestApplication-A", grants=[_grant(), _grant("TestGrant-002")])
    app.disable()
    assert app.state == ApplicationLifecycleState.DISABLED
    assert all(not g.effective for g in app.grants)
    assert all(g.state == GrantState.SUSPENDED for g in app.grants)


def test_re_enable_does_not_implicitly_reactivate_grants():
    app = Application(application_id="TestApplication-A", grants=[_grant()])
    app.disable()
    app.re_enable()  # reactivate_grants defaults False
    assert app.state == ApplicationLifecycleState.INSTALLED
    assert not app.grants[0].effective


def test_re_enable_can_explicitly_reactivate_grants():
    app = Application(application_id="TestApplication-A", grants=[_grant()])
    app.disable()
    app.re_enable(reactivate_grants=True)
    assert app.grants[0].effective


def test_uninstall_retains_state_and_suspends_but_does_not_revoke():
    app = Application(application_id="TestApplication-A", grants=[_grant()])
    app.uninstall()
    assert app.state == ApplicationLifecycleState.UNINSTALLED_RETAINED
    assert app.grants[0].state == GrantState.SUSPENDED  # not REVOKED


def test_delete_state_revokes_grants_uninstall_alone_does_not():
    app = Application(application_id="TestApplication-A", grants=[_grant()])
    app.uninstall()
    assert app.grants[0].state != GrantState.REVOKED
    app.delete_state()
    assert app.state == ApplicationLifecycleState.STATE_DELETED
    assert app.grants[0].state == GrantState.REVOKED


def test_application_isolation_grants_are_per_application_object():
    app_a = Application(application_id="TestApplication-A", grants=[_grant("TestGrant-001")])
    app_b = Application(application_id="TestApplication-B", grants=[_grant("TestGrant-002")])
    app_a.disable()
    # Disabling A must never touch B's independently-held grants.
    assert app_b.grants[0].effective
