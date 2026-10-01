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
# Persona-aware wiring (work-queue item 25, decision record 78): a
# session's data (settings_web's own account/settings store, redirected
# via persist_bind_mounts onto whichever persona is active) can change
# identity underneath it if the active persona switches mid-session.
# --------------------------------------------------------------------------

class FakePersonaProvider(sw.ActivePersonaProvider):
    def __init__(self, persona: str):
        self.persona = persona

    def current_persona(self):
        return self.persona


def test_login_without_a_persona_provider_is_unaffected_legacy_behavior():
    sessions = sw.SessionStore()
    result = sw.handle_login(FakeVerifier({"root": "baseline"}), sessions, "root", "baseline", now=1000.0)
    token = result.body["token"]
    session = sessions.get(token, now=1000.0)
    assert session.persona is None


def test_login_records_the_active_persona_when_a_provider_is_supplied():
    sessions = sw.SessionStore()
    result = sw.handle_login(FakeVerifier({"root": "baseline"}), sessions, "root", "baseline", now=1000.0,
                              persona_provider=FakePersonaProvider("admin"))
    token = result.body["token"]
    session = sessions.get(token, now=1000.0)
    assert session.persona == "admin"


def test_settings_view_succeeds_when_persona_unchanged_since_login():
    sessions = sw.SessionStore()
    provider = FakePersonaProvider("admin")
    login = sw.handle_login(FakeVerifier({"root": "baseline"}), sessions, "root", "baseline", now=1000.0,
                             persona_provider=provider)
    result = sw.handle_settings_view(sessions, FakeSource({"network": {}}), token=login.body["token"],
                                      now=1001.0, persona_provider=provider)
    assert result.outcome == "applied"


def test_settings_view_refuses_a_stale_session_after_persona_switches():
    sessions = sw.SessionStore()
    provider = FakePersonaProvider("admin")
    login = sw.handle_login(FakeVerifier({"root": "baseline"}), sessions, "root", "baseline", now=1000.0,
                             persona_provider=provider)
    provider.persona = "personal"  # the active persona switched underneath this session
    result = sw.handle_settings_view(sessions, FakeSource({"network": {}}), token=login.body["token"],
                                      now=1001.0, persona_provider=provider)
    assert result.outcome == "refused"
    assert result.status == 401
    assert result.body["session_persona"] == "admin"
    assert result.body["active_persona"] == "personal"


def test_settings_edit_refuses_a_stale_session_after_persona_switches_without_calling_applier():
    sessions = sw.SessionStore()
    provider = FakePersonaProvider("admin")
    login = sw.handle_login(FakeVerifier({"root": "baseline"}), sessions, "root", "baseline", now=1000.0,
                             persona_provider=provider)
    provider.persona = "personal"
    applier = FakeApplier()
    result = sw.handle_settings_edit(sessions, applier, login.body["token"], "network", {"hostname": "x"},
                                      now=1001.0, persona_provider=provider)
    assert result.outcome == "refused"
    assert applier.calls == []


# --------------------------------------------------------------------------
# The Admin tab (work-queue item 28, decision record 80): a real web
# surface over settings_store.py's schema-driven groups, gated on a
# real admin_elevation ticket for edits.
# --------------------------------------------------------------------------

def test_admin_view_requires_a_valid_session():
    sessions = sw.SessionStore()
    result = sw.handle_admin_view(sessions, token="bogus", now=1000.0)
    assert result.outcome == "refused"
    assert result.status == 401


def test_admin_view_returns_real_effective_settings():
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    result = sw.handle_admin_view(sessions, token=session.token, now=1001.0)
    assert result.outcome == "applied"
    assert result.body["settings"]["sessions"]["default_session_ttl_hours"] == 24
    assert result.body["settings"]["startup"]["auto_start_persona"] == "personal"


