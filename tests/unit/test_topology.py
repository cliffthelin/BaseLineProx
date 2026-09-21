import ifnet_config as ic
import topology as topo

VMBR0_BRIDGE = """auto lo
iface lo inet loopback

iface enp0s31f6 inet manual

auto vmbr0
iface vmbr0 inet static
    address 10.0.2.15/24
    gateway 10.0.2.2
    bridge-ports enp0s31f6
"""

PHYSICAL_STATIC = """auto lo
iface lo inet loopback

auto enp0s31f6
iface enp0s31f6 inet static
    address 192.168.1.50/24
    gateway 192.168.1.1
"""

BOND_PLUS_BRIDGE = """auto lo
iface lo inet loopback

iface eth0 inet manual
iface eth1 inet manual

auto bond0
iface bond0 inet manual
    bond-slaves eth0 eth1
    bond-mode active-backup

auto vmbr0
iface vmbr0 inet static
    address 10.0.2.15/24
    gateway 10.0.2.2
    bridge-ports bond0
"""

VLAN_IFACE = """auto lo
iface lo inet loopback

iface eth0 inet manual

auto eth0.10
iface eth0.10 inet static
    address 10.10.0.5/24
    gateway 10.10.0.1
    vlan-raw-device eth0
"""

AMBIGUOUS_TWO_BRIDGES = """auto lo
iface lo inet loopback

iface eth0 inet manual

auto vmbr0
iface vmbr0 inet static
    address 10.0.2.15/24
    gateway 10.0.2.2
    bridge-ports eth0

auto vmbr1
iface vmbr1 inet static
    address 10.0.3.15/24
    gateway 10.0.3.2
    bridge-ports eth0
"""


def _cfg(text):
    return ic.parse_files({"/etc/network/interfaces": text})


def test_direct_physical_static_target():
    result = topo.derive_target("enp0s31f6", _cfg(PHYSICAL_STATIC))
    assert result.ok
    assert result.target.name == "enp0s31f6"
    assert result.target.kind == "physical"


def test_standard_vmbr0_bridge_from_bridge_itself():
    # The common real case: network.py's own route lookup already names
    # the bridge (it carries the default route), so the walk is trivial.
    result = topo.derive_target("vmbr0", _cfg(VMBR0_BRIDGE))
    assert result.ok
    assert result.target.name == "vmbr0"
    assert result.target.kind == "bridge"
    assert result.target.physical_devices == ["enp0s31f6"]


def test_standard_vmbr0_bridge_from_physical_member():
    # v1's mistake: assuming the physical member itself is the target.
    # The walk must find the bridge instead, not the manual physical stanza.
    result = topo.derive_target("enp0s31f6", _cfg(VMBR0_BRIDGE))
    assert result.ok
    assert result.target.name == "vmbr0"
    assert result.target.kind == "bridge"


def test_bond_plus_bridge_two_level_walk():
    result = topo.derive_target("eth0", _cfg(BOND_PLUS_BRIDGE))
    assert result.ok
    assert result.target.name == "vmbr0"
    assert sorted(result.target.physical_devices) == ["eth0", "eth1"]


def test_vlan_interface():
    result = topo.derive_target("eth0", _cfg(VLAN_IFACE))
    assert result.ok
    assert result.target.name == "eth0.10"
    assert result.target.kind == "vlan"


def test_ambiguous_topology_refuses():
    result = topo.derive_target("eth0", _cfg(AMBIGUOUS_TWO_BRIDGES))
    assert not result.ok
    names = sorted(c.name for c in result.candidates)
    assert names == ["vmbr0", "vmbr1"]
    assert "multiple" in result.reason


def test_no_static_config_anywhere_refuses():
    text = "auto lo\niface lo inet loopback\n\niface enp0s31f6 inet manual\n"
    result = topo.derive_target("enp0s31f6", _cfg(text))
    assert not result.ok
    assert result.candidates == []


def test_unknown_device_refuses():
    result = topo.derive_target("ghost0", _cfg(VMBR0_BRIDGE))
    assert not result.ok
