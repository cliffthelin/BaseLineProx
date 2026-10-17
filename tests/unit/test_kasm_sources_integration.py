"""Workspaces from other registries, end to end on this side: the builder's step, what the host reads back, the page, and the icons served."""
import http.client
import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest

import kasm_page
import kasm_setup as ksetup
from test_baseline_web import _RealServerCase, _base_deps
from test_kasm_setup import build, world  # noqa: F401
from test_kasm_sources import CHROMIUM, FIXTURE, PNG, site, source  # noqa: F401
from test_new_web_routes import req

BUILDER = Path(__file__).parents[2] / "baseline" / "bin" / "baseline-build-kasm-base"


@pytest.fixture(scope="module")
def builder():
    loader = importlib.machinery.SourceFileLoader("baseline_build_kasm_base", str(BUILDER))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def test_the_builder_adds_the_sources_to_its_registry_and_says_what_it_did(builder, site, tmp_path, capsys, monkeypatch):
    import kasm_sources
    _, url = site
    real = kasm_sources.fetch_bytes
    monkeypatch.setattr(kasm_sources, "fetch_bytes", lambda u, limit, **kw: real(u, limit, allow_http=True))      # the test site is http on localhost
    document = {"name": "Baseline", "workspacecount": 1, "workspaces": [{"friendly_name": "Browser"}]}
    rows = builder.add_sources(document, [source(url=url)], "1.19.0", tmp_path / "registry", tmp_path / "cache")
    out = capsys.readouterr().out
    assert [r["status"] for r in rows] == ["included"] and document["workspacecount"] == 2
    assert "included (UNVERIFIED for this Kasm version)" in out
    assert builder.add_sources(document, [], "1.19.0", tmp_path / "registry", tmp_path / "cache") == []


def test_the_builder_reports_why_a_workspace_was_left_out(builder, site, tmp_path, capsys, monkeypatch):
    import kasm_sources
    _, url = site
    real = kasm_sources.fetch_bytes
    monkeypatch.setattr(kasm_sources, "fetch_bytes", lambda u, limit, **kw: real(u, limit, allow_http=True))
    document = {"name": "Baseline", "workspacecount": 0, "workspaces": []}
    builder.add_sources(document, [source(url=url, include=[{"name": "Chromium"}])], "1.19.0", tmp_path / "registry", tmp_path / "cache")
    assert f"left out: it has not been reviewed" in capsys.readouterr().out and document["workspaces"] == []


def carried(world, rows, icons=()):
    registry = world.base_dir / "registry"
    (registry / "1.1" / "icons").mkdir(parents=True, exist_ok=True)
    (registry / "1.1" / "list.json").write_text(json.dumps({"workspaces": [{"image_src": "chrome.png"}, {"image_src": "linuxserver-chromium.png"}]}))
    (registry / "sources.json").write_text(json.dumps({"sources": [], "workspaces": rows}))
    for name in icons:
        (registry / "1.1" / "icons" / name).write_bytes(PNG)


def test_the_host_reads_back_what_was_taken_and_does_not_ask_kasm_for_icons_that_came_with_it(world):
    setup, _ = build(world)
    assert setup.carried_sources() is None
    carried(world, [{"source": "linuxserver", "name": "Chromium", "status": "included"}], icons=["linuxserver-chromium.png"])
    assert setup.carried_sources()["workspaces"][0]["name"] == "Chromium"
    assert setup.registry_icon_names() == ["chrome.png"]
    (world.base_dir / "registry" / "sources.json").write_text("{ broken")
    assert setup.carried_sources() is None                                                      # damaged: nothing claimed, no crash


ROWS = [{"source": "linuxserver", "name": "Chromium", "status": "included", "unverified": True, "findings": ["run_config.security_opt"], "requires_network": True},
        {"source": "linuxserver", "name": "Firefox", "status": "excluded", "reason": "it has not been reviewed: set reviewed to abc", "findings": [], "definition": {"image": "x<script>alert(1)</script>"}}]


def test_the_page_says_what_is_offered_with_its_caveats_and_what_is_left_out_with_the_definition_to_read():
    page = kasm_page.render({"present": False, "installed": False, "registry_sources": {"workspaces": ROWS}}).decode()
    assert "From other registries" in page and "<b>Chromium</b> from linuxserver: offered" in page
    assert "not verified on this Kasm version" in page and "accepted: run_config.security_opt" in page and "needs internet" in page
    assert "<b>Firefox</b> from linuxserver: <b>left out</b>" in page and "Read its definition" in page
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page                           # a definition from outside is shown as text
    assert "From other registries" not in kasm_page.render({"present": False, "installed": False}).decode()


@pytest.fixture
def served(tmp_path):
    icons, registry = tmp_path / "icons", tmp_path / "registry"
    (registry / "1.1" / "icons").mkdir(parents=True)
    icons.mkdir()
    (registry / "1.1" / "icons" / "linuxserver-chromium.png").write_bytes(PNG)
    (icons / "chrome.png").write_bytes(PNG + b"kasm")
    case = _RealServerCase(_base_deps(kasm_registry_dir=str(registry), kasm_registry_icons_dir=str(icons)))
    case.registry = registry
    yield case
    case.close()


def get(case, path):
    conn = http.client.HTTPConnection("127.0.0.1", case.port, timeout=10)
    conn.request("GET", path)
    r = conn.getresponse()
    out = (r.status, r.read())
    conn.close()
    return out


def test_an_icon_that_came_with_the_registry_is_served_beside_the_ones_copied_from_kasm(served):
    assert get(served, "/kasm-registry/1.1/icons/linuxserver-chromium.png") == (200, PNG)
    assert get(served, "/kasm-registry/1.1/icons/chrome.png") == (200, PNG + b"kasm")
    assert get(served, "/kasm-registry/1.1/icons/missing.png")[0] == 404


def test_the_carried_icon_folder_cannot_be_used_to_reach_anything_else(served):
    (served.registry / "1.1" / "secret.txt").write_text("private")
    (served.registry / "1.1" / "icons" / "link.png").symlink_to(served.registry / "1.1" / "secret.txt")
    assert get(served, "/kasm-registry/1.1/icons/link.png")[0] == 404
    assert get(served, "/kasm-registry/1.1/icons/..%2Fsecret.txt")[0] in (303, 404)                  # refused: it is not an icon name at all
    assert get(served, "/kasm-registry/1.1/icons/sources.json")[0] in (303, 404)


def test_an_imported_icon_always_gets_a_name_the_registry_will_serve_however_long_the_workspace_name():
    import kasm_registry
    import kasm_sources
    for name, ext in (("Chromium", "png"), ("A Very Long Workspace Name With Many Many Words In It", "svg"), ("Odd!! Name ??", "png")):
        icon = kasm_sources._icon_name("linuxserver", {"friendly_name": name, "image_src": f"x.{ext}"})
        assert kasm_registry.ICON_NAME.fullmatch(icon) and icon.endswith("." + ext), icon
