import subprocess

import pytest

import build_currency as bc

SHA_A, SHA_B = "a" * 40, "b" * 40


class Runner:
    def __init__(self, trees, status="", fail=None):
        self.trees, self.status, self.fail = trees, status, fail

    def run(self, argv, timeout=None):
        if self.fail:
            return subprocess.CompletedProcess(argv, 1, "", "x")
        if "rev-parse" in argv:
            return subprocess.CompletedProcess(argv, 0, self.trees[argv[-1].split(":")[1]] + "\n", "")
        return subprocess.CompletedProcess(argv, 0, self.status, "")


def state(**kw):
    return bc.source_state(Runner({"baseline": SHA_A, "boot": SHA_A}, **kw), "/r")


def test_clean_source_state():
    assert state() == {"trees": {"baseline": SHA_A, "boot": SHA_A}, "dirty": []}


def test_uncommitted_changes_are_listed():
    assert state(status=" M baseline/lib/x.py\n?? boot/new.sh\n")["dirty"] == ["baseline/lib/x.py", "boot/new.sh"]


def test_unreadable_source_is_an_error():
    with pytest.raises(bc.BuildError):
        bc.source_state(Runner({}, fail=True), "/r")


def test_matching_record_skips():
    cur = state()
    assert bc.assess({"trees": dict(cur["trees"])}, cur)["action"] == "skip"


def test_no_record_installs():
    assert bc.assess(None, state())["action"] == "install"


def test_changed_tree_installs_and_names_it():
    out = bc.assess({"trees": {"baseline": SHA_B, "boot": SHA_A}}, state())
    assert out["action"] == "install" and "baseline" in out["reason"] and "boot" not in out["reason"]


def test_dirty_source_never_skips_even_with_a_matching_record():
    cur = state(status=" M baseline/lib/x.py\n")
    assert bc.assess({"trees": dict(cur["trees"])}, cur)["action"] == "install"
