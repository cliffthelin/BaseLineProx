"""Tests for tools/check_provision_deploys_all_imports.py - the real,
permanent regression check for the exact bug decision record 63 found
by hand: a `baseline/lib/*.py` module transitively imported by a
provisioned bin script, but never copied by provision.sh, crashes that
bin script with `ModuleNotFoundError` the first time it actually runs
on real hardware.

Two things are proven here, deliberately kept separate:
1. Against THIS actual repo, right now, there is no such gap - this
   test doubles as the permanent regression guard for the real bug
   that was found and fixed.
2. The checker itself is correct - proven against a small synthetic
   fixture repo, independent of this repo's own current state, so a
   change to this repo can never accidentally make the checker itself
   silently pass by drifting rather than by the real gap being closed.
"""
from pathlib import Path

import check_provision_deploys_all_imports as cpd

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_this_repos_own_provision_sh_has_no_missing_dependency():
    missing = cpd.find_missing_lib_dependencies(REPO_ROOT)
    assert missing == [], f"provision.sh is missing: {missing} - would crash on real deployment"


def _write_fixture_repo(tmp_path, *, bin_imports: str, extra_lib_files: dict, provision_lib_lines: list):
    (tmp_path / "baseline" / "lib").mkdir(parents=True)
    (tmp_path / "baseline" / "bin").mkdir(parents=True)
    (tmp_path / "boot").mkdir(parents=True)

    (tmp_path / "baseline" / "bin" / "myapp").write_text(bin_imports)
    for name, content in extra_lib_files.items():
        (tmp_path / "baseline" / "lib" / f"{name}.py").write_text(content)

    lines = ['cp "$SRC/baseline/bin/myapp" /opt/baseline/bin/myapp']
    lines += [f'cp "$SRC/baseline/lib/{name}.py" /opt/baseline/lib/{name}.py' for name in provision_lib_lines]
    (tmp_path / "boot" / "provision.sh").write_text("\n".join(lines) + "\n")
    return tmp_path


def test_checker_finds_a_real_gap_in_a_synthetic_fixture(tmp_path):
    _write_fixture_repo(
        tmp_path,
        bin_imports="import sys\nsys.path.insert(0, '/opt/baseline/lib')\nimport helper_a\n",
        extra_lib_files={"helper_a": "import helper_b\n", "helper_b": "X = 1\n"},
        provision_lib_lines=["helper_a"],  # helper_b never copied - a real gap
    )
    missing = cpd.find_missing_lib_dependencies(tmp_path)
    assert missing == ["helper_b"]


def test_checker_reports_no_gap_when_everything_transitively_needed_is_copied(tmp_path):
    _write_fixture_repo(
        tmp_path,
        bin_imports="import sys\nsys.path.insert(0, '/opt/baseline/lib')\nimport helper_a\n",
        extra_lib_files={"helper_a": "import helper_b\n", "helper_b": "X = 1\n"},
        provision_lib_lines=["helper_a", "helper_b"],
    )
    assert cpd.find_missing_lib_dependencies(tmp_path) == []


def test_checker_follows_transitive_imports_two_levels_deep(tmp_path):
    _write_fixture_repo(
        tmp_path,
        bin_imports="import sys\nsys.path.insert(0, '/opt/baseline/lib')\nimport helper_a\n",
        extra_lib_files={
            "helper_a": "import helper_b\n",
            "helper_b": "import helper_c\n",
            "helper_c": "X = 1\n",
        },
        provision_lib_lines=["helper_a", "helper_b"],  # helper_c (two levels deep) never copied
    )
    assert cpd.find_missing_lib_dependencies(tmp_path) == ["helper_c"]


def test_main_returns_0_for_this_real_repo():
    assert cpd.main(["--repo-root", str(REPO_ROOT)]) == 0


def test_main_returns_1_when_a_gap_exists(tmp_path):
    _write_fixture_repo(
        tmp_path,
        bin_imports="import sys\nsys.path.insert(0, '/opt/baseline/lib')\nimport helper_a\n",
        extra_lib_files={"helper_a": "import helper_b\n", "helper_b": "X = 1\n"},
        provision_lib_lines=["helper_a"],
    )
    assert cpd.main(["--repo-root", str(tmp_path)]) == 1
