"""Tests for the additive network-repair extension (Milestone 1 Gate A,
v4 scope: preserve the actually-reproduced IPv6-only Fixture A rather than
requiring `ipv6=off` to manufacture an IPv4 configuration).

Fixture A and Fixture B below are byte-accurate transcriptions of the real
`/etc/network/interfaces` files captured directly from disposable QEMU
installs in Milestone 1 Phase 0 - see
docs/design/decision-records/10-m1-phase0-network-resolution.md. They are
not hand-approximated shapes; they are the actual evidence.
"""
import ifnet_config as ic
import network
import repair
import repair_additive
import topology as topo
import firstboot_network_repair as fbnr
from fake_runner import FakeRunner, FakeProc

# --- Byte-accurate Phase 0 fixtures ---------------------------------------

FIXTURE_A_IPV6_ONLY = """auto lo
iface lo inet loopback

iface ens3 inet6 manual

auto vmbr0
iface vmbr0 inet6 static
\taddress fec0::5054:ff:feba:5e12/64
\tgateway fe80::2
\tbridge-ports ens3
\tbridge-stp off
\tbridge-fd 0

source /etc/network/interfaces.d/*
"""

FIXTURE_B_IPV4_FALLBACK = """auto lo
iface lo inet loopback

iface ens3 inet manual

auto vmbr0
iface vmbr0 inet static
\taddress 192.168.100.2/24
\tgateway 192.168.100.1
\tbridge-ports ens3
\tbridge-stp off
\tbridge-fd 0

source /etc/network/interfaces.d/*
"""


def _cfg(text):
    return ic.parse_files({"/etc/network/interfaces": text})


# ===========================================================================
# 1. Byte-accurate fixture parsing
# ===========================================================================

def test_fixture_a_parses_confidently_with_glob_source_recorded():
    cfg = _cfg(FIXTURE_A_IPV6_ONLY)
    assert "vmbr0" in cfg.stanzas
    assert cfg.stanzas["vmbr0"].family == "inet6"
    assert cfg.stanzas["vmbr0"].method == "static"
    assert cfg.stanzas["ens3"].family == "inet6"
    assert cfg.stanzas["ens3"].method == "manual"
    # The glob-form `source` line is recorded (informationally - this
    # module has no filesystem access to resolve it itself) but does NOT
    # break confidence: a glob that resolves to zero real fragment files
    # (the normal case for a fresh install) is not an unconfident parse.
    # Real resolution happens in repair.read_interfaces_config via
    # Runner.listdir - see the dedicated glob-resolution test below.
    assert cfg.glob_source_targets == [("/etc/network/interfaces", 13, "/etc/network/interfaces.d/*")]
    assert cfg.confidently_parsed


def test_fixture_b_parses_confidently_with_glob_source_recorded():
    cfg = _cfg(FIXTURE_B_IPV4_FALLBACK)
    assert cfg.stanzas["vmbr0"].family == "inet"
    assert cfg.stanzas["vmbr0"].method == "static"
    assert cfg.stanzas["vmbr0"].options["address"] == "192.168.100.2/24"
    assert cfg.stanzas["ens3"].family == "inet"
    assert cfg.stanzas["ens3"].method == "manual"
    assert cfg.confidently_parsed


def test_resolve_source_glob_matches_only_the_pattern():
    entries = ["/etc/network/interfaces.d/eth0.cfg", "/etc/network/interfaces.d/README",
               "/etc/network/interfaces.d/.hidden"]
    matched = ic.resolve_source_glob("/etc/network/interfaces.d/*", entries)
    # fnmatch's "*" does not treat a leading dot specially the way shell
    # globs sometimes do - assert the actual, tested behavior rather than
    # an assumption: all three match this pattern.
    assert matched == sorted(entries)


def test_read_interfaces_config_resolves_real_glob_fragment_files():
    import repair
    from fake_runner import FakeRunner
    r = FakeRunner(files={
        "/etc/network/interfaces": FIXTURE_A_IPV6_ONLY,
        "/etc/network/interfaces.d/extra.cfg": "# a real fragment file\n",
    })
    cfg = repair.read_interfaces_config(r)
    assert "/etc/network/interfaces.d/extra.cfg" in cfg.files
    assert cfg.files["/etc/network/interfaces.d/extra.cfg"] == "# a real fragment file\n"


