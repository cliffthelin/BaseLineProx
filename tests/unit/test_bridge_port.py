"""ADR 0001: a bridge whose NIC does not exist on this machine is pointed at the one wired NIC that has a link. Real files under tmp_path
stand in for /sys/class/net and /etc/network/interfaces."""
import bridge_port as bp

INTERFACES = """auto lo
iface lo inet loopback

iface ens4 inet manual

auto vmbr0
iface vmbr0 inet6 static
        address fec0::5054:ff:feba:5e20/64
        gateway fe80::2
        bridge-ports ens4
        bridge-stp off
        bridge-fd 0
iface vmbr0 inet dhcp

source /etc/network/interfaces.d/*
"""


def sysnet(tmp_path, nics, *, extra=()):
    root = tmp_path / "net"
    root.mkdir()
    (root / "lo").mkdir()
    (root / "bonding_masters").write_text("")
    for name, link in nics.items():
        (root / name / "device").mkdir(parents=True)
        if link is not None:
            (root / name / "carrier").write_text("1\n" if link else "0\n")
    for name in extra:
        (root / name / "bridge").mkdir(parents=True)
    return root


def run(tmp_path, nics, text=INTERFACES, **kw):
    root = sysnet(tmp_path, nics, extra=kw.pop("extra", ()))
    interfaces = tmp_path / "interfaces"
    interfaces.write_text(text)
    result = bp.run(interfaces, root, bring_up=False, wait_seconds=0, log=tmp_path / "log", now=lambda: 1000, **kw)
    return result, interfaces.read_text()


def test_a_missing_bridge_port_is_replaced_by_the_one_wired_nic_with_a_link_and_nothing_else_changes(tmp_path):
    result, text = run(tmp_path, {"enp5s0": True, "wlp2s0": False})
    assert result["action"] == "rewrite" and result["nic"] == "enp5s0"
    assert text == INTERFACES.replace("bridge-ports ens4", "bridge-ports enp5s0")
    assert (tmp_path / "interfaces.baseline-bridge-port.1000").read_text() == INTERFACES      # backed up first
    assert '"nic": "enp5s0"' in (tmp_path / "log").read_text()


def test_nothing_is_touched_when_the_bridge_port_exists(tmp_path):
    result, text = run(tmp_path, {"ens4": True, "enp5s0": True})
    assert result["action"] == "none" and text == INTERFACES
    assert not list(tmp_path.glob("interfaces.baseline*"))


def test_two_linked_nics_is_ambiguous_and_is_reported_not_guessed(tmp_path):
    result, text = run(tmp_path, {"enp5s0": True, "enp6s0": True})
    assert result["action"] == "none" and "more than one" in result["reason"] and text == INTERFACES


def test_no_nic_with_a_link_leaves_the_file_alone_and_says_why(tmp_path):
    result, text = run(tmp_path, {"enp5s0": False})
    assert result["action"] == "none" and "no wired NIC" in result["reason"] and text == INTERFACES


def test_a_bridge_and_a_wireless_device_are_never_chosen(tmp_path):
    root = sysnet(tmp_path, {"enp5s0": None}, extra=("vmbr0",))
    (root / "wlp2s0" / "device").mkdir(parents=True)
    (root / "wlp2s0" / "wireless").mkdir()
    (root / "wlp2s0" / "carrier").write_text("1\n")
    assert bp.wired_nics(root) == ["enp5s0"]


def test_a_comment_and_line_endings_survive_and_a_glob_port_is_left_alone():
    text = "iface vmbr0 inet manual\r\n    bridge-ports ens4 # uplink\r\n"
    out = bp.rewrite(text, [{"line": 1, "ports": ["ens4"]}], "enp5s0")
    assert out == "iface vmbr0 inet manual\r\n    bridge-ports enp5s0 # uplink\r\n"
    assert bp.plan("bridge-ports en*\n", {"enp5s0"}, ["enp5s0"])["action"] == "none"
    assert bp.plan("bridge-ports none\n", {"enp5s0"}, ["enp5s0"])["action"] == "none"


def test_a_cellular_modem_is_never_the_uplink_even_when_it_reports_a_link_first(tmp_path):
    """PC601 on a Latitude 5290 (2026-10-12): the WWAN device was bridged and the real ethernet port stayed without a bridge."""
    root = sysnet(tmp_path, {"enp0s31f6": True, "wwp0s20f0u2i12": True})
    (root / "wwp0s20f0u2i12" / "uevent").write_text("DEVTYPE=wwan\n")
    assert bp.wired_nics(root) == ["enp0s31f6"]
    interfaces = tmp_path / "interfaces"
    interfaces.write_text(INTERFACES)
    result = bp.run(interfaces, root, bring_up=False, wait_seconds=0, log=tmp_path / "log", now=lambda: 1000)
    assert result["action"] == "rewrite" and result["nic"] == "enp0s31f6"


def test_a_docked_laptop_uses_its_own_port_not_the_docks_usb_adapter(tmp_path):
    root = sysnet(tmp_path, {"enp0s31f6": True})
    usb = tmp_path / "usbtree" / "usb2" / "2-4"
    usb.mkdir(parents=True)
    (root / "enxd8d09057dda4").mkdir()
    (root / "enxd8d09057dda4" / "device").symlink_to(usb)
    (root / "enxd8d09057dda4" / "carrier").write_text("1\n")
    interfaces = tmp_path / "interfaces"
    interfaces.write_text(INTERFACES)
    result = bp.run(interfaces, root, bring_up=False, wait_seconds=0, log=tmp_path / "log", now=lambda: 1000)
    assert result["action"] == "rewrite" and result["nic"] == "enp0s31f6"
