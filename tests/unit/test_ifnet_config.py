import ifnet_config as ic

PHYSICAL_STATIC = """auto lo
iface lo inet loopback

auto enp0s31f6
iface enp0s31f6 inet static
    address 192.168.1.50/24
    netmask 255.255.255.0
    gateway 192.168.1.1
"""

VMBR0_BRIDGE = """auto lo
iface lo inet loopback

iface enp0s31f6 inet manual

auto vmbr0
iface vmbr0 inet static
    address 10.0.2.15/24
    netmask 255.255.255.0
    gateway 10.0.2.2
    bridge-ports enp0s31f6
    bridge-stp off
    bridge-fd 0
"""


def test_parse_physical_static():
    cfg = ic.parse_files({"/etc/network/interfaces": PHYSICAL_STATIC})
    assert cfg.confidently_parsed
    st = cfg.stanzas["enp0s31f6"]
    assert st.family == "inet" and st.method == "static"
    assert st.options["address"] == "192.168.1.50/24"
    assert st.options["gateway"] == "192.168.1.1"
    assert ic.classify(st) == "physical"


def test_parse_bridge():
    cfg = ic.parse_files({"/etc/network/interfaces": VMBR0_BRIDGE})
    assert cfg.confidently_parsed
    bridge = cfg.stanzas["vmbr0"]
    assert ic.classify(bridge) == "bridge"
    assert ic.bridge_members(bridge) == ["enp0s31f6"]
    member = cfg.stanzas["enp0s31f6"]
    assert member.method == "manual"
    assert ic.classify(member) == "physical"


def test_duplicate_stanza_breaks_confidence():
    text = PHYSICAL_STATIC + "\niface enp0s31f6 inet dhcp\n"
    cfg = ic.parse_files({"/etc/network/interfaces": text})
    assert not cfg.confidently_parsed
    assert "enp0s31f6" in cfg.duplicate_names


def test_unrecognized_directive_breaks_confidence():
    text = PHYSICAL_STATIC + "\nmapping enp0s31f6\n    script /bin/true\n"
    cfg = ic.parse_files({"/etc/network/interfaces": text})
    assert not cfg.confidently_parsed
    assert any("mapping" in line for _p, _n, line in cfg.unparsed_lines)


def test_rewrite_static_to_dhcp_touches_only_target_stanza():
    text = VMBR0_BRIDGE
    cfg = ic.parse_files({"/etc/network/interfaces": text})
    out = ic.rewrite_stanza_to_dhcp(cfg, "vmbr0")
    new_text = out["/etc/network/interfaces"]
    assert "iface vmbr0 inet dhcp" in new_text
    assert "address 10.0.2.15/24" not in new_text
    # Everything about the physical member is untouched, byte for byte.
    assert "iface enp0s31f6 inet manual" in new_text
    # Nothing before the bridge stanza changed.
    assert new_text.split("iface vmbr0")[0] == text.split("iface vmbr0")[0]


def test_rewrite_refuses_non_static_stanza():
    cfg = ic.parse_files({"/etc/network/interfaces": VMBR0_BRIDGE})
    try:
        ic.rewrite_stanza_to_dhcp(cfg, "enp0s31f6")
        assert False, "should have refused a manual stanza"
    except ic.RewriteError:
        pass


def test_rewrite_refuses_missing_stanza():
    cfg = ic.parse_files({"/etc/network/interfaces": VMBR0_BRIDGE})
    try:
        ic.rewrite_stanza_to_dhcp(cfg, "nope0")
        assert False
    except ic.RewriteError:
        pass


def test_rewrite_refuses_when_not_confidently_parsed():
    text = PHYSICAL_STATIC + "\nmapping enp0s31f6\n    script /bin/true\n"
    cfg = ic.parse_files({"/etc/network/interfaces": text})
    try:
        ic.rewrite_stanza_to_dhcp(cfg, "enp0s31f6")
        assert False
    except ic.RewriteError:
        pass


def test_closure_hash_stable_and_order_independent():
    files_a = {"/etc/network/interfaces": VMBR0_BRIDGE, "/etc/network/interfaces.d/extra": "auto foo\n"}
    files_b = {"/etc/network/interfaces.d/extra": "auto foo\n", "/etc/network/interfaces": VMBR0_BRIDGE}
    assert ic.hash_closure(files_a) == ic.hash_closure(files_b)


def test_closure_hash_changes_on_any_file_change():
    files = {"/etc/network/interfaces": VMBR0_BRIDGE}
    h1 = ic.hash_closure(files)
    files2 = dict(files)
    files2["/etc/network/interfaces"] = VMBR0_BRIDGE + "\n# comment\n"
    h2 = ic.hash_closure(files2)
    assert h1 != h2
