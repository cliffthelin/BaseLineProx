import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import repair
from fake_runner import FakeRunner, FakeProc

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
"""


def healthy_facts():
    return [
        {"fact": "nic_detected", "ok": True, "detail": ""},
        {"fact": "driver_bound", "ok": True, "detail": ""},
        {"fact": "carrier_present", "ok": True, "detail": ""},
        {"fact": "address_assigned", "ok": True, "detail": ""},
        {"fact": "gateway_reachable", "ok": True, "detail": ""},
    ]


def broken_facts():
    return [
        {"fact": "nic_detected", "ok": True, "detail": ""},
        {"fact": "driver_bound", "ok": True, "detail": ""},
        {"fact": "carrier_present", "ok": True, "detail": ""},
        {"fact": "address_assigned", "ok": True, "detail": ""},
        {"fact": "gateway_reachable", "ok": False, "detail": "10.0.2.2: no ping reply"},
    ]


def make_ready_runner(files=None, target="vmbr0", new_addr="10.0.2.20/24", gateway="10.0.2.2",
                       clustered=False, protected_session=False, syntax_ok=True, apply_ok=True,
                       verify_ok=True):
    files = files if files is not None else {"/etc/network/interfaces": VMBR0_BRIDGE}
    r = FakeRunner(files=files)

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
    r.script(lambda a: a[:2] == ["ifreload", "--syntax-check"],
             FakeProc(0, "", "") if syntax_ok else FakeProc(1, "", "syntax error near bridge-ports"))
    r.script(lambda a: a == ["ifreload", "-a"],
             FakeProc(0, "", "") if apply_ok else FakeProc(1, "", "ifreload: apply failed"))

    if verify_ok:
        r.script(lambda a: a[:5] == ["ip", "-4", "-o", "addr", "show"],
                 FakeProc(0, f"3: {target}    inet {new_addr} brd 10.0.2.255 scope global {target}\\       valid_lft forever preferred_lft forever\n", ""))
        r.script(lambda a: a[:4] == ["ip", "-4", "route", "show"],
                 FakeProc(0, f"default via {gateway} dev {target}\n", ""))
        r.script(lambda a: a[:1] == ["ping"], FakeProc(0, "", ""))
    else:
        r.script(lambda a: a[:5] == ["ip", "-4", "-o", "addr", "show"], FakeProc(0, "", ""))
        r.script(lambda a: a[:4] == ["ip", "-4", "route", "show"], FakeProc(0, "", ""))

    return r


@pytest.fixture
def ready_runner():
    return make_ready_runner()
