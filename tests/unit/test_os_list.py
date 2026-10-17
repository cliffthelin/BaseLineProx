"""The operator's list of operating systems stays the operator's: git-ignored, on USER_ADMIN on the host, checked once when read."""
import json
import subprocess
from pathlib import Path

import pytest

import os_list

REPO = Path(__file__).resolve().parents[2]


def listing(*rows):
    return json.dumps({"os": list(rows)})


def test_a_good_list_is_read_with_defaults_filled_in():
    rows = os_list.parse(listing({"id": "fedora", "name": "Fedora"}, {"id": "kasm", "name": "Kasm", "kind": "kasm", "iso": "x.iso"}))
    assert rows[0] == {"id": "fedora", "name": "Fedora", "kind": "vm", "iso": None, "apps": list(os_list.APPS), "workspaces": None, "notes": ""} and rows[1]["kind"] == "kasm"


@pytest.mark.parametrize("bad,why", [
    ({"id": "Bad Id", "name": "x"}, "id must be"), ({"id": "a"}, "name is required"), ({"id": "a", "name": "x", "kind": "lxd"}, "kind must be"),
    ({"id": "a", "name": "x", "iso": "../etc/passwd"}, "not a path"), ({"id": "a", "name": "x", "notes": "n" * 301}, "notes"), ("text", "not an object")])
def test_a_bad_entry_is_refused_with_the_reason(bad, why):
    with pytest.raises(os_list.OsListError, match=why):
        os_list.parse(listing(bad))


def test_a_duplicate_or_malformed_list_is_refused():
    with pytest.raises(os_list.OsListError, match="twice"):
        os_list.parse(listing({"id": "a", "name": "A"}, {"id": "a", "name": "B"}))
    for text in ("not json", "[]", '{"os": 3}'):
        with pytest.raises(os_list.OsListError):
            os_list.parse(text)


def test_with_no_list_nothing_is_assumed(tmp_path):
    assert os_list.locate(environ={}, host=tmp_path / "a", repo=tmp_path / "b") is None


def test_the_list_is_found_in_the_stated_order(tmp_path):
    host, repo, named = tmp_path / "host.json", tmp_path / "repo.json", tmp_path / "named.json"
    repo.write_text("{}")
    assert os_list.locate(environ={}, host=host, repo=repo) == repo
    host.write_text("{}")
    assert os_list.locate(environ={}, host=host, repo=repo) == host
    named.write_text("{}")
    assert os_list.locate(environ={"BASELINE_OS_LIST": str(named)}, host=host, repo=repo) == named


def test_the_working_copy_is_git_ignored_and_nothing_under_it_is_tracked():
    ignored = subprocess.run(["git", "check-ignore", "-q", "config/local/supported-os.json"], cwd=REPO)
    assert ignored.returncode == 0
    tracked = subprocess.run(["git", "ls-files", "config/local"], cwd=REPO, capture_output=True, text=True).stdout
    assert tracked.strip() == ""


def test_the_committed_example_is_valid_and_says_where_the_real_one_goes():
    text = (REPO / "config/supported-os.example.json").read_text()
    assert os_list.parse(text) and "config/local/supported-os.json" in text
    assert subprocess.run(["git", "check-ignore", "-q", "config/supported-os.example.json"], cwd=REPO).returncode == 1       # the example IS committed


def test_the_host_keeps_its_copy_on_user_admin():
    assert str(os_list.HOST_COPY).startswith("/mnt/USER_ADMIN/")


def test_apps_default_to_the_five_and_a_kasm_entry_has_none():
    rows = os_list.parse(listing({"id": "a", "name": "A"}, {"id": "k", "name": "K", "kind": "kasm"}, {"id": "b", "name": "B", "apps": ["chrome"]}))
    assert rows[0]["apps"] == list(os_list.APPS) and rows[1]["apps"] == [] and rows[2]["apps"] == ["chrome"]


def test_an_unknown_or_repeated_app_is_refused():
    for apps in (["notepad"], ["chrome", "chrome"], "chrome"):
        with pytest.raises(os_list.OsListError, match="apps must be"):
            os_list.parse(listing({"id": "a", "name": "A", "apps": apps}))


def test_the_apps_are_the_five_the_environments_catalogue_knows():
    import environments
    assert tuple(os_list.APPS) == tuple(environments.APPS)


WS = {"key": "browser", "image": "chrome", "friendly_name": "Browser", "persistent": True}


def test_a_kasm_entry_may_name_its_workspaces_and_others_may_not():
    rows = os_list.parse(listing({"id": "k", "name": "K", "kind": "kasm", "workspaces": [WS]}))
    assert rows[0]["workspaces"] == [WS]
    assert os_list.parse(listing({"id": "k", "name": "K", "kind": "kasm"}))[0]["workspaces"] is None
    with pytest.raises(os_list.OsListError, match="only a kasm entry"):
        os_list.parse(listing({"id": "a", "name": "A", "workspaces": [WS]}))


@pytest.mark.parametrize("bad", [[], [{"key": "X", "image": "chrome", "friendly_name": "B", "persistent": True}],
                                 [dict(WS, persistent="yes")], [WS, dict(WS, friendly_name="Other")], [WS, dict(WS, key="two")], [dict(WS, friendly_name="")]])
def test_bad_workspace_definitions_are_refused(bad):
    with pytest.raises(os_list.OsListError):
        os_list.parse(listing({"id": "k", "name": "K", "kind": "kasm", "workspaces": bad}))
