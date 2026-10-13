"""One builder of Network rows for the TUI tab and the web /network page (browser parity). `network` is injected, so no real NIC is read."""
import network_view as nv


class Net:
    class NetworkProbeError(Exception):
        pass

    @staticmethod
    def friendly_name(name, show):
        return {"vmbr0": "Bridge", "enp0s31f6": "Ethernet"}.get(name, name) + (f" ({name})" if show else "")

    @staticmethod
    def _bridge_members(dev):
        return {"enp0s31f6"}

    @staticmethod
    def interface_traffic_label(dev):
        return "rx 1.0 MB tx 2.0 MB"


FACTS = [{"fact": "address_assigned", "ok": True, "detail": "vmbr0: 10.0.0.133"},
         {"fact": "internet_reachable", "ok": True, "detail": "ok"}]
IFACES = [{"name": "enp0s31f6", "carrier": True, "wired": True, "driver_bound": True},
          {"name": "wwp0s20f0u2i12", "carrier": False, "wired": False, "driver_bound": True},
          {"name": "enx1", "carrier": False, "wired": True, "driver_bound": True}]
PROVIDERS = [{"name": "Claude Subscription", "state": "unconfigured", "detail": "no Claude credential configured"},
             {"name": "Ollama (local)", "state": "unreachable", "detail": "refused"}]


def test_the_active_connection_comes_first_with_its_address_and_the_bridge_member_is_not_listed_twice():
    rows = nv.build_rows(FACTS, IFACES, PROVIDERS, Net)
    ordered = nv.sort_rows(rows)
    assert ordered[0][2:4] == ("Ethernet", "Active") and "10.0.0.133" in ordered[0][4]
    assert [r for r in rows if r[2] == "Ethernet"] and len([r for r in rows if r[0] == "iface:enp0s31f6"]) == 1


def test_a_wired_link_without_carrier_is_unreachable_and_a_modem_without_one_is_only_available():
    rows = {r[0]: r for r in nv.build_rows(FACTS, IFACES, PROVIDERS, Net)}
    assert rows["iface:enx1"][3] == "Unreachable" and rows["iface:wwp0s20f0u2i12"][3] == "Available"


def test_every_status_a_row_can_carry_is_ordered_and_styled_including_not_set_up():
    """'Not set up' (a provider without credentials) used to be missing here and would have blanked the TUI table."""
    rows = nv.build_rows(FACTS, IFACES, PROVIDERS, Net)
    statuses = {r[3] for r in rows}
    assert "Not set up" in statuses
    assert statuses <= set(nv.STATUS_ORDER) and statuses <= set(nv.STATUS_STYLE)
    nv.sort_rows(rows)                                       # does not raise


def test_the_page_lists_the_rows_with_their_status_and_escapes_values():
    html = nv.render([("k", "Network", "<b>x</b>", "Active", "10.0.0.1")]).decode()
    assert "&lt;b&gt;x&lt;/b&gt;" in html and "Active" in html
