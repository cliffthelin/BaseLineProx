# Tests

`tests/unit/` - automated, no real device/root/network access, run with
`pytest` (see `pytest.ini`; `pythonpath = baseline/lib` so tests import the
app's modules the same way `bin/baseline` does, no install step needed).
Everything here uses an in-memory `FakeRunner`
(`tests/unit/fake_runner.py`) instead of real `subprocess`/filesystem calls
- no test in this suite ever invokes a real `ip`, `ifreload`, `dhclient`,
`systemd-run`, or `pvecm`, and none writes outside its own fixture data.

`tests/console_font_check.sh` (pre-existing) is a manual/deploy-time check
against a real console, not part of this suite.

**Integration test requirement (not yet satisfied):** per
`docs/design/reset-interface-to-dhcp-plan.md`, `reset_interface_to_dhcp`
needs a pass against real `ifreload`/bridge topology/DHCP acquisition/
systemd rollback in an isolated network namespace or a disposable Proxmox
VM with console access and a recoverable snapshot, before it's ever run on
the physical Baseline host. That test doesn't exist yet - this unit suite
proves the Python logic is internally consistent, not that it works
end-to-end against real `ifupdown2`.
