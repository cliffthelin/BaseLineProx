"""Test helper: obtain a REAL authorization through the real challenge-and-confirm flow (never a shortcut)."""
import drive_admin as da
import hitl

SECRET = "test-secret"


class ManualClock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def new_store(clock=None, audit=None):
    return hitl.ConfirmationStore(verify_secret=lambda s: s == SECRET, clock=clock or ManualClock(), audit=audit)


def authorize(action_id, params, *, pds_runner=None, store=None, session="test-session"):
    """Challenge -> wait -> confirm. Returns (authorization, store) for exactly this request."""
    store = store or new_store()
    prepared = da.prepare_action(action_id, params, pds_runner=pds_runner)
    chal = store.challenge(session, action_id, prepared["params"], prepared["serial"], prepared["summary"])
    store.clock.advance(store.min_wait_s + 1)
    return store.confirm(session, chal["id"], chal["phrase"], SECRET), store


def perform_confirmed(runner, action_id, params, *, pds_runner=None, **kw):
    auth, store = authorize(action_id, params, pds_runner=pds_runner)
    return da.perform_action(runner, action_id, params, pds_runner=pds_runner, authorization=auth, hitl_store=store, **kw)
