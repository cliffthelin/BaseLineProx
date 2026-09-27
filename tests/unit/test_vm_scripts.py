"""Unit tests for vm_scripts.py - Track A6, VM/LXC provisioning via
pinned + sha256-verified community-scripts/ProxmoxVE Helper-Scripts. No
real curl, no real bash, no real pct/qm/network - see fake_runner.FakeRunner.

Fixtures under tests/unit/fixtures/ are byte-identical copies of the
real, MIT-licensed upstream files at the commits vm_scripts.py pins
(PINNED_COMMIT / CORE_PINNED_COMMIT) - their sha256 genuinely matches
the manifest, not a fabricated stand-in."""
import json
from pathlib import Path

from fake_runner import FakeRunner

import vm_scripts

FIXTURES = Path(__file__).parent / "fixtures"
DEBIAN_LXC_FIXTURE = (FIXTURES / "pve_ct_debian_pinned.sh").read_text()
CORE_BUILD_FUNC_FIXTURE = (FIXTURES / "pve_core_build_func_pinned.sh").read_text()


def _runner_with_verified_fetches(entry_ok=True, core_ok=True):
    runner = FakeRunner()
    entry_stdout = DEBIAN_LXC_FIXTURE if entry_ok else "echo tampered"
    core_stdout = CORE_BUILD_FUNC_FIXTURE if core_ok else "echo tampered-core"
    runner.script(lambda argv: argv[:1] == ["curl"] and "community-scripts/core" in argv[-1],
                  __import__("fake_runner").FakeProc(0, core_stdout, ""))
    runner.script(lambda argv: argv[:1] == ["curl"] and "ProxmoxVE" in argv[-1],
                  __import__("fake_runner").FakeProc(0, entry_stdout, ""))
    return runner


def test_list_scripts_is_pure_and_sorted():
    ids = [s.script_id for s in vm_scripts.list_scripts()]
    assert ids == sorted(ids)
    assert "docker-lxc" in ids
    assert "haos-vm" in ids


def test_verify_and_get_refuses_unknown_script_id_without_fetching():
    runner = FakeRunner()
    result = vm_scripts.verify_and_get(runner, "not-a-real-script")
    assert result.outcome == "refused"
    assert result.content is None
    assert "not on the known-script allow-list" in result.detail
    assert runner.calls == []


def test_verify_and_get_applies_on_matching_hash():
    runner = _runner_with_verified_fetches()
    result = vm_scripts.verify_and_get(runner, "debian-lxc")
    assert result.outcome == "applied"
    assert result.content == DEBIAN_LXC_FIXTURE


def test_verify_and_get_refuses_on_hash_mismatch():
    runner = _runner_with_verified_fetches(entry_ok=False)
    result = vm_scripts.verify_and_get(runner, "debian-lxc")
    assert result.outcome == "refused"
    assert result.content is None
    assert "sha256 mismatch" in result.detail


def test_verify_and_get_refuses_on_fetch_failure():
    runner = FakeRunner()
    runner.script_prefix("curl", returncode=22, stdout="", stderr="404 not found")
    result = vm_scripts.verify_and_get(runner, "debian-lxc")
    assert result.outcome == "refused"
    assert "fetch failed" in result.detail


def test_verify_core_build_func_applies_on_matching_hash():
    runner = _runner_with_verified_fetches()
    result = vm_scripts.verify_core_build_func(runner)
    assert result.outcome == "applied"
    assert result.content == CORE_BUILD_FUNC_FIXTURE


def test_verify_core_build_func_refuses_on_hash_mismatch():
    runner = _runner_with_verified_fetches(core_ok=False)
    result = vm_scripts.verify_core_build_func(runner)
    assert result.outcome == "refused"
    assert "sha256 mismatch" in result.detail


def test_run_script_never_executes_when_entry_script_unverified():
    runner = _runner_with_verified_fetches(entry_ok=False)
    outcome = vm_scripts.run_script(runner, "debian-lxc")
    assert outcome.outcome == "refused"
    assert all(call[0] != "bash" for call in runner.calls)
    assert runner.writes == []  # core/build.func never staged either


def test_run_script_never_executes_when_core_build_func_unverified():
    runner = _runner_with_verified_fetches(core_ok=False)
    outcome = vm_scripts.run_script(runner, "debian-lxc")
    assert outcome.outcome == "refused"
    assert "core/build.func" in outcome.detail
    assert all(call[0] != "bash" for call in runner.calls)


def test_run_script_stages_verified_core_and_executes_with_override_env():
    runner = _runner_with_verified_fetches()
    runner.script(lambda argv: argv[:1] == ["bash"], __import__("fake_runner").FakeProc(0, "Created LXC 105", ""))
    outcome = vm_scripts.run_script(runner, "debian-lxc")
    assert outcome.outcome == "applied"
    assert runner.files[vm_scripts.CORE_BUILD_FUNC_PATH] == CORE_BUILD_FUNC_FIXTURE
    bash_call = [c for c in runner.calls if c[0] == "bash"][0]
    assert vm_scripts.CORE_STATE_DIR in bash_call[2]
    assert DEBIAN_LXC_FIXTURE in bash_call[2]


def test_run_script_logs_exactly_one_event_per_attempt():
    runner = _runner_with_verified_fetches()
    runner.script(lambda argv: argv[:1] == ["bash"], __import__("fake_runner").FakeProc(0, "Created LXC 105", ""))
    vm_scripts.run_script(runner, "debian-lxc")
    assert len(runner.appends) == 1
    logged = json.loads(runner.files[runner.appends[0]].strip())
    assert logged["script_id"] == "debian-lxc"
    assert logged["outcome"] == "applied"
    assert logged["stage"] == "execute"


def test_run_script_honors_custom_timeout_override():
    class TimeoutCapturingRunner(FakeRunner):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.timeouts_by_argv0 = []

        def run(self, argv, timeout=10):
            self.timeouts_by_argv0.append((argv[0], timeout))
            return super().run(argv, timeout=timeout)

    runner = TimeoutCapturingRunner()
    entry_stdout, core_stdout = DEBIAN_LXC_FIXTURE, CORE_BUILD_FUNC_FIXTURE
    runner.script(lambda argv: argv[:1] == ["curl"] and "community-scripts/core" in argv[-1],
                  __import__("fake_runner").FakeProc(0, core_stdout, ""))
    runner.script(lambda argv: argv[:1] == ["curl"] and "ProxmoxVE" in argv[-1],
                  __import__("fake_runner").FakeProc(0, entry_stdout, ""))
    runner.script(lambda argv: argv[:1] == ["bash"], __import__("fake_runner").FakeProc(0, "Created LXC 105", ""))

    vm_scripts.run_script(runner, "debian-lxc", timeout=45)

    bash_timeout = [t for name, t in runner.timeouts_by_argv0 if name == "bash"][0]
    assert bash_timeout == 45


def test_run_script_logs_refusal_event_when_script_id_unknown():
    runner = FakeRunner()
    vm_scripts.run_script(runner, "not-a-real-script")
    assert len(runner.appends) == 1
    logged = json.loads(runner.files[runner.appends[0]].strip())
    assert logged["outcome"] == "refused"
    assert logged["stage"] == "entry_script"