def test_read_interfaces_config_handles_empty_interfaces_d_cleanly():
    import repair
    from fake_runner import FakeRunner
    # No fragment files at all - the normal case for a fresh Proxmox
    # install (Milestone 1 Phase 0 never confirmed any existed). Must not
    # raise and must not fabricate a phantom file for the literal glob
    # string itself.
    r = FakeRunner(files={"/etc/network/interfaces": FIXTURE_A_IPV6_ONLY})
    cfg = repair.read_interfaces_config(r)
    assert "/etc/network/interfaces.d/*" not in cfg.files
    assert cfg.confidently_parsed


def test_source_directory_form_still_works_unaffected():
    # source-directory (as opposed to bare `source <glob>`) already
    # resolves via runner.listdir and is unaffected by this change.
    text = "auto lo\niface lo inet loopback\n\nsource-directory /etc/network/interfaces.d\n"
    cfg = _cfg(text)
    assert cfg.glob_source_targets == []


# ===========================================================================
# 2. Additive topology derivation
# ===========================================================================

def test_derive_additive_target_selects_vmbr0_for_fixture_a():
    cfg = _cfg(FIXTURE_A_IPV6_ONLY)
    result = topo.derive_additive_target("vmbr0", cfg)
    assert result.ok
    assert result.target.name == "vmbr0"
    assert result.target.kind == "bridge"
    assert result.target.physical_devices == ["ens3"]


def test_derive_additive_target_from_physical_member_walks_up():
    cfg = _cfg(FIXTURE_A_IPV6_ONLY)
    result = topo.derive_additive_target("ens3", cfg)
    assert result.ok
    assert result.target.name == "vmbr0"


def test_derive_additive_target_refuses_fixture_b_since_inet_already_exists():
    # Fixture B already has a real inet static stanza - that's a REPLACE
    # case (derive_target's job), never additive. Mixing the two paths for
    # the same interface is exactly what this must not do.
    cfg = _cfg(FIXTURE_B_IPV4_FALLBACK)
    result = topo.derive_additive_target("vmbr0", cfg)
    assert not result.ok
    assert result.candidates == []


def test_derive_target_replace_path_refuses_fixture_a_cleanly():
    # The existing, unmodified replace-path derivation must still refuse
    # (not crash, not mis-select) Fixture A - confirming decision record
    # 11's finding directly, not just asserting it in prose.
    cfg = _cfg(FIXTURE_A_IPV6_ONLY)
    result = topo.derive_target("vmbr0", cfg)
    assert not result.ok
    assert "no inet static configuration" in result.reason


def test_derive_target_replace_path_still_selects_vmbr0_for_fixture_b():
    # Fixture B continues to use the existing replacement behavior,
    # completely unchanged.
    cfg = _cfg(FIXTURE_B_IPV4_FALLBACK)
    result = topo.derive_target("vmbr0", cfg)
    assert result.ok
    assert result.target.name == "vmbr0"
    assert result.target.kind == "bridge"
    assert result.target.physical_devices == ["ens3"]


# ===========================================================================
# 3. plan_and_derive mode selection
# ===========================================================================

def test_plan_and_derive_picks_additive_for_fixture_a():
    r = FakeRunner(files={"/etc/network/interfaces": FIXTURE_A_IPV6_ONLY})
    mode, result = repair_additive.plan_and_derive(r, "vmbr0")
    assert mode == "additive"
    assert result.ok
    assert result.target.name == "vmbr0"


def test_plan_and_derive_picks_replace_for_fixture_b():
    r = FakeRunner(files={"/etc/network/interfaces": FIXTURE_B_IPV4_FALLBACK})
    mode, result = repair_additive.plan_and_derive(r, "vmbr0")
    assert mode == "replace"
    assert result.ok
    assert result.target.name == "vmbr0"


# ===========================================================================
# 4. add_dhcp_stanza - additive rewrite, IPv6 stanza preserved verbatim
# ===========================================================================

