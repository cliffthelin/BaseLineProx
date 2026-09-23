"""Unit tests for settings_web.py's routing/decision logic (PRD SS5.16) -
login, settings review/edit, and the two-safe-flow-else-hand-off gate
around rebuild. Exercises the handle_* functions directly with fakes,
not real sockets - the real HTTP wiring is a thin pass-through covered
by manual browser verification (see decision record for this module)."""
import settings_web as sw


class FakeVerifier(sw.PasswordVerifier):
    def __init__(self, users: dict):
        self.users = users

    def verify(self, username, password):
        return self.users.get(username) == password


class FakeSource(sw.SettingsSource):
    def __init__(self, settings: dict):
        self.settings = settings

    def current_settings(self):
        return self.settings


class FakeApplier(sw.SectionApplier):
    def __init__(self):
        self.calls = []

    def apply(self, section, new_values):
        self.calls.append((section, new_values))
        return sw.ApplyResult(applied=True, detail=f"{section} applied")


class FakeEligibility(sw.RebuildEligibility):
    def __init__(self, eligible_targets: set):
        self.eligible_targets = eligible_targets

    def is_eligible(self, target):
        if target in self.eligible_targets:
            return True, "explicitly allow-listed for this test"
        return False, "not eligible"


class FakeTrigger(sw.RebuildTrigger):
    def __init__(self):
        self.calls = []

    def rebuild(self, target, config):
        self.calls.append((target, config))
        return sw.ApplyResult(applied=True, detail="rebuilt")


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------

def test_login_succeeds_with_correct_credentials():
    sessions = sw.SessionStore()
    result = sw.handle_login(FakeVerifier({"root": "baseline"}), sessions, "root", "baseline", now=1000.0)
    assert result.outcome == "applied"
    assert "token" in result.body


def test_login_fails_with_wrong_password():
    sessions = sw.SessionStore()
    result = sw.handle_login(FakeVerifier({"root": "baseline"}), sessions, "root", "wrong", now=1000.0)
    assert result.outcome == "refused"
    assert result.status == 401


def test_login_fails_with_unknown_username_same_shape_as_wrong_password():
    sessions = sw.SessionStore()
    unknown_result = sw.handle_login(FakeVerifier({"root": "baseline"}), sessions, "ghost", "x", now=1000.0)
    wrong_pw_result = sw.handle_login(FakeVerifier({"root": "baseline"}), sessions, "root", "x", now=1000.0)
    assert unknown_result.status == wrong_pw_result.status == 401
    assert unknown_result.body == wrong_pw_result.body  # no username enumeration


# --------------------------------------------------------------------------
# Settings view / edit
# --------------------------------------------------------------------------

def test_settings_view_requires_valid_session():
    sessions = sw.SessionStore()
    result = sw.handle_settings_view(sessions, FakeSource({"network": {}}), token="bogus", now=1000.0)
    assert result.outcome == "refused"
    assert result.status == 401


def test_settings_view_succeeds_with_valid_session():
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    result = sw.handle_settings_view(sessions, FakeSource({"network": {"hostname": "x"}}),
                                      token=session.token, now=1001.0)
    assert result.outcome == "applied"
    assert result.body["settings"]["network"]["hostname"] == "x"


def test_settings_edit_rejects_unknown_section_without_calling_applier():
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    applier = FakeApplier()
    result = sw.handle_settings_edit(sessions, applier, session.token, "not_a_real_section",
                                      {"x": 1}, now=1001.0)
    assert result.outcome == "handed_off"
    assert applier.calls == []


def test_settings_edit_applies_known_section():
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    applier = FakeApplier()
    result = sw.handle_settings_edit(sessions, applier, session.token, "network",
                                      {"hostname": "new"}, now=1001.0)
    assert result.outcome == "applied"
    assert applier.calls == [("network", {"hostname": "new"})]


def test_settings_edit_requires_valid_session():
    sessions = sw.SessionStore()
    applier = FakeApplier()
    result = sw.handle_settings_edit(sessions, applier, "bogus-token", "network", {}, now=1000.0)
    assert result.outcome == "refused"
    assert applier.calls == []


