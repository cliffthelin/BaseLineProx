"""A carried package cache records what it was built for, and a stale one is never used (found 2026-10-15: `cache_status` called a cache
built before bluez/pipewire were added "complete", so the install would have failed offline at `apt-get install`).

The cache carries BUILT_FOR.json (hashed in its manifest like any file): the list of packages it was built to satisfy. The install stage
compares it with the list the current code needs. Comparing with the apt index does not work: the Proxmox base already has curl, ethtool and
others, so they never appear in what was downloaded."""
import json
from pathlib import Path

import pytest

import offline_cache as oc

REPO = Path(__file__).resolve().parents[2]
allscript = None


@pytest.fixture(autouse=True)
def _load_allscript():
    global allscript
    if allscript is None:
        from importlib.machinery import SourceFileLoader
        from importlib.util import module_from_spec, spec_from_loader
        loader = SourceFileLoader("allscript_install_for_currency", str(REPO / "baseline/bin/baseline-allscript-install"))
        spec = spec_from_loader(loader.name, loader)
        allscript = module_from_spec(spec)
        loader.exec_module(allscript)


@pytest.fixture
def packages(monkeypatch):
    names = ["inxi", "tmux", "bluez"]
    monkeypatch.setattr(oc, "required_packages", lambda repo_root: list(names))
    return names


def cache(tmp_path, packages_built_for=None, apps=True):
    root = tmp_path / "cache"
    root.mkdir()
    (root / "MANIFEST.json").write_text("{}")
    if apps:
        (root / "apps").mkdir()
    if packages_built_for is not None:
        (root / oc.BUILT_FOR).write_text(json.dumps({"required_packages": packages_built_for, "sha256": "x"}))
    return root


def test_the_fingerprint_does_not_depend_on_the_order_or_duplicates(packages, monkeypatch):
    a = oc.required_fingerprint(REPO)
    monkeypatch.setattr(oc, "required_packages", lambda repo_root: ["bluez", "inxi", "tmux", "inxi"])
    assert oc.required_fingerprint(REPO) == a


def test_the_fingerprint_changes_when_a_package_is_added(packages, monkeypatch):
    before = oc.required_fingerprint(REPO)
    monkeypatch.setattr(oc, "required_packages", lambda repo_root: packages + ["wireplumber"])
    assert oc.required_fingerprint(REPO) != before


def test_a_cache_written_for_the_current_packages_is_current(tmp_path, packages):
    root = tmp_path / "c"
    root.mkdir()
    oc.write_built_for(root, REPO)
    assert oc.cache_is_current(root, REPO) == (True, "")


def test_a_cache_that_never_recorded_what_it_was_built_for_is_not_current(tmp_path, packages):
    ok, why = oc.cache_is_current(cache(tmp_path), REPO)
    assert ok is False and "never recorded" in why


def test_a_stale_cache_names_the_packages_it_lacks_and_the_ones_it_no_longer_needs(tmp_path, packages):
    ok, why = oc.cache_is_current(cache(tmp_path, packages_built_for=["inxi", "tmux", "old-thing"]), REPO)
    assert ok is False and "bluez" in why and "old-thing" in why


def test_an_unreadable_record_is_not_current_rather_than_an_error(tmp_path, packages):
    root = cache(tmp_path)
    (root / oc.BUILT_FOR).write_text("{broken")
    ok, why = oc.cache_is_current(root, REPO)
    assert ok is False and "unreadable" in why


def test_the_record_is_part_of_the_manifest_so_a_target_verifies_it(tmp_path, packages):
    root = tmp_path / "c"
    root.mkdir()
    oc.write_built_for(root, REPO)
    assert oc.BUILT_FOR in oc.build_manifest(root)


def test_the_install_stage_calls_a_cache_built_for_other_packages_stale(tmp_path, packages):
    assert allscript.cache_status(cache(tmp_path, packages_built_for=["inxi"]), REPO) == "stale"
    other = tmp_path / "ok"
    other.mkdir()
    (other / "MANIFEST.json").write_text("{}")
    (other / "apps").mkdir()
    oc.write_built_for(other, REPO)
    assert allscript.cache_status(other, REPO) == "complete"


def test_without_a_repo_the_old_meaning_is_unchanged(tmp_path):
    assert allscript.cache_status(tmp_path / "none") == "missing"
    assert allscript.cache_status(cache(tmp_path, apps=False)) == "without_apps"


def test_every_use_of_the_status_passes_the_repo_so_the_check_cannot_be_forgotten():
    text = (REPO / "baseline/bin/baseline-allscript-install").read_text()
    uses = [line for line in text.splitlines() if "cache_status(CACHE_DIR" in line]
    assert uses and all("REPO" in line for line in uses), uses


def test_the_builder_records_what_it_built_for():
    assert "write_built_for(output" in (REPO / "baseline/bin/baseline-build-offline-cache").read_text()
