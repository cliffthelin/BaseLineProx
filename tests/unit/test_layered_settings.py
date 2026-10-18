"""Settings shared from one OS to the next, layered, stored only on the volumes that may hold non-public data (DR259).

Real files in a temp directory, no fakes: the store is plain file I/O, so the tests exercise exactly what runs on the drive. The four
roots stand in for USER_ADMIN, USER_<PERSONA>, APPDATA_<PERSONA> and SESSION_TEMP."""
import json
import os
import stat

import pytest

import layered_settings as ls

OS_A = "O_V_00001"
OS_B = "O_V_00002"
APP = "A_D_00007"


@pytest.fixture
def roots(tmp_path):
    made = {name: tmp_path / name for name in ("admin", "user", "appdata", "session")}
    for p in made.values():
        p.mkdir()
    return ls.Roots(**{k: str(v) for k, v in made.items()})


def test_the_default_roots_are_the_four_allowed_volumes_of_the_persona():
    r = ls.default_roots("personal")
    assert (r.admin, r.user, r.appdata, r.session) == ("/mnt/USER_ADMIN", "/mnt/USER_PERSONAL", "/mnt/APPDATA_PERSONAL", "/mnt/SESSION_TEMP")


def test_a_setting_shared_by_the_user_reaches_every_os(roots):
    ls.write_layer(roots, "user", {"timezone": "America/Denver", "theme": "dark"})
    for os_id in (OS_A, OS_B):
        eff = ls.effective_os(roots, os_id)
        assert eff["timezone"] == "America/Denver" and eff["theme"] == "dark"


def test_the_order_is_admin_then_user_then_os_and_the_later_layer_wins(roots):
    ls.write_layer(roots, "admin", {"locale": "en_US.UTF-8", "theme": "light", "keyboard": "us"}, actor="admin")
    ls.write_layer(roots, "user", {"theme": "dark"})
    ls.write_layer(roots, "os", {"keyboard": "de"}, os_id=OS_A)
    a, b = ls.effective_os(roots, OS_A), ls.effective_os(roots, OS_B)
    assert (a["locale"], a["theme"], a["keyboard"]) == ("en_US.UTF-8", "dark", "de")
    assert b["keyboard"] == "us"                     # the difference belongs to OS_A alone


def test_an_application_inherits_its_os_and_adds_its_own_settings(roots):
    ls.write_layer(roots, "user", {"theme": "dark"})
    ls.write_layer(roots, "app", {"enabled": True, "autostart": False}, os_id=OS_A, app_id=APP)
    eff = ls.effective_app(roots, OS_A, APP)
    assert eff["theme"] == "dark" and eff["enabled"] is True and eff["autostart"] is False
    assert "enabled" not in ls.effective_os(roots, OS_A)
    assert "enabled" not in ls.effective_app(roots, OS_B, APP)       # the same app in another OS has its own settings


def test_each_layer_is_written_only_to_its_own_volume(roots, tmp_path):
    ls.write_layer(roots, "admin", {"theme": "dark"}, actor="admin")
    ls.write_layer(roots, "user", {"theme": "dark"})
    ls.write_layer(roots, "os", {"theme": "dark"}, os_id=OS_A)
    ls.write_layer(roots, "app", {"enabled": True}, os_id=OS_A, app_id=APP)
    ls.write_layer(roots, "session", {"default_run_mode": "window"})
    files = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*.json"))
    assert files == sorted([
        "admin/settings/shared.json", "user/settings/shared.json", f"user/settings/os/{OS_A}.json",
        f"appdata/{APP}/os/{OS_A}.json", "session/launcher/session.json"])


def test_the_admin_layer_is_writable_only_by_an_administrator(roots):
    with pytest.raises(ls.SettingsError, match="administrator"):
        ls.write_layer(roots, "admin", {"theme": "dark"})
    with pytest.raises(ls.SettingsError, match="administrator"):
        ls.write_layer(roots, "admin", {"theme": "dark"}, actor="person")
    assert ls.read_layer(roots, "admin") == {}


@pytest.mark.parametrize("key,value", [
    ("timezone", "../../etc/passwd"), ("timezone", "Mars/Olympus; reboot"), ("locale", "english"), ("keyboard", "us;rm"),
    ("theme", "neon"), ("display_scale", 130), ("default_run_mode", "rdp"), ("hostname", "x"), ("password", "hunter2"),
])
def test_unknown_keys_and_malformed_values_are_refused_and_nothing_is_written(roots, key, value):
    with pytest.raises(ls.SettingsError):
        ls.write_layer(roots, "user", {key: value})
    assert ls.read_layer(roots, "user") == {}