def test_add_dhcp_stanza_inserts_before_trailing_source_directive():
    # Real evidence (decision record 12): appending at the absolute end
    # of the file placed the new stanza AFTER the trailing
    # `source /etc/network/interfaces.d/*` line - non-standard Debian/
    # ifupdown2 layout, and a real `ifreload --syntax-check` run treated
    # an unrelated, otherwise-non-fatal bridge-fd warning as fatal
    # specifically against that layout. The fix inserts immediately
    # after the target's own stanza, always before any later `source`
    # line.
    cfg = _cfg(FIXTURE_A_IPV6_ONLY)
    new_files = ic.add_dhcp_stanza(cfg, "vmbr0")
    new_text = new_files["/etc/network/interfaces"]
    expected = (
        "auto lo\niface lo inet loopback\n\niface ens3 inet6 manual\n\n"
        "auto vmbr0\niface vmbr0 inet6 static\n"
        "\taddress fec0::5054:ff:feba:5e12/64\n"
        "\tgateway fe80::2\n"
        "\tbridge-ports ens3\n"
        "\tbridge-stp off\n"
        "\tbridge-fd 0\n\n"
        "iface vmbr0 inet dhcp\n\n"
        "source /etc/network/interfaces.d/*\n"
    )
    assert new_text == expected
    # The new stanza's position, not just its presence: it must appear
    # strictly before the source directive, never after.
    assert new_text.index("iface vmbr0 inet dhcp") < new_text.index("source /etc/network/interfaces.d/*")
    # The existing inet6 stanza is still byte-identical and unmoved.
    assert "iface vmbr0 inet6 static" in new_text
    assert "\taddress fec0::5054:ff:feba:5e12/64" in new_text


def test_add_dhcp_stanza_refuses_when_inet_stanza_already_exists():
    cfg = _cfg(FIXTURE_B_IPV4_FALLBACK)
    try:
        ic.add_dhcp_stanza(cfg, "vmbr0")
        assert False, "must refuse - vmbr0 already has an inet stanza"
    except ic.RewriteError as exc:
        assert "already has an inet stanza" in str(exc)


def test_add_dhcp_stanza_refuses_when_not_confidently_parsed():
    duplicate_name_text = FIXTURE_A_IPV6_ONLY + "\niface vmbr0 inet6 manual\n"  # same name twice -> duplicate
    cfg = _cfg(duplicate_name_text)
    assert not cfg.confidently_parsed
    try:
        ic.add_dhcp_stanza(cfg, "vmbr0")
        assert False, "must refuse on an unconfidently-parsed config"
    except ic.RewriteError as exc:
        assert "not confidently parsed" in str(exc)


def test_ens3_remains_manual_after_reparsing_the_additive_result():
    cfg = _cfg(FIXTURE_A_IPV6_ONLY)
    new_files = ic.add_dhcp_stanza(cfg, "vmbr0")
    # ens3's own stanza (a separate file region) must be byte-identical.
    assert "iface ens3 inet6 manual" in new_files["/etc/network/interfaces"]
    assert new_files["/etc/network/interfaces"].count("iface ens3") == 1


def test_reparsing_the_additive_result_shows_known_documented_duplicate_limitation():
    # Documented, accepted limitation (see add_dhcp_stanza's docstring):
    # re-parsing the post-additive file shows vmbr0 as a duplicate stanza
    # name (same name, two families) - a real gap in this parser's
    # name-only keying, but fail-closed: it means no further automated
    # repair can target vmbr0 again until a human resolves it, not a
    # silent wrong action.
    cfg = _cfg(FIXTURE_A_IPV6_ONLY)
    new_files = ic.add_dhcp_stanza(cfg, "vmbr0")
    reparsed = ic.parse_files(new_files)
    assert "vmbr0" in reparsed.duplicate_names
    assert not reparsed.confidently_parsed


# ===========================================================================
# 4b. ifreload --syntax-check's interactive-vs-scripted exit-code mismatch
# (decision record 13): confirmed directly, real host, real ifupdown2 -
# the identical bridge-fd warning against the identical, UNMODIFIED
# Proxmox-generated file exits 0 run interactively and exits 1 run via
# Python's subprocess module (exactly how this module invokes every
# subprocess). Refusing on every non-zero exit made the repair action
# unusable against a stock installer-generated config with no repair
# involved at all - not specific to the additive stanza.
# ===========================================================================

def test_syntax_check_advisory_only_true_for_warning_only_stderr():
    assert repair._syntax_check_advisory_only('warning: vmbr0: bridge-fd: value of out range "0": valid attribute range: 2-255')


def test_syntax_check_advisory_only_true_for_multiple_warning_lines():
    assert repair._syntax_check_advisory_only(
        "warning: vmbr0: bridge-fd: value of out range \"0\"\nwarning: vmbr0: another advisory note\n")


