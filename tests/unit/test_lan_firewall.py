"""LAN-only firewall: default-deny inbound, outbound open, inbound only from private/LAN ranges.
Every command goes through the FakeRunner - no real nft/systemctl is ever invoked."""
import pytest
from fake_runner import FakeProc, FakeRunner

import lan_firewall as lf

LISTING_OK = "table inet baseline_lan {\n chain input {\n  type filter hook input priority filter; policy drop;\n" \
             + "".join(f"  {s}\n" for s in lf.DEFAULT_LAN_SUBNETS) + " }\n}\n"


def _runner(listing=LISTING_OK, **scripts):
    r = FakeRunner()
    r.script_prefix("nft", "list", "table", stdout=listing)
    for prefix, kw in scripts.items():
        r.script_prefix(*prefix.split(), **kw)
    return r


def test_ruleset_is_default_deny_inbound_with_lan_allow_and_no_output_or_forward_restriction():
    text = lf.build_ruleset(lf.DEFAULT_LAN_SUBNETS)
    assert "policy drop" in text
    assert "hook input" in text
    assert "hook output" not in text and "hook forward" not in text   # outbound and VM/LXC forwarding untouched
    assert "iif lo accept" in text
    assert "ct state established,related accept" in text
    for subnet in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fe80::/10", "fc00::/7"):
        assert subnet in text
    assert "udp sport 67 udp dport 68 accept" in text       # the machine must still be able to get its own address
    assert "udp sport 547 udp dport 546 accept" in text
    assert text.index("delete table inet baseline_lan") < text.index("policy drop")   # idempotent reload


@pytest.mark.parametrize("bad", ["0.0.0.0/0", "::/0", "8.8.8.0/24", "garbage", "", "10.0.0.0/8; accept", 5])
def test_non_lan_or_malformed_subnets_are_rejected(bad):
    with pytest.raises(ValueError):
        lf.validate_subnets([bad])


def test_custom_private_subnets_are_accepted_and_empty_means_default():
    assert lf.validate_subnets(["192.168.50.0/24"]) == ["192.168.50.0/24"]
    assert lf.validate_subnets(None) == list(lf.DEFAULT_LAN_SUBNETS)


def test_apply_checks_loads_verifies_then_persists():
    r = _runner()
    ok, detail = lf.apply(r, {"allow_lan_only": True})
    assert ok is True, detail
    calls = r.calls
    cand = lf.RULESET_PATH + ".new"
    assert ["nft", "-c", "-f", cand] in calls
    assert ["nft", "-f", cand] in calls
    assert calls.index(["nft", "-c", "-f", cand]) < calls.index(["nft", "-f", cand])
    assert ["systemctl", "enable", lf.UNIT_NAME] in calls
    assert lf.RULESET_PATH in r.writes and lf.UNIT_PATH in r.writes
    assert calls.index(["nft", "-f", cand]) < calls.index(["systemctl", "enable", lf.UNIT_NAME])


def test_failed_syntax_check_changes_nothing_and_never_touches_the_persisted_ruleset():
    r = _runner(**{"nft -c": dict(returncode=1, stderr="syntax error")})
    r.files[lf.RULESET_PATH] = "previous good ruleset"
    ok, detail = lf.apply(r, {"allow_lan_only": True})
    assert ok is False and "syntax error" in detail
    assert not any(c[:2] == ["nft", "-f"] for c in r.calls)
    assert lf.UNIT_PATH not in r.writes
    assert r.files[lf.RULESET_PATH] == "previous good ruleset"      # next boot still loads the last good rules
    assert not r.path_exists(lf.RULESET_PATH + ".new")               # candidate file cleaned up


def test_failed_reapply_restores_the_previous_ruleset_instead_of_leaving_the_machine_open():
    r = _runner(listing="policy accept")
    r.files[lf.RULESET_PATH] = "previous good ruleset"
    ok, _ = lf.apply(r, {"allow_lan_only": True})
    assert ok is False
    assert ["nft", "-f", lf.RULESET_PATH] in r.calls                  # previous rules reloaded
    assert ["nft", "delete", "table", "inet", "baseline_lan"] not in r.calls
    assert r.files[lf.RULESET_PATH] == "previous good ruleset"


def test_the_ruleset_is_promoted_to_the_persisted_path_only_after_it_verifies():
    r = _runner()
    ok, _ = lf.apply(r, {"allow_lan_only": True})
    assert ok is True
    assert "policy drop" in r.files[lf.RULESET_PATH]
    assert not r.path_exists(lf.RULESET_PATH + ".new")


def test_ipv6_neighbor_discovery_is_allowed_so_ipv6_keeps_working():
    text = lf.build_ruleset(lf.DEFAULT_LAN_SUBNETS)
    assert "icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-advert, nd-router-solicit } accept" in text


def test_boot_unit_loads_after_distro_nftables_and_requires_its_mounts():
    assert "After=nftables.service" in lf._UNIT          # nftables.conf starts with `flush ruleset`; ours must come last
    assert "RequiresMountsFor=/etc/baseline" in lf._UNIT


def test_ruleset_that_does_not_verify_is_removed_and_reported():
    r = _runner(listing="table inet baseline_lan {\n chain input {\n policy accept;\n }\n}\n")
    ok, detail = lf.apply(r, {"allow_lan_only": True})
    assert ok is False and "verif" in detail
    assert ["nft", "delete", "table", "inet", "baseline_lan"] in r.calls   # never leave a half-trusted ruleset
    assert ["systemctl", "enable", lf.UNIT_NAME] not in r.calls


def test_missing_nft_is_a_failure_not_a_pass():
    r = _runner(**{"nft -c": dict(returncode=127, stderr="No such file")})
    assert lf.apply(r, {"allow_lan_only": True})[0] is False


def test_open_mode_is_refused_and_touches_nothing():
    r = _runner()
    ok, detail = lf.apply(r, {"allow_lan_only": False})
    assert ok is False and "LAN-only" in detail
    assert r.calls == [] and r.writes == []


def test_bad_configured_subnet_is_refused_before_any_command():
    r = _runner()
    ok, _ = lf.apply(r, {"allow_lan_only": True, "lan_subnets": ["0.0.0.0/0"]})
    assert ok is False and r.calls == []