def test_session_expires_after_ttl():
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    session.ttl_s = 60.0
    result = sw.handle_settings_view(sessions, FakeSource({}), token=session.token, now=1000.0 + 61.0)
    assert result.outcome == "refused"


# --------------------------------------------------------------------------
# New account (flow 2, step 1)
# --------------------------------------------------------------------------

def test_new_account_requires_username_and_password():
    result = sw.handle_new_account(sw.default_hasher, "", "")
    assert result.outcome == "refused"


def test_new_account_succeeds_with_both_fields():
    result = sw.handle_new_account(lambda pw: f"hashed:{pw}", "operator", "secret123")
    assert result.outcome == "applied"
    assert result.body["account"] == "operator"


# --------------------------------------------------------------------------
# Rebuild - the one destructive trigger, and its hand-off default
# --------------------------------------------------------------------------

def test_rebuild_refuses_and_never_calls_trigger_when_not_eligible():
    eligibility = FakeEligibility(eligible_targets=set())  # nothing eligible
    trigger = FakeTrigger()
    result = sw.handle_rebuild(eligibility, trigger, "/dev/sdc", {})
    assert result.outcome == "handed_off"
    assert trigger.calls == []  # the safety property: never silently executes


def test_rebuild_refuses_a_real_device_path_by_default():
    eligibility = sw.PathPrefixRebuildEligibility()  # real default implementation
    trigger = FakeTrigger()
    result = sw.handle_rebuild(eligibility, trigger, "/dev/sdc", {})
    assert result.outcome == "handed_off"
    assert trigger.calls == []


def test_rebuild_proceeds_only_for_an_explicitly_eligible_target():
    eligibility = FakeEligibility(eligible_targets={"/tmp/scratch.img"})
    trigger = FakeTrigger()
    result = sw.handle_rebuild(eligibility, trigger, "/tmp/scratch.img", {"k": "v"})
    assert result.outcome == "applied"
    assert trigger.calls == [("/tmp/scratch.img", {"k": "v"})]


def test_path_prefix_eligibility_accepts_configured_disposable_prefix():
    eligibility = sw.PathPrefixRebuildEligibility(disposable_prefixes=("/tmp/",))
    eligible, _ = eligibility.is_eligible("/tmp/anything.img")
    assert eligible is True


def test_path_prefix_eligibility_rejects_everything_else():
    eligibility = sw.PathPrefixRebuildEligibility(disposable_prefixes=("/tmp/",))
    eligible, reason = eligibility.is_eligible("/dev/sdb")
    assert eligible is False
    assert "disposable-target prefix" in reason


# --------------------------------------------------------------------------
# Real default implementations (JsonFileStore-backed), exercised for real
# --------------------------------------------------------------------------

def test_file_backed_verifier_round_trips_a_real_sha512crypt_hash(tmp_path):
    store = sw.JsonFileStore(tmp_path / "store.json")
    store.add_user("alice", sw._sha512crypt("correct horse", sw._new_salt()))
    verifier = sw.FileBackedPasswordVerifier(store)
    assert verifier.verify("alice", "correct horse") is True
    assert verifier.verify("alice", "wrong") is False
    assert verifier.verify("nobody", "x") is False


def test_file_backed_applier_persists_across_a_new_store_instance(tmp_path):
    path = tmp_path / "store.json"
    store1 = sw.JsonFileStore(path)
    sw.FileBackedSectionApplier(store1).apply("firewall", {"allow_lan_only": False})

    store2 = sw.JsonFileStore(path)  # fresh instance, same file
    assert store2.settings()["firewall"]["allow_lan_only"] is False


def test_logging_rebuild_trigger_records_a_real_observable_entry(tmp_path):
    store = sw.JsonFileStore(tmp_path / "store.json")
    trigger = sw.LoggingRebuildTrigger(store, clock=lambda: 42.0)
    result = trigger.rebuild("/tmp/x.img", {"a": 1})
    assert result.applied is True
    log = store._read()["rebuild_log"]
    assert log == [{"target": "/tmp/x.img", "config": {"a": 1}, "at": 42.0}]