def test_syntax_check_advisory_only_false_for_genuine_error():
    assert not repair._syntax_check_advisory_only("error: could not parse /etc/network/interfaces: line 12")


def test_syntax_check_advisory_only_false_when_mixed_with_non_warning_line():
    assert not repair._syntax_check_advisory_only(
        "warning: vmbr0: bridge-fd: value of out range \"0\"\nerror: something else is actually wrong\n")


def test_syntax_check_advisory_only_false_for_empty_stderr():
    # A non-zero exit with no explanatory output at all is not something
    # this fail-closed helper is willing to wave through.
    assert not repair._syntax_check_advisory_only("")
    assert not repair._syntax_check_advisory_only("   \n  \n")


# ===========================================================================
# 5. Full additive repair pipeline (mirrors test_repair.py's structure)
# ===========================================================================

def healthy_facts():
    return [{"fact": "nic_detected", "ok": True, "detail": ""},
            {"fact": "driver_bound", "ok": True, "detail": ""},
            {"fact": "carrier_present", "ok": True, "detail": ""},
            {"fact": "address_assigned", "ok": True, "detail": ""},
            {"fact": "gateway_reachable", "ok": True, "detail": ""}]


def broken_facts_fixture_a():
    return [{"fact": "nic_detected", "ok": True, "detail": ""},
            {"fact": "driver_bound", "ok": True, "detail": ""},
            {"fact": "carrier_present", "ok": True, "detail": ""},
            {"fact": "address_assigned", "ok": False, "detail": "no address on default route device"},
            {"fact": "gateway_reachable", "ok": False, "detail": "no default gateway in routing table"}]


def make_additive_runner(files=None, target="vmbr0", new_addr="10.0.2.20/24", gateway="10.0.2.2",
                          clustered=False, protected_session=False, syntax_ok=True, apply_ok=True,
                          verify_ok=True, dns_ok=True, https_ok=True, syntax_advisory_only=False):
    files = files if files is not None else {"/etc/network/interfaces": FIXTURE_A_IPV6_ONLY}
    r = FakeRunner(files=files)
    r.script(lambda a: a == ["ip", "route", "show", "default"], FakeProc(0, "", ""))
    r.script(lambda a: a == ["ip", "-6", "route", "show", "default"],
             FakeProc(0, "default via fe80::2 dev vmbr0\n", ""))
    r.script(lambda a: a[:2] == ["which", "ifreload"], FakeProc(0, "/usr/sbin/ifreload\n", ""))
    r.script(lambda a: a[:1] == ["dpkg-query"], FakeProc(0, "3.2.0", ""))
    r.script(lambda a: a[:1] == ["pvecm"],
             FakeProc(0, "", "") if not clustered else FakeProc(0, "Cluster information\nNodes: 3\n", ""))
    r.script(lambda a: a[:1] == ["ss"],
             FakeProc(0, "State  Recv-Q Send-Q Local Address:Port  Peer Address:Port\n", "") if not protected_session
             else FakeProc(0, "State  Recv-Q Send-Q Local Address:Port  Peer Address:Port\n"
                              "ESTAB  0      0      10.0.2.15:22       10.0.2.99:51000\n", ""))
    r.script(lambda a: a[:1] == ["systemd-run"], FakeProc(0, "", ""))
    r.script(lambda a: a[:2] == ["systemctl", "stop"], FakeProc(0, "", ""))
    if syntax_advisory_only:
        # Real, confirmed shape (decision record 13): non-zero exit, but
        # stderr is entirely a `warning:`-prefixed, advisory-only message.
        r.script(lambda a: a[:2] == ["ifreload", "--syntax-check"],
                 FakeProc(1, "", 'warning: vmbr0: bridge-fd: value of out range "0": valid attribute range: 2-255'))
    else:
        r.script(lambda a: a[:2] == ["ifreload", "--syntax-check"],
                 FakeProc(0, "", "") if syntax_ok else FakeProc(1, "", "syntax error"))
    r.script(lambda a: a == ["ifreload", "-a"],
             FakeProc(0, "", "") if apply_ok else FakeProc(1, "", "ifreload: apply failed"))
    if verify_ok:
        r.script(lambda a: a[:5] == ["ip", "-4", "-o", "addr", "show"],
                 FakeProc(0, f"3: {target}    inet {new_addr} brd 10.0.2.255 scope global {target}\\"
                             f"       valid_lft forever preferred_lft forever\n", ""))
        r.script(lambda a: a[:4] == ["ip", "-4", "route", "show"],
                 FakeProc(0, f"default via {gateway} dev {target}\n", ""))
        r.script(lambda a: a[:1] == ["ping"], FakeProc(0, "", ""))
        r.script(lambda a: a[:2] == ["getent", "hosts"],
                 FakeProc(0, "" if not dns_ok else "199.204.44.128 deb.debian.org\n",
                           "" if dns_ok else "not found"), )
        r.script(lambda a: a[:1] == ["curl"],
                 FakeProc(0, "200" if https_ok else "000", ""))
    else:
        r.script(lambda a: a[:5] == ["ip", "-4", "-o", "addr", "show"], FakeProc(0, "", ""))
        r.script(lambda a: a[:4] == ["ip", "-4", "route", "show"], FakeProc(0, "", ""))
    return r


