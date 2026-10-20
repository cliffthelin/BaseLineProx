import subprocess

import pytest

import update_bundle as ub


class R:
    def __init__(self, dirty=""):
        self.dirty = dirty

    def run(self, argv, timeout=None):
        if "rev-parse" in argv:
            return subprocess.CompletedProcess(argv, 0, "a" * 40 + "\n", "")
        return subprocess.CompletedProcess(argv, 0, self.dirty, "")


def test_the_bundle_is_prepared_from_the_commit_and_named_for_the_target(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(ub.installer_inputs, "prepare", lambda root, dest, **kw: seen.update(root=root, dest=dest, **kw) or {"prepared": True})
    monkeypatch.setattr(ub.installer_inputs, "verify", lambda dest: seen.update(verified=str(dest)))
    folder = ub.prepare_update_bundle(R(), tmp_path / "repo", tmp_path / "bundles", "PC9", now=1_800_000_000, known_targets={"PC9"})
    assert folder.parent == tmp_path / "bundles" and folder.name.startswith("pc9-") and seen["verified"] == str(folder)
    assert seen["plan"] == {"installed_update": {"serial": "PC9"}} and seen["settings"] == {}


def test_uncommitted_changes_are_refused_so_an_update_is_exactly_a_commit(tmp_path):
    with pytest.raises(ub.BundleError, match="uncommitted"):
        ub.prepare_update_bundle(R(" M baseline/lib/x.py\n"), tmp_path, tmp_path / "b", "PC9")


def test_an_unknown_target_is_refused(tmp_path):
    with pytest.raises(ub.BundleError, match="not a drive"):
        ub.prepare_update_bundle(R(), tmp_path, tmp_path / "b", "NOPE", known_targets={"PC9"})
