"""Baseline as a Kasm third-party workspace registry: the published schema 1.1, built from the release's own workspace definitions."""
import json

import pytest

import kasm_build as kb
import kasm_registry as kr

SEED = """
images:
- {name: "kasmweb/chrome:1.19.0-rolling-daily", friendly_name: Chrome, description: A browser, docker_registry: "https://index.docker.io/v1/", categories: [Browser], cores: 2.0,
   memory_bytes: 2902458368, gpu_count: 0, cpu_allocation_method: Inherit, uncompressed_size_mb: 2934, run_config: {hostname: kasm}, exec_config: {go: {cmd: x}}, notes: null}
- {name: "kasmweb/firefox:1.19.0-rolling-daily", friendly_name: Firefox, description: Another, docker_registry: "https://index.docker.io/v1/", categories: [Browser], cores: 2.0,
   memory_bytes: null, gpu_count: 0, cpu_allocation_method: Inherit, uncompressed_size_mb: 2500, run_config: {}, exec_config: {}}
"""
WS = [{"key": "a", "image": "chrome", "friendly_name": "Browser (temporary)", "persistent": False},
      {"key": "b", "image": "chrome", "friendly_name": "Browser (personal)", "persistent": True},
      {"key": "c", "image": "firefox", "friendly_name": "Firefox", "persistent": True}]


def build(**kw):
    return kr.build(WS, SEED, name="Baseline", description="d", list_url="https://h.example:8100/kasm-registry/", now_ms=1700000000000, **kw)


def test_the_document_has_the_published_top_level_fields_and_one_entry_per_distinct_image():
    doc = build()
    assert list(doc) == ["name", "workspacecount", "icon", "description", "list_url", "contact_url", "modified", "workspaces", "channels", "default_channel"]
    assert doc["workspacecount"] == 2 and [w["friendly_name"] for w in doc["workspaces"]] == ["Browser", "Firefox"]       # a temporary and a personal browser are one image
    assert doc["modified"] == 1700000000000 and doc["channels"] == [] and json.loads(kr.render(doc)) == doc


def test_each_workspace_carries_the_releases_own_definition_and_a_compatibility_entry_for_this_version():
    chrome = build()["workspaces"][0]
    assert chrome["image_src"] == "chrome.png" and chrome["architecture"] == ["amd64"] and chrome["run_config"] == {"hostname": "kasm"} and chrome["exec_config"] == {"go": {"cmd": "x"}}
    assert chrome["compatibility"] == [{"version": "1.19.x", "image": "kasmweb/chrome:1.19.0", "uncompressed_size_mb": 2934}]
    assert chrome["memory"] == 2768 and chrome["cores"] == 2.0 and len(chrome["sha"]) == 40 and "notes" not in chrome


def test_a_workspace_image_the_release_does_not_have_is_refused():
    with pytest.raises(kr.RegistryError, match="no workspace image named ghost"):
        kr.build([{"key": "x", "image": "ghost", "friendly_name": "G", "persistent": False}], SEED, name="B", description="d", list_url="https://h/")


@pytest.mark.parametrize("url", ["https://h.example/no-slash", "ftp://h/", ""])
def test_the_registry_address_must_be_an_http_address_ending_in_a_slash(url):
    with pytest.raises(kr.RegistryError, match="ending in a slash"):
        kr.build(WS, SEED, name="B", description="d", list_url=url)


def test_the_real_default_workspaces_build_from_the_real_release_seed_when_present():
    from pathlib import Path
    seeds = list(Path("/tmp").glob("**/kasm_release/conf/database/seed_data/default_images_amd64.yaml"))
    if not seeds:
        pytest.skip("no Kasm release seed on this machine")
    doc = kr.build(kb.WORKSPACES, seeds[0].read_text(), name="Baseline", description="d", list_url="https://h.example/kasm-registry/")
    assert doc["workspacecount"] == 5 and all(w["compatibility"][0]["image"].endswith(":1.19.0") for w in doc["workspaces"])
