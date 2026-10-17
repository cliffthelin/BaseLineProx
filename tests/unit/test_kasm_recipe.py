"""The Kasm recipe: decisions written down, checked against what the Kasm release itself starts (DR260)."""
import json

import pytest

import kasm_build as kb
import kasm_recipe as kr

# the images 1.19.0's own docker-compose-all.yaml starts (read from the release, 2026-10-17)
COMPOSE = """
services:
  db: {image: "kasmweb/postgres:1.19.0-rolling"}
  kasm_api: {image: "kasmweb/api:1.19.0-rolling"}
  kasm_manager: {image: "kasmweb/manager:1.19.0-rolling"}
  kasm_agent: {image: "kasmweb/agent:1.19.0-rolling"}
  kasm_guac: {image: "kasmweb/kasm-guac:1.19.0-rolling"}
  rdp_gateway: {image: "kasmweb/rdp-gateway:1.19.0-rolling"}
  kasm_rdp_https_gateway: {image: "kasmweb/rdp-https-gateway:1.19.0-rolling"}
  proxy: {image: "kasmweb/proxy:1.19.0-rolling"}
"""


def recipe():
    return kr.default(kb.WORKSPACES)


def test_the_default_recipe_covers_exactly_the_images_the_release_starts():
    assert kr.validate(recipe(), kr.compose_images(COMPOSE))
    assert sorted(kr.service_images(recipe())) == sorted(kr.compose_images(COMPOSE))
    assert set(kb.SERVICE_IMAGES) == set(kr.compose_images(COMPOSE))               # what the build carries comes from the recipe


def test_the_defaults_record_what_this_setup_does_not_use():
    states = {c["id"]: c["state"] for c in recipe()["components"]}
    assert states["server-connections"] == "unused" and states["database"] == "required" and states["agent"] == "required"
    notes = {c["id"]: c["note"] for c in recipe()["components"]}
    assert "installing the roles separately" in notes["server-connections"]          # what dropping it would take is written next to it
    assert {p["id"]: p["state"] for p in recipe()["plugins"]} == {"logging": "required", "network": "unused"}


def test_a_new_release_component_must_be_given_a_state_before_it_can_be_built():
    newer = COMPOSE + '  kasm_new_thing: {image: "kasmweb/new-thing:1.20.0"}\n'
    with pytest.raises(kr.RecipeError, match="gives no state: new-thing"):
        kr.validate(recipe(), kr.compose_images(newer))


def test_a_component_the_release_does_not_start_is_refused():
    r = recipe()
    r["components"][0]["images"].append("ghost")
    with pytest.raises(kr.RecipeError, match="does not start: ghost"):
        kr.validate(r, kr.compose_images(COMPOSE))


@pytest.mark.parametrize("change,why", [
    (lambda r: r["components"][0].update(state="optional"), "state must be one of"),
    (lambda r: r["components"][0].update(role="web"), "role must be one of"),
    (lambda r: r["components"][0].update(state="unused"), "cannot be unused"),
    (lambda r: r["components"][1].update(id="database"), "listed twice"),
    (lambda r: r["components"][1]["images"].append("postgres"), "belongs to both"),
    (lambda r: r["components"][0].update(images=[]), "images must be"),
    (lambda r: r["components"][0].update(id="Bad Id"), "needs an id"),
    (lambda r: r["components"][0].update(note="x" * 401), "note is text"),
    (lambda r: r.update(format="other/v1"), "has format"),
    (lambda r: r.update(workspaces=[]), "lists its workspaces"),
    (lambda r: r["plugins"][0].update(tag="latest"), "plugin needs"),
])
def test_a_bad_recipe_is_refused_with_the_reason(change, why):
    r = recipe()
    change(r)
    with pytest.raises(kr.RecipeError, match=why):
        kr.validate(r)


def test_the_recipe_is_found_in_the_stated_order_and_a_bad_file_is_refused(tmp_path):
    custom = recipe()
    custom["components"][4]["note"] = "mine"
    named, working = tmp_path / "named.json", tmp_path / "working.json"
    working.write_text(json.dumps(custom))
    assert kr.locate({}, repo=tmp_path / "none.json") is None and kr.locate({}, repo=working) == working
    named.write_text("{}")
    assert kr.locate({"BASELINE_KASM_RECIPE": str(named)}, repo=working) == named
    assert kr.load(kb.WORKSPACES, working)["components"][4]["note"] == "mine"
    with pytest.raises(kr.RecipeError, match="cannot be read|has format"):
        kr.load(kb.WORKSPACES, named)
    named.write_text("not json")
    with pytest.raises(kr.RecipeError, match="cannot be read"):
        kr.load(kb.WORKSPACES, named)


def test_the_os_lists_kasm_entry_chooses_the_workspaces_over_the_recipes():
    chosen = [{"key": "browser", "image": "chrome", "friendly_name": "Browser", "persistent": True}]
    got = kb.recipe_for([{"kind": "vm"}, {"kind": "kasm", "workspaces": chosen}], recipe_path=None)
    assert got["workspaces"] == chosen and len(got["components"]) == 5
    assert kb.recipe_for([], recipe_path=None)["workspaces"] == [dict(w) for w in kb.WORKSPACES]


def test_the_plugins_the_build_packs_come_from_the_recipe_and_an_unknown_one_is_refused():
    script = kb.prepare_script(["kasmweb/api:1.19.0"], [], recipe()["plugins"])
    assert '"kasmweb/logger kasmweb/kasm-logging-plugin amd64-1.1"' in script and '"kasmweb/sidecar kasmweb/kasm-network-plugin amd64-1.5"' in script
    newer = [dict(recipe()["plugins"][0], tag="1.2")]
    assert "amd64-1.2" in kb.prepare_script([], [], newer)
    with pytest.raises(kb.KasmBuildError, match="does not know how to pack: telemetry"):
        kb.prepare_script([], [], [{"id": "telemetry", "image": "x/y", "tag": "1", "state": "used"}])


def test_the_summary_is_what_a_host_needs_and_carries_no_workspaces_or_images_of_the_user():
    summary = kr.summary(recipe())
    assert [c["id"] for c in summary["components"]] == ["database", "application", "agent", "proxy", "server-connections"]
    assert set(summary) == {"components", "plugins", "settings", "registry"} and summary["settings"] == {} and summary["registry"]["enabled"] is False


def test_the_committed_example_is_the_default_recipe_and_valid():
    from pathlib import Path
    example = json.loads((Path(__file__).resolve().parents[2] / "config/kasm-recipe.example.json").read_text())
    assert "config/local/kasm-recipe.json" in example.pop("_note")
    assert kr.validate(example) == recipe()                     # the example never drifts from what the build does by default


def test_settings_and_registry_are_validated():
    r = recipe()
    r["settings"] = {"log_retention": 14}
    assert kr.validate(r)
    for bad in ({"Bad Name": 1}, {"x": 1}, [1]):
        r["settings"] = bad
        with pytest.raises(kr.RecipeError, match="settings are a mapping"):
            kr.validate(r)
    r = recipe()
    r["registry"] = {"enabled": True, "name": "Baseline", "list_url": "https://host.example:8100/kasm-registry/"}
    assert kr.validate(r)
    for url in ("ftp://x/", "https://host/no-trailing-slash", "https://ho st/"):
        r["registry"]["list_url"] = url
        with pytest.raises(kr.RecipeError, match="list_url"):
            kr.validate(r)
    r["registry"]["list_url"] = ""                                  # empty is allowed: this host's own address is used when Kasm is installed
    assert kr.validate(r)