def test_admin_view_lists_every_registered_dependency():
    """Decision record 91: the Admin tab is the "know what is in
    place" surface - real dependency definitions must be reachable
    from the same view as settings, not only via a function nobody
    calls from the UI."""
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    result = sw.handle_admin_view(sessions, token=session.token, now=1001.0)
    ids = {d["id"] for d in result.body["dependencies"]}
    assert "system.sqlite3_importable" in ids
    assert "install.self_installer_lvm_preset_valid" in ids


def test_admin_view_reflects_a_real_prior_health_check_result():
    import dependencies as dep
    dep.run_checks(phase=dep.ADHOC)
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    result = sw.handle_admin_view(sessions, token=session.token, now=1001.0)
    assert result.body["dependency_results"]["system.sqlite3_importable"]["ok"] is True


def test_admin_view_has_no_results_yet_on_a_never_checked_machine():
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    result = sw.handle_admin_view(sessions, token=session.token, now=1001.0)
    assert result.body["dependency_results"] == {}


def test_render_admin_page_shows_a_real_dependency_and_its_last_result():
    body = sw.render_admin_page(
        {}, elevated=True,
        dependencies=[{"id": "system.sqlite3_importable", "level": "system", "severity": "loud",
                       "description": "x"}],
        dependency_results={"system.sqlite3_importable": {"ok": True, "detail": "'sqlite3' is importable"}},
    ).decode()
    assert "system.sqlite3_importable" in body
    assert "OK" in body
    assert "'sqlite3' is importable" in body


def test_render_admin_page_shows_never_checked_when_no_result_exists():
    body = sw.render_admin_page(
        {}, elevated=True,
        dependencies=[{"id": "install.self_installer_fqdn_valid", "level": "install", "severity": "silent",
                       "description": "x"}],
        dependency_results={},
    ).decode()
    assert "never checked" in body


def test_render_admin_page_omits_the_dependencies_section_when_none_given():
    body = sw.render_admin_page({}, elevated=True).decode()
    assert "<h2>Dependencies</h2>" not in body


def test_admin_elevate_requires_a_valid_session():
    import admin_elevation
    sessions = sw.SessionStore()
    store = admin_elevation.ElevationStore()
    result = sw.handle_admin_elevate(store, lambda p: True, sessions, token="bogus",
                                      passphrase="x", now=1000.0)
    assert result.outcome == "refused"
    assert result.status == 401


def test_admin_elevate_hands_off_when_no_verifier_is_configured():
    import admin_elevation
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    store = admin_elevation.ElevationStore()
    result = sw.handle_admin_elevate(store, None, sessions, token=session.token,
                                      passphrase="x", now=1001.0)
    assert result.outcome == "handed_off"


def test_admin_elevate_refuses_a_wrong_passphrase():
    import admin_elevation
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    store = admin_elevation.ElevationStore()
    result = sw.handle_admin_elevate(store, lambda p: p == "correct", sessions, token=session.token,
                                      passphrase="wrong", now=1001.0)
    assert result.outcome == "refused"
    assert result.status == 401


def test_admin_elevate_grants_a_real_ticket_on_the_correct_passphrase():
    import admin_elevation
    from fake_runner import FakeRunner
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    store = admin_elevation.ElevationStore()
    result = sw.handle_admin_elevate(store, lambda p: p == "correct", sessions, token=session.token,
                                      passphrase="correct", now=1001.0)
    assert result.outcome == "applied"
    assert store.is_elevated(FakeRunner(), now=1001.0) is True


def test_admin_edit_requires_a_valid_session():
    import admin_elevation
    from fake_runner import FakeRunner
    sessions = sw.SessionStore()
    store = admin_elevation.ElevationStore()
    result = sw.handle_admin_edit(sessions, FakeRunner(), store, token="bogus",
                                   group="startup", key="auto_start_persona", value="admin", now=1000.0)
    assert result.outcome == "refused"
    assert result.status == 401


