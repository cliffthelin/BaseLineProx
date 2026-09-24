from inventory.runner import CommandResult
from inventory.collectors import security

from .fake_runner import FakeRunner


def test_sysctl_discovered_keys_are_not_queried_unless_reviewed():
    """Cliff's fail-closed correction: a key merely appearing in a config
    file earns it a place in discovered_keys, never a live sysctl query -
    only the separately reviewed SYSCTL_ALLOWLIST gets queried."""
    r = FakeRunner()
    r.binaries["sysctl"] = "/usr/sbin/sysctl"
    r.files["/etc/sysctl.conf"] = "kernel.some_undiscovered_tunable = 1\n"
    r.dirs["/etc/sysctl.d"] = []
    queried_keys = []
    r.script(
        lambda a: a[0] == "sysctl",
        lambda a: (queried_keys.append(a[1]), CommandResult(ok=True, stdout=f"{a[1]} = 1"))[1],
    )
    result = security.collect_sysctl(r)
    assert result["discovered_keys"] == ["kernel.some_undiscovered_tunable"]
    assert "kernel.some_undiscovered_tunable" not in queried_keys
    assert set(queried_keys) == set(security.SYSCTL_ALLOWLIST)


def test_sysctl_reviewed_keys_still_get_live_values():
    r = FakeRunner()
    r.binaries["sysctl"] = "/usr/sbin/sysctl"
    r.files["/etc/sysctl.conf"] = ""
    r.dirs["/etc/sysctl.d"] = []
    r.script(lambda a: a[0] == "sysctl", CommandResult(ok=True, stdout="1"))
    result = security.collect_sysctl(r)
    assert set(result["values"].keys()) == set(security.SYSCTL_ALLOWLIST)


def test_sysctl_discovered_key_that_is_also_reviewed_appears_in_both():
    r = FakeRunner()
    r.binaries["sysctl"] = "/usr/sbin/sysctl"
    reviewed_key = security.SYSCTL_ALLOWLIST[0]
    r.files["/etc/sysctl.conf"] = f"{reviewed_key} = 1\n"
    r.dirs["/etc/sysctl.d"] = []
    r.script(lambda a: a[0] == "sysctl", CommandResult(ok=True, stdout="1"))
    result = security.collect_sysctl(r)
    assert reviewed_key in result["discovered_keys"]
    assert reviewed_key in result["values"]


def test_firewall_ruleset_unavailable_is_visibly_reported():
    r = FakeRunner()  # no nft, no iptables on PATH
    result = security.collect_firewall_ruleset(r)
    assert result["backend"] is None
    assert result["_collection_notes"][0]["status"] == "unavailable"
