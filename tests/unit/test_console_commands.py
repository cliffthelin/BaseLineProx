"""The Console tab's command set as plain-text lines (browser parity with the TUI). Collaborators are injected: no real NIC, drive or CLI."""
from types import SimpleNamespace as NS

import console_commands as cc


class Adapter:
    def __init__(self, grant=True):
        self.asked, self.grant = [], grant
        if grant:
            self.grant_write_scope = self._grant
            self.revoke_write_scope = self._revoke

    def new_session(self):
        return NS(write_grant=None, started=False)

    def ask(self, question, session=None):
        self.asked.append((question, session))
        return f"answer to {question}"

    def _grant(self, session, path, authorized_by, now):
        if not path.startswith("/"):
            raise ValueError("scope must be an absolute directory")
        session.write_grant = NS(scope_path=path)
        return session.write_grant

    def _revoke(self, session):
        session.write_grant = None


def env(adapter=None, **over):
    registry = NS(get_adapter=lambda hid: adapter if hid in ("claude", "opencode") else None,
                  supports_write_grant=lambda a: a is not None and hasattr(a, "grant_write_scope"),
                  HarnessAdapterError=RuntimeError)
    base = dict(
        hardware=NS(collect=lambda: ({"raw": 1}, None),
                    normalize=lambda raw: {"machine": {"system": "Dell Latitude", "type": "laptop"},
                                           "cpu": {"model": "i5", "cores": 4}, "memory": {"total": "16G", "used": "3G"},
                                           "system": {"kernel": "7.0", "distro": "Proxmox"}}),
        network=NS(check_lifeline=lambda: [{"fact": "nic_detected", "ok": True, "detail": "enp0s31f6"},
                                           {"fact": "gateway_reachable", "ok": False, "detail": "no route"}]),
        tether=NS(auto_tether=lambda: {"ok": False, "stage": "no_candidate", "detail": "no USB network interface found"}),
        harness_registry=registry, sessions={}, snapshot={"read": lambda: None, "write": lambda d: None}, now=lambda: 1.0)
    base.update(over)
    return cc.Context(**base)


def test_help_lists_every_command_the_tui_console_has():
    out = "\n".join(cc.run("help", env()))
    for word in ("hardware", "network", "tether", "ask <question>", "grant write <directory>", "revoke write"):
        assert word in out


def test_hardware_prints_the_same_fields_and_says_whether_it_changed():
    lines = cc.run("hardware", env())
    assert any("Dell Latitude (laptop)" in l for l in lines) and any("i5 x4" in l for l in lines)
    assert any("no prior snapshot" in l for l in lines)


def test_network_stops_at_the_first_failing_stage_and_names_it():
    lines = cc.run("network", env())
    assert any("nic_detected" in l and "OK" in l for l in lines)
    assert any("Stopped at: gateway_reachable" in l for l in lines)


def test_tether_reports_no_candidate_plainly():
    assert any("No tether device found" in l for l in cc.run("tether", env()))


def test_ask_goes_to_the_selected_harness_with_one_session_that_is_kept():
    adapter = Adapter()
    context = env(adapter)
    assert cc.run("ask is it hot?", context, harness="opencode") == ["answer to is it hot?"]
    cc.run("ask again", context, harness="opencode")
    assert adapter.asked[0][1] is adapter.asked[1][1]                    # the harness's session is reused, as in the TUI
    assert "opencode" in context.sessions and "claude" not in context.sessions


def test_an_unknown_harness_and_unknown_commands_are_said_so():
    assert any("No adapter" in l for l in cc.run("ask x", env(Adapter()), harness="nonesuch"))
    assert any("unknown command" in l and "help" in l for l in cc.run("reboot now", env()))


def test_write_grant_is_scoped_one_time_and_revocable_and_refused_when_unsupported():
    adapter = Adapter()
    context = env(adapter)
    assert any("scoped to /srv/work" in l for l in cc.run("grant write /srv/work", context))
    assert any("revoked" in l for l in cc.run("revoke write", context))
    assert any("No write access was granted" in l for l in cc.run("revoke write", context))
    assert any("scope must be" in l for l in cc.run("grant write relative", context))
    assert any("usage: grant write" in l for l in cc.run("grant write ", context))
    assert any("doesn't support a write grant" in l for l in cc.run("grant write /x", env(Adapter(grant=False))))