def test_admin_edit_refuses_without_an_elevation_ticket():
    import admin_elevation
    from fake_runner import FakeRunner
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    store = admin_elevation.ElevationStore()  # never elevated
    result = sw.handle_admin_edit(sessions, FakeRunner(), store, token=session.token,
                                   group="startup", key="auto_start_persona", value="admin", now=1001.0)
    assert result.outcome == "refused"
    assert result.status == 403


def test_admin_edit_applies_a_real_setting_once_elevated():
    import admin_elevation
    from fake_runner import FakeRunner
    import settings_store
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    store = admin_elevation.ElevationStore()
    store.grant(now=1001.0)
    runner = FakeRunner()
    result = sw.handle_admin_edit(sessions, runner, store, token=session.token,
                                   group="startup", key="auto_start_persona", value="admin", now=1001.0)
    assert result.outcome == "applied"
    assert settings_store.get_setting("startup", "auto_start_persona") == "admin"


def test_admin_edit_hands_off_an_unknown_setting_without_a_ticket_bypass():
    import admin_elevation
    from fake_runner import FakeRunner
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0)
    store = admin_elevation.ElevationStore()
    store.grant(now=1001.0)
    result = sw.handle_admin_edit(sessions, FakeRunner(), store, token=session.token,
                                   group="ghost", key="nope", value=1, now=1001.0)
    assert result.outcome == "handed_off"


# --------------------------------------------------------------------------
# Recovery mode's userless discovery view (work-queue item 26, decision
# record 81) - no session/token anywhere here, guest-tier by construction.
# --------------------------------------------------------------------------

def test_recovery_view_hands_off_when_no_runner_is_configured():
    result = sw.handle_recovery_view(None, personas=("admin", "personal"))
    assert result.outcome == "handed_off"


def test_recovery_view_needs_no_session_at_all():
    from fake_runner import FakeRunner
    result = sw.handle_recovery_view(FakeRunner(), personas=("admin", "personal"))
    assert result.outcome == "applied"
    assert result.body["personas_missing"] == ["admin", "personal"]


def test_recovery_view_reports_real_discovery_and_active_state():
    from fake_runner import FakeRunner
    import recovery_mode
    mounts = "/dev/sdb2 /mnt/USER_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    recovery_mode.record_entry(runner, now=1000.0, reason="cascade_failed")
    result = sw.handle_recovery_view(runner, personas=("admin", "personal"))
    assert result.body["personas_found"] == ["admin"]
    assert result.body["recovery_active"] is True


def test_recovery_exit_hands_off_when_no_runner_is_configured():
    result = sw.handle_recovery_exit(None, personas=("admin",), now=1000.0)
    assert result.outcome == "handed_off"


def test_recovery_exit_refuses_without_a_real_read_write_persona():
    from fake_runner import FakeRunner
    result = sw.handle_recovery_exit(FakeRunner(), personas=("admin",), now=1000.0)
    assert result.outcome == "refused"


def test_recovery_exit_succeeds_once_a_persona_is_confirmed_read_write():
    from fake_runner import FakeRunner
    mounts = "/dev/sdb2 /mnt/USER_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    result = sw.handle_recovery_exit(runner, personas=("admin",), now=1000.0)
    assert result.outcome == "applied"


def test_settings_view_without_a_persona_provider_ignores_persona_entirely():
    """A caller that never opts into persona-awareness (the pre-existing
    single-persona behavior) is fully unaffected, even for a session
    that itself has a recorded persona from an earlier login."""
    sessions = sw.SessionStore()
    session = sessions.create("root", now=1000.0, persona="admin")
    result = sw.handle_settings_view(sessions, FakeSource({"network": {}}), token=session.token, now=1001.0)
    assert result.outcome == "applied"


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
# Real default implementations (LocalAppStore-backed, decision record
# 91 - previously a single flat JSON file, JsonFileStore), exercised
# for real
# --------------------------------------------------------------------------

