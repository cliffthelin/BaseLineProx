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
    """Confirmed by a person AND asked for by the web app (a genuinely signed origin from a test gate)."""
    import web_origin_helper
    auth, store = authorize(action_id, params, pds_runner=pds_runner)
    prepared = da.prepare_action(action_id, params, pds_runner=pds_runner)
    origin = web_origin_helper.origin_for("drive_action", {"action_id": action_id, "params": prepared["params"]})
    return da.perform_action(runner, action_id, params, pds_runner=pds_runner, authorization=auth, hitl_store=store,
                             origin=origin, **kw)


def perform_with_origin(runner, action_id, params, **kw):
    """perform_action with a genuinely signed web origin and nothing else: for tests of the layers behind the
    gate (confirmation, validation). A request that cannot even be prepared goes without one: it is refused first."""
    import web_origin_helper
    if "origin" not in kw:
        try:
            prepared = da.prepare_action(action_id, params, pds_runner=kw.get("pds_runner"))
            kw["origin"] = web_origin_helper.origin_for("drive_action", {"action_id": action_id, "params": prepared["params"]})
        except ValueError:
            pass
    return da.perform_action(runner, action_id, params, **kw)
