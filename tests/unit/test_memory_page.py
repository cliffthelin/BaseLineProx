"""The host swap setting from the browser (operator 2026-10-16). Real HTTP server and session; the host is the simulated one from test_swap_config."""
import json
import os

import pytest

import layered_settings as ls
from test_baseline_web import _RealServerCase, _base_deps
from test_new_web_routes import req
from test_swap_config import GIB, VG, World

AUDIT = []


@pytest.fixture
def case(tmp_path):
    made = [tmp_path / n for n in ("admin", "user", "appdata", "session")]
    for p in made:
        p.mkdir()
    world = World(active={"/mnt/SESSION_TEMP/swapfile": 4 * GIB}, files={"/mnt/SESSION_TEMP/swapfile"}, fstab="/mnt/SESSION_TEMP/swapfile none swap sw 0 0\n")
    AUDIT.clear()
    c = _RealServerCase(_base_deps(launcher_roots=ls.Roots(*map(str, made)), swap_runner=world, swap_vg=VG, swap_ensure_room=lambda *a: None,
                                   audit=AUDIT.append))
    c.tmp, c.world = tmp_path, world
    yield c
    c.close()


def test_the_page_needs_a_session_and_shows_the_current_swap_and_both_kinds(case):
    assert req(case, "GET", "/memory", cookie=False)[0] == 303
    status, _, page = req(case, "GET", "/memory")
    assert status == 200 and "4 GiB" in page and "file" in page
    assert 'value="file"' in page and 'value="reserved"' in page and 'name="gib"' in page and 'name="confirm"' in page
    assert "nothing is written" in page.lower()                  # what the reserved choice means is said where it is chosen
    assert "Launcher" in page                                      # where a VM's or container's own swap is set


def test_choosing_a_reserved_swap_applies_it_and_records_it_on_user_admin(case):
    status, location, _ = req(case, "POST", "/memory/swap", {"gib": "8", "kind": "reserved", "confirm": "yes"})
    assert status == 303 and location.startswith("/memory?notice=")
    assert f"/dev/{VG}/baseline_swap_8g" in case.world.active and not any(c[0] == "dd" for c in case.world.log)
    assert json.load(open(os.path.join(case.tmp, "admin", "settings", "shared.json"))) == {"host_swap_gib": 8, "host_swap_kind": "reserved"}
    assert any(e.get("event") == "host_swap_changed" and e["gib"] == 8 and e["kind"] == "reserved" for e in AUDIT)


def test_nothing_changes_without_the_confirmation_or_with_a_bad_value(case):
    for fields in ({"gib": "8", "kind": "reserved"}, {"gib": "99", "kind": "file", "confirm": "yes"}, {"gib": "x", "kind": "file", "confirm": "yes"},
                   {"gib": "4", "kind": "zeroed", "confirm": "yes"}):
        status, location, _ = req(case, "POST", "/memory/swap", fields)
        assert status == 303 and location.startswith("/memory?notice="), fields
    assert list(case.world.active) == ["/mnt/SESSION_TEMP/swapfile"] and not os.path.exists(os.path.join(case.tmp, "admin", "settings"))


def test_a_failure_is_shown_and_not_recorded_as_the_setting(case):
    case.world.fail.add("lvcreate")
    status, location, _ = req(case, "POST", "/memory/swap", {"gib": "8", "kind": "reserved", "confirm": "yes"})
    assert status == 303 and "insufficient" in location.replace("+", " ")
    assert not os.path.exists(os.path.join(case.tmp, "admin", "settings"))


def test_the_swap_change_needs_a_session(case):
    assert req(case, "POST", "/memory/swap", {"gib": "8", "kind": "file", "confirm": "yes"}, cookie=False)[0] in (303, 401)
    assert list(case.world.active) == ["/mnt/SESSION_TEMP/swapfile"]


def test_the_page_is_linked_from_the_navigation_and_home(case):
    assert 'href="/memory"' in req(case, "GET", "/hardware")[2] and 'href="/memory"' in req(case, "GET", "/home")[2]