def test_additive_pipeline_success_fixture_a_produces_bounded_additive_proposal():
    r = make_additive_runner()
    result = repair_additive.add_dhcp_to_bridge(
        r, "vmbr0", "test-operator", operator_present=True,
        check_lifeline_fn=broken_facts_fixture_a)
    assert result.ok
    assert result.outcome == "success"
    final_text = r.files["/etc/network/interfaces"]
    # Additive and bounded: the new stanza is inserted before the
    # trailing source directive, not appended after it (see decision
    # record 12/13 - appending after `source` was the real root cause
    # of the ifreload --syntax-check failure found in the QEMU run).
    assert "iface vmbr0 inet dhcp" in final_text
    assert final_text.index("iface vmbr0 inet dhcp") < final_text.index("source /etc/network/interfaces.d/*")
    assert "iface vmbr0 inet6 static" in final_text


def test_ens3_remains_manual_after_real_pipeline_run():
    r = make_additive_runner()
    repair_additive.add_dhcp_to_bridge(r, "vmbr0", "test-operator", operator_present=True,
                                        check_lifeline_fn=broken_facts_fixture_a)
    assert "iface ens3 inet6 manual" in r.files["/etc/network/interfaces"]


def test_residual_ipv6_stanza_detected_and_logged_not_claimed_repaired():
    r = make_additive_runner()
    repair_additive.add_dhcp_to_bridge(r, "vmbr0", "test-operator", operator_present=True,
                                        check_lifeline_fn=broken_facts_fixture_a)
    events_path = str(network.EVENT_LOG)
    logged = r.files.get(events_path, "")
    assert "residual_config_detected" in logged
    assert '"residual_family": "inet6"' in logged


def test_concurrent_edit_between_backup_and_write_refuses():
    r = make_additive_runner()
    original_read = r.read_text

    calls = {"n": 0}

    target_path = "/etc/network/interfaces"

    def flaky_read(path):
        text = original_read(path)
        # Only count reads of the target path itself (read #1: derivation,
        # #2: backup, #3: pre-write revalidation) - other reads (e.g. the
        # backup module's own byte-verification readback of a *different*
        # path) must not shift this count, matching test_repair.py's own
        # established pattern for this exact scenario.
        if path == target_path:
            calls["n"] += 1
            if calls["n"] == 3:
                return text.replace("bridge-fd 0", "bridge-fd 1")
        return text

    r.read_text = flaky_read
    result = repair_additive.add_dhcp_to_bridge(r, "vmbr0", "test-operator", operator_present=True,
                                                  check_lifeline_fn=broken_facts_fixture_a)
    assert not result.ok
    assert result.outcome == "refused"
    assert "concurrent_config_change" in result.detail
    # No additive line was ever written.
    assert "inet dhcp" not in r.files["/etc/network/interfaces"]


def test_failed_apply_leaves_rollback_armed_original_restorable():
    r = make_additive_runner(apply_ok=False)
    result = repair_additive.add_dhcp_to_bridge(r, "vmbr0", "test-operator", operator_present=True,
                                                  check_lifeline_fn=broken_facts_fixture_a)
    assert not result.ok
    assert result.outcome == "refused"
    assert "apply_failed" in result.detail
    # The independent rollback stays armed per the transactional pipeline's
    # own spec (repair.py, unchanged) - a systemd-run call was made to arm
    # it, and it's still armed since this path never cancels it.
    assert any(c[:1] == ["systemd-run"] for c in r.calls)


