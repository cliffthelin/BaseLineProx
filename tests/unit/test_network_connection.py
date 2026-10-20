import network_connection as nc
import network_connection_page as ncp


class Net:
    def __init__(self, fail_alias=False, power_ok=True):
        self.calls, self.fail_alias, self.power_ok = [], fail_alias, power_ok

    def save_alias(self, ifname, alias):
        self.calls.append(("alias", ifname, alias))
        if self.fail_alias:
            raise OSError("read-only")

    def set_admin_state(self, ifname, up):
        self.calls.append(("power", ifname, up))
        return self.power_ok, f"{ifname} {'up' if up else 'down'}"


class Pref:
    def __init__(self):
        self.calls = []

    def apply_primary(self, dev):
        self.calls.append(("primary", dev))
        return True, "primary set"

    def save_preference(self, fallback=None):
        self.calls.append(("fallback", fallback))


def test_alias_power_and_role_are_applied_in_order():
    net, pref = Net(), Pref()
    msgs, failed = nc.apply_changes(net, pref, "eth0", alias="Office", power_on=False, admin_up_at_open=True, role="primary")
    assert not failed and net.calls == [("alias", "eth0", "Office"), ("power", "eth0", False)] and pref.calls == [("primary", "eth0")]
    assert msgs == ["eth0 down", "primary set"]


def test_power_untouched_when_unchanged_or_unreadable():
    net = Net()
    nc.apply_changes(net, Pref(), "eth0", alias="", power_on=True, admin_up_at_open=True, role=None)
    nc.apply_changes(net, Pref(), "eth0", alias="", power_on=False, admin_up_at_open=None, role=None)
    assert [c for c in net.calls if c[0] == "power"] == []


def test_failures_are_reported_and_fallback_is_saved():
    net, pref = Net(fail_alias=True, power_ok=False), Pref()
    msgs, failed = nc.apply_changes(net, pref, "eth0", alias="x", power_on=False, admin_up_at_open=True, role="fallback")
    assert failed and any("alias" in m for m in msgs) and pref.calls == [("fallback", "eth0")]


def test_unknown_role_is_refused_before_anything_changes():
    net = Net()
    assert nc.apply_changes(net, Pref(), "eth0", alias="x", power_on=True, admin_up_at_open=True, role="boss")[1] is True and net.calls == []


def test_lifeline_text_only_for_the_active_connection():
    facts = [{"fact": "nic_detected", "ok": True, "detail": "eth0"}]
    assert "Not currently carrying" in nc.lifeline_text(facts, False)
    text = nc.lifeline_text(facts, True)
    assert "OK  NIC detected: eth0" in text and "Driver bound: not reached" in text


def test_page_has_the_tui_dialogs_controls_and_warns_for_the_active_connection():
    page = ncp.render("eth0", "Ethernet", ["Device: eth0"], "", "", True, {"primary": "eth0"}, "x", is_active=True).decode()
    assert 'name="alias"' in page and 'name="power" checked' in page and 'value="primary" checked' in page and "disconnect this page" in page