def test_file_backed_verifier_round_trips_a_real_sha512crypt_hash(tmp_path):
    store = sw.LocalAppStore(tmp_path / "store.db")
    store.add_user("alice", sw._sha512crypt("correct horse", sw._new_salt()))
    verifier = sw.FileBackedPasswordVerifier(store)
    assert verifier.verify("alice", "correct horse") is True
    assert verifier.verify("alice", "wrong") is False
    assert verifier.verify("nobody", "x") is False


def test_file_backed_elevation_verifier_accepts_the_real_dev_seed_passphrase(tmp_path):
    store = sw.LocalAppStore(tmp_path / "store.db")  # creates the store, seeding elevation_password_hash
    verifier = sw.FileBackedElevationVerifier(store)
    assert verifier("baseline-admin") is True
    assert verifier("baseline") is False  # the login password must not also work as elevation


def test_system_password_verifier_accepts_the_real_matching_password():
    entry_hash = sw._sha512crypt("correct horse", sw._new_salt())
    shadow_text = f"root:{entry_hash}:19000:0:99999:7:::\n"
    verifier = sw.SystemPasswordVerifier(read_text=lambda path: shadow_text)
    assert verifier.verify("root", "correct horse") is True
    assert verifier.verify("root", "wrong") is False


def test_system_password_verifier_refuses_an_unknown_username():
    verifier = sw.SystemPasswordVerifier(read_text=lambda path: "root:$6$abc$def:19000:0:99999:7:::\n")
    assert verifier.verify("nobody", "anything") is False


def test_system_password_verifier_refuses_cleanly_when_shadow_is_unreadable():
    def _raise(path):
        raise PermissionError("Permission denied")
    verifier = sw.SystemPasswordVerifier(read_text=_raise)
    assert verifier.verify("root", "anything") is False


def test_system_password_verifier_refuses_a_non_sha512_hash_scheme():
    verifier = sw.SystemPasswordVerifier(read_text=lambda path: "root:$y$j9T$abc$def:19000:0:99999:7:::\n")
    assert verifier.verify("root", "anything") is False


class _FakeSudoExecutor:
    """Matches subprocess.run's real call shape - never invokes real
    sudo or needs a real password."""
    def __init__(self, *, returncode=0):
        self.returncode = returncode
        self.calls = []

    def __call__(self, argv, *, input=b"", capture_output=True, timeout=10):
        self.calls.append((list(argv), input))
        import subprocess
        return subprocess.CompletedProcess(argv, self.returncode, b"", b"")


def test_sudo_password_verifier_accepts_when_the_real_sudo_preflight_succeeds():
    executor = _FakeSudoExecutor(returncode=0)
    verifier = sw.SudoPasswordVerifier(executor=executor)
    assert verifier.verify("cane", "whatever-the-real-password-is") is True
    assert executor.calls  # the real preflight genuinely ran


def test_sudo_password_verifier_refuses_when_the_real_sudo_preflight_fails():
    executor = _FakeSudoExecutor(returncode=1)
    verifier = sw.SudoPasswordVerifier(executor=executor)
    assert verifier.verify("cane", "wrong") is False


def test_sudo_password_verifier_ignores_username_and_checks_the_process_owner_only():
    """Real, stated behavior: `sudo -S` always authenticates whoever
    the process itself runs as, never the typed username - correct for
    this project's real multi-account-shares-one-password setup, not
    a per-username check this class pretends to do."""
    executor = _FakeSudoExecutor(returncode=0)
    verifier = sw.SudoPasswordVerifier(executor=executor)
    assert verifier.verify("Cliff", "the-shared-password") is True
    assert verifier.verify("cane", "the-shared-password") is True


def test_build_real_server_uses_the_real_sudo_password_verifier_for_login(tmp_path):
    server = sw.build_real_server(bind_port=0, data_path=tmp_path / "store.json")
    assert isinstance(server.deps["verifier"], sw.SudoPasswordVerifier)
    server.httpd.server_close()


