"""Tests for the deployed-files/unit-status coverage added during the
canonical-repo port (baseline/lib/inventory/collectors/baseline_config.py) -
the historical inventory branch only ever checked baseline.service and
never inventoried /opt/baseline/bin or /opt/baseline/lib at all, a real
gap versus what boot/provision.sh actually deploys."""
from inventory.collectors.baseline_config import collect_baseline_config
from inventory.runner import CommandResult

from .fake_runner import FakeRunner


def test_all_three_deployed_units_are_checked_not_just_baseline_service():
    r = FakeRunner()
    r.dirs["/etc/baseline"] = []
    r.dirs["/var/lib/baseline"] = []
    r.dirs["/opt/baseline/bin"] = []
    r.dirs["/opt/baseline/lib"] = []
    r.binaries["systemctl"] = "/usr/bin/systemctl"
    r.script(lambda a: a[:2] == ["systemctl", "status"], CommandResult(ok=True, stdout="active"))

    result = collect_baseline_config(r)

    assert set(result["unit_status_available"]) == {
        "baseline.service", "baseline-additive-dhcp-reapply.service", "baseline-firstboot.service",
    }
    assert all(result["unit_status_available"].values())


def test_deployed_files_are_listed_and_hashed_not_read_as_content():
    r = FakeRunner()
    r.dirs["/etc/baseline"] = []
    r.dirs["/var/lib/baseline"] = []
    r.dirs["/opt/baseline/bin"] = ["/opt/baseline/bin/baseline"]
    r.dirs["/opt/baseline/lib"] = ["/opt/baseline/lib/repair.py"]
    r.binaries["systemctl"] = "/usr/bin/systemctl"
    r.binaries["sha256sum"] = "/usr/bin/sha256sum"
    r.script(lambda a: a[:2] == ["systemctl", "status"], CommandResult(ok=True, stdout="active"))
    r.script(
        lambda a: a[:1] == ["sha256sum"],
        CommandResult(ok=True, stdout=(
            "aaaa  /opt/baseline/bin/baseline\n"
            "bbbb  /opt/baseline/lib/repair.py\n"
        )),
    )

    result = collect_baseline_config(r)

    assert result["deployed_files"] == ["/opt/baseline/bin/baseline", "/opt/baseline/lib/repair.py"]
    assert result["deployed_file_sha256"] == {
        "/opt/baseline/bin/baseline": "aaaa",
        "/opt/baseline/lib/repair.py": "bbbb",
    }
    # Never read as content - only hashed via a subprocess.
    assert not any("baseline" in p and p not in ("/etc/baseline",) for p in r.read_calls)


def test_no_deployed_files_means_no_hash_call_attempted():
    r = FakeRunner()
    r.dirs["/etc/baseline"] = []
    r.dirs["/var/lib/baseline"] = []
    r.dirs["/opt/baseline/bin"] = []
    r.dirs["/opt/baseline/lib"] = []
    r.binaries["systemctl"] = "/usr/bin/systemctl"
    r.script(lambda a: a[:2] == ["systemctl", "status"], CommandResult(ok=True, stdout="active"))

    result = collect_baseline_config(r)

    assert result["deployed_files"] == []
    assert result["deployed_file_sha256"] == {}
    assert not any(c[:1] == ["sha256sum"] for c in r.run_calls)