def test_failed_syntax_check_restores_exact_original():
    r = make_additive_runner(syntax_ok=False)
    result = repair_additive.add_dhcp_to_bridge(r, "vmbr0", "test-operator", operator_present=True,
                                                  check_lifeline_fn=broken_facts_fixture_a)
    assert not result.ok
    assert "syntax_invalid" in result.detail
    assert r.files["/etc/network/interfaces"] == FIXTURE_A_IPV6_ONLY


def test_advisory_only_syntax_check_warning_does_not_block_the_repair():
    # The real finding (decision record 13): ifreload --syntax-check's
    # non-zero exit against a warning-only, non-interactive invocation
    # must not be treated the same as a genuine syntax error - this is
    # the actual, real-world shape the QEMU integration run hit, and the
    # fix this test locks in.
    r = make_additive_runner(syntax_advisory_only=True)
    result = repair_additive.add_dhcp_to_bridge(r, "vmbr0", "test-operator", operator_present=True,
                                                  check_lifeline_fn=broken_facts_fixture_a)
    assert result.ok
    assert result.outcome == "success"
    assert "iface vmbr0 inet dhcp" in r.files["/etc/network/interfaces"]


def test_advisory_only_syntax_check_warning_does_not_block_replace_path_either():
    # The exact same ifreload behavior would affect the existing replace
    # path (reset_interface_to_dhcp) against Fixture B or any real
    # Proxmox-generated bridge-fd-0 config - not specific to the
    # additive extension, so both call sites needed the fix.
    r = make_additive_runner(files={"/etc/network/interfaces": FIXTURE_B_IPV4_FALLBACK},
                              syntax_advisory_only=True)
    result = repair.reset_interface_to_dhcp(r, "vmbr0", "test-operator", operator_present=True,
                                             check_lifeline_fn=broken_facts_fixture_a)
    assert result.ok
    assert result.outcome == "success"
    assert "iface vmbr0 inet dhcp" in r.files["/etc/network/interfaces"]
    assert "192.168.100.2/24" not in r.files["/etc/network/interfaces"]


def test_successful_dhcp_verifies_address_route_gateway_dns_and_https():
    r = make_additive_runner()
    result = repair_additive.add_dhcp_to_bridge(r, "vmbr0", "test-operator", operator_present=True,
                                                  check_lifeline_fn=broken_facts_fixture_a)
    assert result.ok
    assert any(c[:2] == ["getent", "hosts"] for c in r.calls)
    assert any(c[:1] == ["curl"] for c in r.calls)


def test_dns_failure_fails_verification_even_with_address_and_route_present():
    r = make_additive_runner(dns_ok=False)
    result = repair_additive.add_dhcp_to_bridge(r, "vmbr0", "test-operator", operator_present=True,
                                                  check_lifeline_fn=broken_facts_fixture_a)
    assert not result.ok
    assert result.outcome == "rolled_back"
    assert "DNS resolution" in result.detail


def test_https_failure_fails_verification_even_with_dns_working():
    r = make_additive_runner(https_ok=False)
    result = repair_additive.add_dhcp_to_bridge(r, "vmbr0", "test-operator", operator_present=True,
                                                  check_lifeline_fn=broken_facts_fixture_a)
    assert not result.ok
    assert result.outcome == "rolled_back"
    assert "HTTPS" in result.detail


def test_no_additive_candidate_refuses_cleanly():
    text = "auto lo\niface lo inet loopback\n\niface ens3 inet manual\n"
    r = FakeRunner(files={"/etc/network/interfaces": text})
    r.script(lambda a: a[:2] == ["which", "ifreload"], FakeProc(0, "/usr/sbin/ifreload\n", ""))
    r.script(lambda a: a[:1] == ["dpkg-query"], FakeProc(0, "3.2.0", ""))
    r.script(lambda a: a[:1] == ["pvecm"], FakeProc(0, "", ""))
    result = repair_additive.add_dhcp_to_bridge(r, "ens3", "test-operator", operator_present=True,
                                                  check_lifeline_fn=broken_facts_fixture_a)
    assert not result.ok
    assert "no_additive_candidate" in result.detail