def test_system_elevation_verifier_is_callable_with_just_a_password():
    entry_hash = sw._sha512crypt("correct horse", sw._new_salt())
    shadow_text = f"cane:{entry_hash}:19000:0:99999:7:::\n"
    verifier = sw.SystemElevationVerifier("cane", sw.SystemPasswordVerifier(read_text=lambda path: shadow_text))
    assert verifier("correct horse") is True
    assert verifier("wrong") is False


def test_system_elevation_verifier_checks_its_own_bound_username_only():
    entry_hash = sw._sha512crypt("correct horse", sw._new_salt())
    shadow_text = f"someoneelse:{entry_hash}:19000:0:99999:7:::\n"
    verifier = sw.SystemElevationVerifier("cane", sw.SystemPasswordVerifier(read_text=lambda path: shadow_text))
    assert verifier("correct horse") is False


def test_system_elevation_verifier_defaults_to_a_real_system_password_verifier():
    verifier = sw.SystemElevationVerifier("root")
    assert isinstance(verifier.verifier, sw.SystemPasswordVerifier)


def test_file_backed_elevation_verifier_refuses_when_no_hash_is_stored(tmp_path):
    # A freshly created store always seeds an elevation hash (its own
    # dev-only default) - to prove the "nothing stored" case for real,
    # remove that row directly rather than faking a pre-sqlite file
    # shape that no longer exists.
    store = sw.LocalAppStore(tmp_path / "store.db")
    store._conn.execute("DELETE FROM kv WHERE namespace = 'auth' AND key = 'elevation_password_hash'")
    store._conn.commit()
    verifier = sw.FileBackedElevationVerifier(store)
    assert verifier("anything") is False


def test_file_backed_applier_persists_across_a_new_store_instance(tmp_path):
    path = tmp_path / "store.db"
    store1 = sw.LocalAppStore(path)
    sw.FileBackedSectionApplier(store1).apply("firewall", {"allow_lan_only": False})

    store2 = sw.LocalAppStore(path)  # fresh instance, same file
    assert store2.settings()["firewall"]["allow_lan_only"] is False


def test_logging_rebuild_trigger_records_a_real_observable_entry(tmp_path):
    store = sw.LocalAppStore(tmp_path / "store.db")
    trigger = sw.LoggingRebuildTrigger(store, clock=lambda: 42.0)
    result = trigger.rebuild("/tmp/x.img", {"a": 1})
    assert result.applied is True
    assert store.rebuild_log() == [{"target": "/tmp/x.img", "config": {"a": 1}, "at": 42.0}]


def test_rebuild_log_preserves_order_across_multiple_real_entries(tmp_path):
    store = sw.LocalAppStore(tmp_path / "store.db")
    store.record_rebuild("/tmp/a.img", {}, 1.0)
    store.record_rebuild("/tmp/b.img", {}, 2.0)
    assert [r["target"] for r in store.rebuild_log()] == ["/tmp/a.img", "/tmp/b.img"]


def test_add_user_does_not_disturb_the_seeded_root_account(tmp_path):
    store = sw.LocalAppStore(tmp_path / "store.db")
    root_hash_before = store.get_user_hash("root")
    store.add_user("alice", sw._sha512crypt("x", sw._new_salt()))
    assert store.get_user_hash("root") == root_hash_before
    assert store.get_user_hash("alice") is not None


def test_update_section_only_touches_the_named_section(tmp_path):
    store = sw.LocalAppStore(tmp_path / "store.db")
    store.update_section("firewall", {"allow_lan_only": False})
    assert store.settings()["firewall"]["allow_lan_only"] is False
    assert store.settings()["ssh"]["password_auth"] is False  # untouched default


def test_resolve_data_path_defaults_to_tmp_when_env_unset():
    from pathlib import Path
    assert sw.resolve_data_path({}) == Path("/tmp/baseline-settings-web/store.db")


def test_resolve_data_path_honors_env_override():
    from pathlib import Path
    env = {"BASELINE_SETTINGS_WEB_DATA": "/var/lib/baseline/settings-web/store.json"}
    assert sw.resolve_data_path(env) == Path("/var/lib/baseline/settings-web/store.json")