def test_application_keys_belong_to_the_app_layer_only(roots):
    with pytest.raises(ls.SettingsError):
        ls.write_layer(roots, "user", {"enabled": True})
    with pytest.raises(ls.SettingsError):
        ls.write_layer(roots, "app", {"theme": "dark"}, os_id=OS_A, app_id=APP)


def test_entities_are_named_by_constant_identifiers_never_by_name(roots):
    for bad_os in ("ubuntu", "../O_V_00001", "O_V_1", "A_D_00007", "O_V_00001/../x"):
        with pytest.raises(ls.SettingsError):
            ls.write_layer(roots, "os", {"theme": "dark"}, os_id=bad_os)
    for bad_app in ("chrome", "O_V_00001", "../A_D_00007"):
        with pytest.raises(ls.SettingsError):
            ls.write_layer(roots, "app", {"enabled": True}, os_id=OS_A, app_id=bad_app)


def test_a_layer_that_resolves_outside_its_volume_is_refused(roots, tmp_path):
    elsewhere = tmp_path / "substrate"
    elsewhere.mkdir()
    os.symlink(elsewhere, os.path.join(roots.user, "settings"))       # a link out of the volume, to the disposable side
    with pytest.raises(ls.SettingsError, match="outside"):
        ls.write_layer(roots, "user", {"theme": "dark"})
    assert list(elsewhere.iterdir()) == []


def test_a_missing_volume_is_refused_not_created(tmp_path):
    gone = ls.Roots(admin=str(tmp_path / "x1"), user=str(tmp_path / "x2"), appdata=str(tmp_path / "x3"), session=str(tmp_path / "x4"))
    with pytest.raises(ls.SettingsError, match="not mounted|does not exist"):
        ls.write_layer(gone, "user", {"theme": "dark"})
    assert list(tmp_path.iterdir()) == []                 # writing through to the substrate is exactly what this must never do


def test_a_corrupt_file_is_an_error_never_silently_empty(roots):
    ls.write_layer(roots, "user", {"theme": "dark"})
    path = os.path.join(roots.user, "settings", "shared.json")
    with open(path, "w") as f:
        f.write("{not json")
    with pytest.raises(ls.SettingsError, match="unreadable"):
        ls.read_layer(roots, "user")
    with pytest.raises(ls.SettingsError):
        ls.effective_os(roots, OS_A)


def test_a_file_with_an_unknown_key_is_reported_not_trusted(roots):
    ls.write_layer(roots, "user", {"theme": "dark"})
    path = os.path.join(roots.user, "settings", "shared.json")
    with open(path, "w") as f:
        json.dump({"theme": "dark", "shell_command": "x"}, f)
    with pytest.raises(ls.SettingsError, match="shell_command"):
        ls.read_layer(roots, "user")


def test_files_are_private_and_written_atomically(roots):
    ls.write_layer(roots, "user", {"theme": "dark"})
    path = os.path.join(roots.user, "settings", "shared.json")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert [n for n in os.listdir(os.path.dirname(path)) if n.endswith(".tmp")] == []


def test_a_change_merges_with_what_is_there_and_none_removes_a_key(roots):
    ls.write_layer(roots, "user", {"theme": "dark", "locale": "en_US.UTF-8"})
    ls.write_layer(roots, "user", {"theme": "light"})
    assert ls.read_layer(roots, "user") == {"theme": "light", "locale": "en_US.UTF-8"}
    ls.write_layer(roots, "user", {"theme": None})
    assert ls.read_layer(roots, "user") == {"locale": "en_US.UTF-8"}


def test_on_the_drive_a_directory_that_is_not_a_mount_is_refused(tmp_path):
    plain = {n: tmp_path / n for n in ("a", "b", "c", "d")}
    for p in plain.values():
        p.mkdir()
    strict = ls.Roots(str(plain["a"]), str(plain["b"]), str(plain["c"]), str(plain["d"]), require_mount=True)
    with pytest.raises(ls.SettingsError, match="not mounted"):
        ls.write_layer(strict, "user", {"theme": "dark"})
    assert list(plain["b"].iterdir()) == []


def test_reading_a_volume_that_is_not_there_is_empty_not_an_error(tmp_path):
    gone = ls.Roots(str(tmp_path / "1"), str(tmp_path / "2"), str(tmp_path / "3"), str(tmp_path / "4"))
    assert ls.read_layer(gone, "user") == {}


