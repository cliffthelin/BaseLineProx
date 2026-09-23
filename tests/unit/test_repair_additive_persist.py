"""Unit tests for repair_additive_persist.py - decision record 17's
confirmed reboot-persistence gap and its fix. All FakeRunner-scripted,
no real subprocess/device access."""
from fake_runner import FakeRunner, FakeProc
import repair
import repair_additive_persist as persist

ADDITIVE_INTERFACES = """auto lo
iface lo inet loopback

iface vmbr0 inet6 static
\taddress fec0::5054:ff:feba:5e12/64
\tgateway fe80::2
\tbridge-ports ens3
\tbridge-stp off
\tbridge-fd 0

iface vmbr0 inet dhcp

source /etc/network/interfaces.d/*
"""

NON_ADDITIVE_INTERFACES = """auto lo
iface lo inet loopback

auto vmbr0
iface vmbr0 inet static
\taddress 192.168.1.2/24
\tgateway 192.168.1.1
\tbridge-ports ens3
\tbridge-stp off
\tbridge-fd 0

source /etc/network/interfaces.d/*
"""


def _runner_with(interfaces_text, ip_addr_output=""):
    r = FakeRunner(files={repair.INTERFACES_PATH: interfaces_text})
    r.script(lambda a: a[:4] == ["ip", "-4", "-o", "addr"],
              FakeProc(0, ip_addr_output, ""))
    return r


def test_reapplies_dhclient_when_additive_stanza_present_and_no_ipv4():
    r = _runner_with(ADDITIVE_INTERFACES, ip_addr_output="")
    r.script(lambda a: a[:1] == ["dhclient"], FakeProc(0, "", ""))

    events = persist.reapply_additive_dhcp(r)

    assert len(events) == 1
    assert events[0]["interface"] == "vmbr0"
    assert events[0]["status"] == "pass"
    assert ["dhclient", "vmbr0"] in r.calls


def test_does_nothing_when_ipv4_already_present():
    r = _runner_with(ADDITIVE_INTERFACES,
                      ip_addr_output="3: vmbr0    inet 10.0.2.15/24 brd 10.0.2.255 scope global vmbr0")

    events = persist.reapply_additive_dhcp(r)

    assert events == []
    assert not any(c[:1] == ["dhclient"] for c in r.calls)


def test_does_nothing_for_non_additive_config():
    r = _runner_with(NON_ADDITIVE_INTERFACES, ip_addr_output="")

    events = persist.reapply_additive_dhcp(r)

    assert events == []
    assert not any(c[:1] == ["dhclient"] for c in r.calls)


def test_does_not_touch_a_duplicate_name_without_a_dhcp_stanza():
    # Two static stanzas for the same name (a hand-edited-file case,
    # not this project's additive-repair shape) - must not be treated
    # as if it were an additive-dhcp duplicate.
    text = """auto lo
iface lo inet loopback

iface vmbr0 inet static
\taddress 192.168.1.2/24

iface vmbr0 inet static
\taddress 192.168.1.3/24
"""
    r = _runner_with(text, ip_addr_output="")

    events = persist.reapply_additive_dhcp(r)

    assert events == []
    assert not any(c[:1] == ["dhclient"] for c in r.calls)


def test_records_failure_event_when_dhclient_fails():
    r = _runner_with(ADDITIVE_INTERFACES, ip_addr_output="")
    r.script(lambda a: a[:1] == ["dhclient"], FakeProc(2, "", "dhclient: no lease obtained"))

    events = persist.reapply_additive_dhcp(r)

    assert len(events) == 1
    assert events[0]["status"] == "fail"
    assert "no lease obtained" in events[0]["detail"]


def test_idempotent_second_run_after_success_does_nothing():
    r = _runner_with(ADDITIVE_INTERFACES, ip_addr_output="")
    r.script(lambda a: a[:1] == ["dhclient"], FakeProc(0, "", ""))
    persist.reapply_additive_dhcp(r)

    # Simulate the address now being present (as it would be after a
    # real successful dhclient run) and re-run - must be a no-op.
    r2 = _runner_with(ADDITIVE_INTERFACES,
                       ip_addr_output="3: vmbr0    inet 10.0.2.15/24 brd 10.0.2.255 scope global vmbr0")
    events = persist.reapply_additive_dhcp(r2)

    assert events == []