def test_runner_backed_active_persona_provider_reuses_persist_bind_mounts_directly():
    from fake_runner import FakeRunner
    import persist_bind_mounts as pbm

    runner = FakeRunner(files={pbm.ACTIVE_PERSONA_MARKER_PATH: "personal"})
    provider = sw.RunnerBackedActivePersonaProvider(runner)
    assert provider.current_persona() == "personal"


def test_runner_backed_active_persona_provider_falls_back_to_the_same_default():
    from fake_runner import FakeRunner

    provider = sw.RunnerBackedActivePersonaProvider(FakeRunner())
    assert provider.current_persona() == "admin"


def test_build_real_server_without_a_runner_has_no_persona_provider(tmp_path):
    server = sw.build_real_server(bind_port=0, data_path=tmp_path / "store.json")
    try:
        assert server.deps["persona_provider"] is None
    finally:
        server.httpd.server_close()


def test_build_real_server_with_a_runner_wires_a_real_persona_provider(tmp_path):
    from fake_runner import FakeRunner

    server = sw.build_real_server(bind_port=0, data_path=tmp_path / "store.json", runner=FakeRunner())
    try:
        assert isinstance(server.deps["persona_provider"], sw.RunnerBackedActivePersonaProvider)
        assert server.deps["persona_provider"].current_persona() == "admin"
    finally:
        server.httpd.server_close()


def test_build_real_server_always_wires_a_real_elevation_verifier(tmp_path):
    server = sw.build_real_server(bind_port=0, data_path=tmp_path / "store.json")
    try:
        assert isinstance(server.deps["elevation_verify_fn"], sw.FileBackedElevationVerifier)
        assert server.deps["elevation_verify_fn"]("baseline-admin") is True
    finally:
        server.httpd.server_close()


def test_build_real_server_deps_include_a_fresh_elevation_store(tmp_path):
    import admin_elevation
    server = sw.build_real_server(bind_port=0, data_path=tmp_path / "store.json")
    try:
        assert isinstance(server.deps["elevation_store"], admin_elevation.ElevationStore)
    finally:
        server.httpd.server_close()


# --------------------------------------------------------------------------
# render_admin_page: a real smoke test, matching render_settings_page's own
# lack of dedicated tests (server-rendered HTML is otherwise verified via
# manual browser checks per this module's docstring) - just proving it
# doesn't crash and reflects real input.
# --------------------------------------------------------------------------

def test_render_admin_page_shows_settings_grouped_and_the_elevation_form_when_not_elevated():
    body = sw.render_admin_page({"startup": {"auto_start_persona": "personal"}}, elevated=False).decode()
    assert "startup" in body
    assert "auto_start_persona" in body
    assert "personal" in body
    assert "/admin/elevate" in body


def test_render_admin_page_omits_the_elevation_form_when_already_elevated():
    body = sw.render_admin_page({"startup": {"auto_start_persona": "personal"}}, elevated=True).decode()
    assert "/admin/elevate" not in body


# --------------------------------------------------------------------------
# render_field_input / reconstruct_typed_form_values: real typed form
# controls, never a raw JSON textarea for an ordinary scalar (direct
# feedback: "this is not a user experience").
# --------------------------------------------------------------------------

def test_render_field_input_renders_a_real_checkbox_for_a_bool():
    html = sw.render_field_input("dhcp", True)
    assert 'type="checkbox"' in html
    assert "checked" in html
    assert 'name="dhcp__type" value="bool"' in html


def test_render_field_input_unchecked_checkbox_for_false():
    html = sw.render_field_input("dhcp", False)
    assert 'type="checkbox"' in html
    assert html.count("checked") == 0


def test_render_field_input_renders_a_real_number_input_for_an_int():
    html = sw.render_field_input("default_session_ttl_hours", 24)
    assert 'type="number"' in html
    assert 'value="24"' in html
    assert 'step="1"' in html
    assert 'name="default_session_ttl_hours__type" value="int"' in html