def test_each_effective_value_says_which_layer_it_came_from(roots):
    ls.write_layer(roots, "admin", {"locale": "en_US.UTF-8", "theme": "light"}, actor="admin")
    ls.write_layer(roots, "user", {"theme": "dark"})
    ls.write_layer(roots, "os", {"keyboard": "de"}, os_id=OS_A)
    ls.write_layer(roots, "app", {"enabled": True}, os_id=OS_A, app_id=APP)
    os_view = ls.explain_os(roots, OS_A)
    assert os_view["locale"] == {"value": "en_US.UTF-8", "source": "admin"}
    assert os_view["theme"] == {"value": "dark", "source": "user"}
    assert os_view["keyboard"] == {"value": "de", "source": "os"}
    assert "timezone" not in os_view                                    # unset everywhere: absent, never invented
    app_view = ls.explain_app(roots, OS_A, APP)
    assert app_view["enabled"] == {"value": True, "source": "app"} and app_view["theme"]["source"] == "user"


# --- swap (operator 2026-10-16: swap is a setting the user can change) ---------------------------------------------------------------

@pytest.mark.parametrize("value", [0, 256, 512, 1024, 2048, 4096, 8192, 16384])
def test_a_guests_swap_size_is_one_of_the_offered_sizes(roots, value):
    ls.write_layer(roots, "user", {"swap_mb": value})
    assert ls.effective_os(roots, OS_A)["swap_mb"] == value


@pytest.mark.parametrize("value", [-1, 100, 3000, 10**9, "1024", True, 1.5])
def test_other_swap_sizes_are_refused(roots, value):
    with pytest.raises(ls.SettingsError):
        ls.write_layer(roots, "user", {"swap_mb": value})


def test_swap_can_differ_per_os_and_inherits_otherwise(roots):
    ls.write_layer(roots, "user", {"swap_mb": 2048})
    ls.write_layer(roots, "os", {"swap_mb": 0}, os_id=OS_A)
    assert ls.effective_os(roots, OS_A)["swap_mb"] == 0 and ls.effective_os(roots, OS_B)["swap_mb"] == 2048


def test_the_hosts_own_swap_is_an_admin_setting_and_cannot_be_set_for_a_guest(roots):
    ls.write_layer(roots, "admin", {"host_swap_gib": 8, "host_swap_kind": "reserved"}, actor="admin")
    assert ls.read_layer(roots, "admin") == {"host_swap_gib": 8, "host_swap_kind": "reserved"}
    for layer in ("user", "session"):
        with pytest.raises(ls.SettingsError):
            ls.write_layer(roots, layer, {"host_swap_gib": 8})
    with pytest.raises(ls.SettingsError):
        ls.write_layer(roots, "os", {"host_swap_kind": "file"}, os_id=OS_A)


@pytest.mark.parametrize("key,value", [("host_swap_gib", -1), ("host_swap_gib", 65), ("host_swap_gib", "8"), ("host_swap_gib", True),
                                       ("host_swap_kind", "zeroed"), ("host_swap_kind", "")])
def test_bad_host_swap_values_are_refused(roots, key, value):
    with pytest.raises(ls.SettingsError):
        ls.write_layer(roots, "admin", {key: value}, actor="admin")
    assert ls.read_layer(roots, "admin") == {}


def test_host_only_settings_never_leak_into_what_a_guest_receives(roots):
    ls.write_layer(roots, "admin", {"theme": "dark", "host_swap_gib": 8, "host_swap_kind": "reserved"}, actor="admin")
    assert ls.effective_os(roots, OS_A) == {"theme": "dark"}
    assert set(ls.explain_os(roots, OS_A)) == {"theme"} and set(ls.effective_app(roots, OS_A, APP)) == {"theme"}


def test_read_refuses_unmounted_storage_even_if_a_stale_settings_file_exists(roots):
    ls.write_layer(roots, "user", {"theme": "dark"})
    mounted_roots = roots._replace(require_mount=True)
    with pytest.raises(ls.SettingsError, match="not mounted"):
        ls.read_layer(mounted_roots, "user")


def test_read_reports_missing_storage_instead_of_empty_settings(roots, tmp_path):
    missing_roots = roots._replace(user=str(tmp_path / "absent-volume"), require_mount=True)
    with pytest.raises(ls.SettingsError, match="not mounted"):
        ls.read_layer(missing_roots, "user")