def test_cluster_membership_refuses_additive_path_too():
    r = make_additive_runner(clustered=True)
    result = repair_additive.add_dhcp_to_bridge(r, "vmbr0", "test-operator", operator_present=True,
                                                  check_lifeline_fn=broken_facts_fixture_a)
    assert not result.ok
    assert "cluster_member" in result.detail


# ===========================================================================
# 6. First-boot wiring: discovery, exact-diff proposal, indefinite CONFIRM,
#    package-install gating.
# ===========================================================================

def test_discover_is_read_only_and_safe_unattended():
    r = make_additive_runner()
    d = fbnr.discover(r, check_lifeline_fn=broken_facts_fixture_a)
    assert d["lifeline_ok"] is False
    assert r.writes == []
    assert not any(c[:1] == ["systemd-run"] for c in r.calls)


def test_diagnose_produces_additive_diff_for_fixture_a():
    r = FakeRunner(files={"/etc/network/interfaces": FIXTURE_A_IPV6_ONLY})
    r.script(lambda a: a == ["ip", "route", "show", "default"], FakeProc(0, "", ""))
    r.script(lambda a: a == ["ip", "-6", "route", "show", "default"],
             FakeProc(0, "default via fe80::2 dev vmbr0\n", ""))
    d = fbnr.discover(r, check_lifeline_fn=broken_facts_fixture_a)
    diagnosis = fbnr.diagnose(r, d)
    assert diagnosis["needs_repair"] is True
    assert diagnosis["mode"] == "additive"
    assert diagnosis["target"] == "vmbr0"
    assert diagnosis["diff"]["action"] == "add"
    assert "iface vmbr0 inet dhcp" in diagnosis["diff"]["after"]
    assert "iface vmbr0 inet6 static" in diagnosis["diff"]["before"][0]


def test_declining_authorization_makes_no_change():
    r = make_additive_runner()
    result = fbnr.run_first_boot_network_repair(
        r, stdin=iter(["not confirm\n", ""]), print_fn=lambda *a: None,
        check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "declined"
    assert result["package_install_allowed"] is False
    assert r.files["/etc/network/interfaces"] == FIXTURE_A_IPV6_ONLY
    assert r.writes == []
    assert not any(c[:1] == ["systemd-run"] for c in r.calls)


def test_confirming_proceeds_and_unlocks_package_install_on_success():
    r = make_additive_runner()
    result = fbnr.run_first_boot_network_repair(
        r, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
        check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "additive"
    assert result["package_install_allowed"] is True
    final_text = r.files["/etc/network/interfaces"]
    assert "iface vmbr0 inet dhcp" in final_text
    assert final_text.index("iface vmbr0 inet dhcp") < final_text.index("source /etc/network/interfaces.d/*")


def test_package_install_stays_locked_when_verification_fails():
    r = make_additive_runner(https_ok=False)
    result = fbnr.run_first_boot_network_repair(
        r, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
        check_lifeline_fn=broken_facts_fixture_a)
    assert result["package_install_allowed"] is False


def test_healthy_lifeline_skips_proposal_entirely_and_allows_install():
    r = make_additive_runner()
    result = fbnr.run_first_boot_network_repair(
        r, stdin=iter([]), print_fn=lambda *a: None,
        check_lifeline_fn=healthy_facts)
    assert result["action"] == "none"
    assert result["package_install_allowed"] is True
    assert r.writes == []


def test_eof_on_stdin_never_treated_as_confirmation():
    # wait_for_confirmation must not treat exhausting the iterable (EOF)
    # as confirmation - it returns False (not confirmed), matching
    # Investigation 6's corrected discipline exactly.
    assert fbnr.wait_for_confirmation(iter([])) is False
    assert fbnr.wait_for_confirmation(iter(["", "", ""])) is False


def test_replace_path_still_used_for_fixture_b_through_first_boot_flow():
    r = make_additive_runner(files={"/etc/network/interfaces": FIXTURE_B_IPV4_FALLBACK})
    result = fbnr.run_first_boot_network_repair(
        r, stdin=iter(["CONFIRM\n"]), print_fn=lambda *a: None,
        check_lifeline_fn=broken_facts_fixture_a)
    assert result["action"] == "replace"
    # replace path rewrites the stanza in place - no residual inet6/inet
    # duplication issue, and the file no longer contains the old static
    # address.
    assert "192.168.100.2/24" not in r.files["/etc/network/interfaces"]
    assert "iface vmbr0 inet dhcp" in r.files["/etc/network/interfaces"]