def test_render_field_input_renders_text_for_a_string():
    html = sw.render_field_input("hostname", "baseline")
    assert 'type="text"' in html
    assert 'value="baseline"' in html


def test_render_field_input_renders_a_dropdown_when_options_given():
    html = sw.render_field_input("baseline_mode", "read-only", options=["read-write", "read-only", "write-only"])
    assert "<select" in html
    assert '<option value="read-only" selected>' in html
    assert '<option value="read-write" >' in html


def test_render_field_input_falls_back_to_a_raw_json_textarea_only_for_nested_values():
    html = sw.render_field_input("restored_categories", ["network", "firewall"])
    assert "<textarea" in html
    assert "network" in html


def test_reconstruct_typed_form_values_true_when_checkbox_present():
    form = {"dhcp": "true", "dhcp__type": "bool"}
    assert sw.reconstruct_typed_form_values(form, ["dhcp"]) == {"dhcp": True}


def test_reconstruct_typed_form_values_false_when_checkbox_absent():
    """An unchecked checkbox simply isn't submitted at all - standard
    HTML form behavior - so absence must mean False, not "no change"."""
    form = {"dhcp__type": "bool"}
    assert sw.reconstruct_typed_form_values(form, ["dhcp"]) == {"dhcp": False}


def test_reconstruct_typed_form_values_casts_int_and_float_correctly():
    form = {"ttl__type": "int", "ttl": "12", "ratio__type": "float", "ratio": "0.5"}
    result = sw.reconstruct_typed_form_values(form, ["ttl", "ratio"])
    assert result == {"ttl": 12, "ratio": 0.5}
    assert isinstance(result["ttl"], int)
    assert isinstance(result["ratio"], float)


def test_reconstruct_typed_form_values_real_round_trip_through_render_field_input():
    """The two halves genuinely agree with each other - render a real
    field, simulate submitting it unchanged, get the same real value
    back, for every type this app actually uses."""
    for name, value in [("dhcp", True), ("hostname", "baseline"), ("ttl", 24), ("ratio", 1.5)]:
        rendered = sw.render_field_input(name, value)
        # Simulate the browser's own submission: a checked checkbox
        # sends name=true; everything else sends its real value.
        form = {f"{name}__type": ("bool" if isinstance(value, bool) else
                                   "int" if isinstance(value, int) else
                                   "float" if isinstance(value, float) else "str")}
        if isinstance(value, bool):
            if value:
                form[name] = "true"
        else:
            form[name] = str(value)
        assert sw.reconstruct_typed_form_values(form, [name]) == {name: value}


def test_render_recovery_page_shows_real_discovery_and_no_login_form():
    body = sw.render_recovery_page({
        "personas_found": ["admin"], "personas_missing": ["personal"],
        "active_persona": "admin", "recovery_active": True,
    }).decode()
    assert "admin" in body
    assert "personal" in body
    assert "ACTIVE" in body
    assert "password" not in body.lower()  # userless - no credential form anywhere on this page


def test_render_recovery_page_shows_the_exit_button_only_when_recovery_mode_is_active():
    body = sw.render_recovery_page({
        "personas_found": ["admin"], "personas_missing": [],
        "active_persona": "admin", "recovery_active": True,
    }).decode()
    assert "Attempt to leave recovery mode" in body


def test_render_recovery_page_hides_the_exit_button_when_recovery_mode_is_not_active():
    """Showing "leave recovery mode" when it isn't active implies
    there's something to leave - there isn't, so the control shouldn't
    be there at all."""
    body = sw.render_recovery_page({
        "personas_found": [], "personas_missing": ["admin", "personal"],
        "active_persona": None, "recovery_active": False,
    }).decode()
    assert "Attempt to leave recovery mode" not in body
    assert "not active" in body


def test_render_recovery_page_handles_the_handed_off_case_without_crashing():
    body = sw.render_recovery_page({}, "no Runner configured").decode()
    assert "not available" in body


# ---------------------------------------------------------------------------
# export_install_config round-trip tests
# ---------------------------------------------------------------------------

def test_export_install_config_maps_all_settings_sections():
    store_settings = dict(sw._DEFAULT_SETTINGS_SECTIONS)
    store_settings["proxmox"] = sw._DEFAULT_SETTINGS_SECTIONS["proxmox"]
    store_settings["drivers"] = sw._DEFAULT_SETTINGS_SECTIONS["drivers"]
    config = sw.export_install_config(store_settings)
    assert "network" in config
    assert "firewall" in config
    assert "ssh" in config
    assert "tether" in config
    assert "handoff" in config
    assert "proxmox" in config
    assert "drivers" in config


def test_export_install_config_preserves_network_values():
    settings = {"network": {"hostname": "testhost", "dhcp": False}}
    config = sw.export_install_config(settings)
    assert config["network"]["hostname"] == "testhost"
    assert config["network"]["dhcp"] is False


def test_export_install_config_extracts_iperf3_values_from_diagnostics():
    settings = {
        "diagnostics": {
            "iperf3": {"role": "server", "peer_address": "10.0.0.5", "port": 9999},
        }
    }
    config = sw.export_install_config(settings)
    assert config["diagnostics"]["iperf3"]["role"] == "server"
    assert config["diagnostics"]["iperf3"]["peer_address"] == "10.0.0.5"
    assert config["diagnostics"]["iperf3"]["port"] == 9999


def test_export_install_config_skips_empty_sections():
    config = sw.export_install_config({})
    assert config == {}


def test_export_install_config_round_trips_through_config_pipeline():
    """The real integration test: Configurator defaults → export →
    config_pipeline can process them without errors."""
    import json
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "baseline", "lib"))
    import config_pipeline as cp
    from fake_runner import FakeRunner

    store_settings = dict(sw._DEFAULT_SETTINGS_SECTIONS)
    store_settings["proxmox"] = sw._DEFAULT_SETTINGS_SECTIONS["proxmox"]
    store_settings["drivers"] = sw._DEFAULT_SETTINGS_SECTIONS["drivers"]
    exported = sw.export_install_config(store_settings)

    runner = FakeRunner(files={
        "/etc/baseline/install-config.json": json.dumps(exported),
        "/etc/ssh/sshd_config": "# default config\n",
    })
    config = cp.load_config(runner)
    summary = cp.apply_stored_config(runner, config, network_interface="eno1")

    all_named = set(summary["applied"] + summary["skipped"] + summary["failed"])
    expected = {"network", "firewall", "ssh", "tether", "handoff",
                "smartd", "ethtool", "iperf3", "cpu_microcode", "wifi_firmware"}
    assert expected == all_named
    assert summary["failed"] == []


# --- stored secrets: verifiable as a match, never recoverable -------------

def test_hashes_match_only_on_equal_hashes():
    assert sw._hashes_match("$6$salt$abc", "$6$salt$abc") is True
    assert sw._hashes_match("$6$salt$abc", "$6$salt$abd") is False
    assert sw._hashes_match("", "$6$salt$abc") is False


def test_hash_comparison_is_constant_time():
    import inspect
    src = inspect.getsource(sw._hashes_match)
    assert "compare_digest" in src


def test_a_stored_secret_hash_does_not_contain_the_secret_and_cannot_be_reversed_by_the_verifier(tmp_path):
    store = sw.LocalAppStore(tmp_path / "s.db")
    store.add_user("alice", sw._sha512crypt("correct horse", "abcdefgh"))
    stored = store.get_user_hash("alice")
    assert "correct horse" not in stored and stored.startswith("$6$abcdefgh$")
    verifier = sw.FileBackedPasswordVerifier(store)
    assert verifier.verify("alice", "correct horse") is True
    assert verifier.verify("alice", "wrong") is False
